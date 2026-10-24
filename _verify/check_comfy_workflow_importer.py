"""ComfyUI workflow 导入器回归测试（纯数据转换，无 torch/diffusers 依赖）。

覆盖：格式识别 / UI→graph 透传 / widget 启发式映射 / 引用完整性校验 /
缺失节点检测 / 损坏输入诚实失败。可直接跑：
    python _verify/check_comfy_workflow_importer.py
"""
import json
import sys
import os

# 直接把 workflow_importer 模块路径加入 sys.path 后按文件加载，
# 避免触发 app.core.__init__ 里的 wmic（沙箱黑名单）。
_IMPORTER = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "app", "core", "ai", "workflow_importer.py",
)


def _load():
    import importlib.util
    import sys as _sys
    spec = importlib.util.spec_from_file_location("workflow_importer", _IMPORTER)
    mod = importlib.util.module_from_spec(spec)
    # 关键：把模块注册进 sys.modules，否则 @dataclass + from __future__ annotations
    # 的延迟类型求值会因 module 不在 sys.modules 而抛 AttributeError
    _sys.modules["workflow_importer"] = mod
    spec.loader.exec_module(mod)
    return mod


# 一份最小但结构完整的 SDXL 文生图 UI workflow（Checkpoint → CLIP → KSampler → VAE → Save）
SAMPLE_UI = {
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
         "inputs": [{"name": "text", "type": "STRING", "link": None, "widget": {"name": "text"}},
                    {"name": "clip", "type": "CLIP", "link": 11}],
         "outputs": [{"name": "CONDITIONING", "type": "CONDITIONING", "links": [13]}],
         "widgets_values": ["a cinematic photo of a mountain at sunset"]},
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


def main():
    importer = _load().workflow_importer
    failures = []

    def check(name, cond):
        if cond:
            print(f"  PASS  {name}")
        else:
            failures.append(name)
            print(f"  FAIL  {name}")

    print("== ComfyUI workflow 导入器回归 ==")

    # 1. 格式识别
    check("detect ui 格式", importer.detect_format(SAMPLE_UI) == "ui")
    graph = {"1": {"class_type": "SaveImage", "inputs": {}}}
    check("detect graph 格式", importer.detect_format(graph) == "graph")
    check("detect unknown", importer.detect_format({"foo": 1}) == "unknown")

    # 2. UI → graph 透传
    r = importer.parse(SAMPLE_UI)
    check("parse 成功且可执行", r.is_executable)
    check("class_types 提取正确",
          "KSampler" in r.class_types and "SaveImage" in r.class_types)
    check("graph_prompt 节点数 = 6", len(r.graph_prompt) == 6)

    # 3. widget 映射：CLIPTextEncode 的 text 应是正样本字符串
    clip_node = r.graph_prompt.get("6")
    check("widget 映射：text 命中正样本",
          clip_node and clip_node["inputs"].get("text") == "a cinematic photo of a mountain at sunset")

    # 4. 连接型输入 → [源节点id, 槽]
    ks = r.graph_prompt.get("3")
    check("连接映射：model → [4, 0]",
          ks and ks["inputs"].get("model") == ["4", 0])

    # 5. 引用完整性：悬空引用应产生 warning（SAMPLE 里 link 14 指向不存在的节点 7）
    check("悬空引用产生 warning", len(r.warnings) >= 1)

    # 6. object_info 缺失节点检测
    object_info = {"KSampler": {}, "CheckpointLoaderSimple": {}}  # 故意缺 CLIPTextEncode 等
    r2 = importer.parse(SAMPLE_UI, object_info=object_info)
    check("缺失节点检测到 CLIPTextEncode",
          "CLIPTextEncode" in r2.missing_nodes)

    # 7. 损坏输入诚实失败
    r3 = importer.parse({"not": "workflow"})
    check("损坏输入返回 unknown + 不可执行",
          r3.raw_format == "unknown" and not r3.is_executable)

    print()
    if failures:
        print(f"RESULT: {len(failures)} 项失败 -> {failures}")
        return 1
    print("RESULT: ALL_PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
