"""ComfyUI workflow 导入/转换器（P0 · 透传线）。

职责：把用户从 ComfyUI 复制的 workflow JSON 规范成可直接提交给内置引擎
`/prompt` 接口的 graph prompt。核心思想是「透传而非复刻」——只做格式识别、
UI→graph 转换与结构校验，不重写任何节点逻辑。

设计原则：
- 纯数据转换，无重依赖、不 import torch/diffusers；可安全 import，不阻塞启动。
- 兼容两种输入：UI workflow JSON（界面导出，含 nodes/links）与 graph 格式（API 用）。
- widget 参数采用启发式映射（widget 槽按定义顺序与 widgets_values 对齐），
  精确映射与节点定义校验可经 object_info 可选注入（P1 完善）。
- 失败不抛裸异常：解析问题记入结果的 errors/warnings，交由上层诚实展示。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class WorkflowParseResult:
    """workflow 解析结果（透传给内置引擎前的中转结构）。"""

    raw_format: str = "unknown"                              # "ui" | "graph" | "unknown"
    graph_prompt: Dict[str, Any] = field(default_factory=dict)  # 可直接提交 /prompt
    node_ids: List[str] = field(default_factory=list)
    class_types: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)          # 致命：导致不可执行
    warnings: List[str] = field(default_factory=list)        # 非致命
    missing_nodes: List[str] = field(default_factory=list)   # object_info 中未定义的节点类

    @property
    def is_executable(self) -> bool:
        """是否具备执行条件（无致命错误且存在至少一个节点）。"""
        return len(self.errors) == 0 and len(self.graph_prompt) > 0


class ComfyUIWorkflowImporter:
    """ComfyUI workflow 导入器（P0 透传线）。

    使用方式：
        from app.core.ai.workflow_importer import workflow_importer
        result = workflow_importer.parse(raw_dict, object_info=object_info)
        if result.is_executable:
            prompt = result.graph_prompt  # 提交给 /prompt
    """

    # ────────────── 公共接口 ──────────────

    def parse(self, raw: Dict[str, Any],
              object_info: Optional[Dict[str, Any]] = None) -> WorkflowParseResult:
        """解析任意 workflow 输入为统一 graph prompt。

        参数：
            raw:            用户粘贴/导入的 workflow（UI JSON 或 graph 格式均可）
            object_info:    内置引擎 /object_info 返回的节点定义（可选，用于精确校验）
        """
        result = WorkflowParseResult(raw_format=self.detect_format(raw))
        if result.raw_format == "unknown":
            result.errors.append("无法识别的 workflow 格式：既无 nodes 数组，也非 graph 对象")
            return result

        try:
            if result.raw_format == "ui":
                graph = self.ui_to_graph(raw)
            else:
                graph = self.normalize_graph(raw)
            result.graph_prompt = graph
            result.node_ids = list(graph.keys())
            result.class_types = [node.get("class_type", "") for node in graph.values()]
        except Exception as e:  # 解析异常一律记入 errors，不向上抛
            logger.warning(f"[WorkflowImporter] 解析失败: {e}")
            result.errors.append(f"解析异常: {e}")
            return result

        # schema 校验（object_info 可选）
        errors, warnings, missing = self.validate(graph, object_info)
        result.errors.extend(errors)
        result.warnings.extend(warnings)
        result.missing_nodes = missing
        return result

    def detect_format(self, raw: Dict[str, Any]) -> str:
        """识别输入格式：ui / graph / unknown。"""
        if not isinstance(raw, dict) or not raw:
            return "unknown"
        if "nodes" in raw and isinstance(raw.get("nodes"), list):
            return "ui"
        if all(isinstance(v, dict) and "class_type" in v
               for v in raw.values() if v is not None):
            return "graph"
        return "unknown"

    def ui_to_graph(self, ui: Dict[str, Any]) -> Dict[str, Any]:
        """UI workflow JSON → graph prompt（透传核心）。

        转换规则（与 ComfyUI 前端一致）：
          · nodes[].type       → class_type
          · 连接型输入(link≠null)  → ["源节点id", 源输出槽]
          · widget 输入(link=null) → 按顺序取 widgets_values
        """
        nodes = ui.get("nodes") or []
        link_map = self._build_link_map(ui.get("links") or [])

        graph: Dict[str, Any] = {}
        for node in nodes:
            if not isinstance(node, dict) or "id" not in node or "type" not in node:
                continue
            node_id = str(node["id"])
            inputs: Dict[str, Any] = {}
            widgets_values = node.get("widgets_values") or []
            # ComfyUI 导出时 widget 输入带 "widget" 元数据；据此判定，缺失则回退按序对齐
            input_defs = [i for i in (node.get("inputs") or []) if isinstance(i, dict)]
            has_widget_meta = any(bool(i.get("widget")) for i in input_defs)
            widget_index = 0                     # widget 值游标
            for inp in input_defs:
                name = inp.get("name")
                if not name:
                    continue
                link_id = inp.get("link")
                if link_id is not None:
                    link = link_map.get(link_id)
                    if link is not None:
                        # link 格式 [id, 源节点id, 源输出槽, 目标节点id, 目标输入槽, 类型]
                        inputs[name] = [str(link[1]), int(link[2])]
                    # 悬空连线（无对应 link 记录）→ 跳过，由 validate 告警
                    continue
                # 无连线：有 widget 元数据则按它判定；否则回退为按序取 widgets_values
                is_widget = bool(inp.get("widget")) if has_widget_meta else True
                if is_widget and widget_index < len(widgets_values):
                    inputs[name] = widgets_values[widget_index]
                    widget_index += 1
                # 其余（非 widget 的可选输入或 widget 已耗尽）→ 跳过
            graph[node_id] = {"class_type": node["type"], "inputs": inputs}
        return graph

    def normalize_graph(self, graph: Dict[str, Any]) -> Dict[str, Any]:
        """graph 格式直接透传（键统一为字符串，值保留原样）。"""
        normalized: Dict[str, Any] = {}
        for node_id, node in graph.items():
            if not isinstance(node, dict):
                continue
            normalized[str(node_id)] = node
        return normalized

    def validate(self, graph: Dict[str, Any],
                 object_info: Optional[Dict[str, Any]] = None
                 ) -> Tuple[List[str], List[str], List[str]]:
        """结构校验；object_info 可选，提供则检查节点类是否已定义。

        返回 (errors, warnings, missing_nodes)。
        """
        errors: List[str] = []
        warnings: List[str] = []
        missing: List[str] = []
        if not graph:
            errors.append("graph 为空，无可执行节点")
            return errors, warnings, missing

        node_ids = set(graph.keys())

        # 1. 引用完整性：inputs 里的 [node_id, slot] 必须指向存在的节点
        for node_id, node in graph.items():
            if not node.get("class_type"):
                warnings.append(f"节点 {node_id} 缺少 class_type")
            for inp_name, value in (node.get("inputs") or {}).items():
                if self._is_link_ref(value) and str(value[0]) not in node_ids:
                    warnings.append(f"节点 {node_id}.{inp_name} 引用了不存在的节点 {value[0]}")

        # 2. object_info 节点类存在性校验
        if object_info:
            for node_id, node in graph.items():
                class_type = node.get("class_type", "")
                if class_type and class_type not in object_info:
                    missing.append(class_type)
        return errors, warnings, missing

    # ────────────── 工具方法 ──────────────

    @staticmethod
    def _build_link_map(raw_links: List[Any]) -> Dict[int, list]:
        """link_id → link 数组映射；忽略畸形 link。"""
        link_map: Dict[int, list] = {}
        for link in raw_links:
            if isinstance(link, (list, tuple)) and len(link) >= 6:
                try:
                    link_map[int(link[0])] = list(link)
                except (TypeError, ValueError):
                    continue
        return link_map

    @staticmethod
    def _is_link_ref(value: Any) -> bool:
        """判断 graph input 值是否为节点/槽引用 [node_id, slot]。"""
        return (
            isinstance(value, (list, tuple))
            and len(value) == 2
            and isinstance(value[1], int)
        )


# 全局便捷引用
workflow_importer = ComfyUIWorkflowImporter()


if __name__ == "__main__":
    """命令行自测：解析一份典型 SDXL 文生图 workflow 并打印转换结果。

    运行方式：
        python app/core/ai/workflow_importer.py
    """
    logging.basicConfig(level=logging.INFO)
    import json

    # 一份最小但结构完整的 UI workflow（Checkpoint → CLIP 双编码 → KSampler → VAE → Save）
    sample_ui = {
        "last_node_id": 9,
        "nodes": [
            {"id": 4, "type": "CheckpointLoaderSimple",
             "inputs": [{"name": "ckpt_name", "type": "COMBO", "link": None,
                         "widget": {"name": "ckpt_name"}}],
             "outputs": [{"name": "MODEL", "type": "MODEL", "links": [10]},
                         {"name": "CLIP", "type": "CLIP", "links": [11]},
                         {"name": "VAE", "type": "VAE", "links": [12]}],
             "widgets_values": ["sd_xl_base_1.0.safetensors"]},
            {"id": 6, "type": "CLIPTextEncode",
             "inputs": [{"name": "text", "type": "STRING", "link": None,
                         "widget": {"name": "text"}},
                        {"name": "clip", "type": "CLIP", "link": 11}],
             "outputs": [{"name": "CONDITIONING", "type": "CONDITIONING", "links": [13]}],
             "widgets_values": ["a cinematic photo of a mountain at sunset"]},
            {"id": 7, "type": "CLIPTextEncode",
             "inputs": [{"name": "text", "type": "STRING", "link": None,
                         "widget": {"name": "text"}},
                        {"name": "clip", "type": "CLIP", "link": 11}],
             "outputs": [{"name": "CONDITIONING", "type": "CONDITIONING", "links": [14]}],
             "widgets_values": ["blurry, low quality"]},
            {"id": 5, "type": "EmptyLatentImage",
             "inputs": [{"name": "width", "type": "INT", "link": None, "widget": {"name": "width"}},
                        {"name": "height", "type": "INT", "link": None, "widget": {"name": "height"}},
                        {"name": "batch_size", "type": "INT", "link": None, "widget": {"name": "batch_size"}}],
             "outputs": [{"name": "LATENT", "type": "LATENT", "links": [15]}],
             "widgets_values": [1024, 1024, 1]},
            {"id": 3, "type": "KSampler",
             "inputs": [{"name": "model", "type": "MODEL", "link": 10},
                        {"name": "positive", "type": "CONDITIONING", "link": 13},
                        {"name": "negative", "type": "CONDITIONING", "link": 14},
                        {"name": "latent_image", "type": "LATENT", "link": 15},
                        {"name": "seed", "type": "INT", "link": None, "widget": {"name": "noise_seed"}},
                        {"name": "steps", "type": "INT", "link": None, "widget": {"name": "steps"}},
                        {"name": "cfg", "type": "FLOAT", "link": None, "widget": {"name": "cfg"}},
                        {"name": "sampler_name", "type": "COMBO", "link": None, "widget": {"name": "sampler_name"}},
                        {"name": "scheduler", "type": "COMBO", "link": None, "widget": {"name": "scheduler"}},
                        {"name": "denoise", "type": "FLOAT", "link": None, "widget": {"name": "denoise"}}],
             "outputs": [{"name": "LATENT", "type": "LATENT", "links": [16]}],
             "widgets_values": [42, 20, 7.0, "euler", "normal", 1.0]},
            {"id": 8, "type": "VAEDecode",
             "inputs": [{"name": "samples", "type": "LATENT", "link": 16},
                        {"name": "vae", "type": "VAE", "link": 12}],
             "outputs": [{"name": "IMAGE", "type": "IMAGE", "links": [17]}],
             "widgets_values": []},
            {"id": 9, "type": "SaveImage",
             "inputs": [{"name": "images", "type": "IMAGE", "link": 17},
                        {"name": "filename_prefix", "type": "STRING", "link": None,
                         "widget": {"name": "filename_prefix"}}],
             "outputs": [],
             "widgets_values": ["ComfyUI"]},
        ],
        "links": [
            [10, 4, 0, 3, 0, "MODEL"],
            [11, 4, 1, 6, 1, "CLIP"],
            [12, 4, 2, 8, 1, "VAE"],
            [13, 6, 0, 3, 1, "CONDITIONING"],
            [14, 7, 0, 3, 2, "CONDITIONING"],
            [15, 5, 0, 3, 3, "LATENT"],
            [16, 3, 0, 8, 0, "LATENT"],
            [17, 8, 0, 9, 0, "IMAGE"],
        ],
    }

    result = workflow_importer.parse(sample_ui)
    logger.info(json.dumps({
        "raw_format": result.raw_format,
        "is_executable": result.is_executable,
        "node_ids": result.node_ids,
        "class_types": result.class_types,
        "missing_nodes": result.missing_nodes,
        "errors": result.errors,
        "warnings": result.warnings,
        "graph_prompt": result.graph_prompt,
    }, ensure_ascii=False, indent=2))