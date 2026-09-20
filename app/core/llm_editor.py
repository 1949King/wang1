"""
自然语言编辑器 (LLMEditor)
============================

将自然语言编辑指令映射为 TimelineManager 操作。

流程:
  "把第3个片段加速2倍" → AIEngine.chat() → JSON解析 → EditCommand → TimelineManager

支持的指令类型:
  1. 片段操作: 添加/删除/移动/裁剪/复制/分割
  2. 轨道操作: 添加/删除/排序
  3. 转场: 添加淡入淡出/滑动/缩放
  4. 特效: 滤镜/调色/LUT
  5. 字幕/文字: 添加字幕/标题/水印
  6. 变速: 加速/减速/倒放
  7. 音频: 音量/静音/替换背景音乐
  8. 标记: 章节标记/关键帧

使用示例:
    from app.core.llm_editor import llm_editor
    from app.core.timeline_manager import timeline_manager

    editor = llm_editor.bind(timeline_manager)

    # 方式1: 快速编辑 (一句搞定)
    editor.quick_edit("在第5秒处添加一个淡入转场")

    # 方式2: 分步 (先解析再执行, 可预览/修改)
    commands = editor.parse("把前3个片段各缩短1秒")
    confirmed = editor.preview(commands)  # 返回可读描述
    editor.execute(confirmed)
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ============================================================================
# 数据结构
# ============================================================================

@dataclass
class EditCommand:
    """单条编辑指令

    Attributes:
        action: 操作类型 ("add_clip","remove_clip","add_transition",...)
        params: 操作参数 (timeline_id, track_id, time, duration, ...)
        confidence: LLM 置信度 (0.0-1.0)
        raw_text: 原始自然语言文本
        description: 人类可读的操作描述
    """
    action: str
    params: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    raw_text: str = ""
    description: str = ""


@dataclass
class ParseResult:
    """解析结果"""
    commands: List[EditCommand]
    success: bool = True
    error: str = ""
    model_used: str = ""


# ============================================================================
# 指令系统定义
# ============================================================================

_EDIT_COMMANDS_SPEC = {
    "add_clip": {
        "desc": "添加视频/音频片段到时间线",
        "params": ["timeline_id", "track_id", "file_path", "start_time", "duration", "in_point"],
        "example": {"action": "add_clip", "params": {"file_path": "C:/video.mp4", "start_time": 5.0}},
    },
    "remove_clip": {
        "desc": "删除时间线上的片段",
        "params": ["timeline_id", "track_id", "clip_id", "clip_index"],
        "example": {"action": "remove_clip", "params": {"clip_index": 2}},
    },
    "move_clip": {
        "desc": "移动片段到新的时间位置或轨道",
        "params": ["timeline_id", "track_id", "clip_id", "clip_index", "new_start_time", "new_track_id"],
        "example": {"action": "move_clip", "params": {"clip_index": 1, "new_start_time": 10.0}},
    },
    "trim_clip": {
        "desc": "裁剪片段 (修改入点/出点/时长)",
        "params": ["timeline_id", "track_id", "clip_id", "clip_index", "new_start", "new_end", "new_duration"],
        "example": {"action": "trim_clip", "params": {"clip_index": 0, "new_duration": 3.0}},
    },
    "split_clip": {
        "desc": "在指定时间点分割片段",
        "params": ["timeline_id", "track_id", "clip_id", "clip_index", "split_time"],
        "example": {"action": "split_clip", "params": {"clip_index": 0, "split_time": 5.0}},
    },
    "duplicate_clip": {
        "desc": "复制片段",
        "params": ["timeline_id", "track_id", "clip_id", "clip_index", "new_start_time"],
        "example": {"action": "duplicate_clip", "params": {"clip_index": 0}},
    },
    "add_track": {
        "desc": "添加新轨道 (video/audio/subtitle)",
        "params": ["timeline_id", "track_type", "name"],
        "example": {"action": "add_track", "params": {"track_type": "audio", "name": "BGM"}},
    },
    "remove_track": {
        "desc": "删除轨道",
        "params": ["timeline_id", "track_id", "track_index"],
        "example": {"action": "remove_track", "params": {"track_index": 1}},
    },
    "add_transition": {
        "desc": "添加转场效果",
        "params": ["timeline_id", "track_id", "clip_id", "clip_index", "position", "transition_type", "duration"],
        "example": {"action": "add_transition", "params": {"clip_index": 0, "position": "start", "transition_type": "fade", "duration": 0.5}},
    },
    "add_effect": {
        "desc": "添加视觉特效/滤镜",
        "params": ["timeline_id", "track_id", "clip_id", "clip_index", "effect_type", "params"],
        "example": {"action": "add_effect", "params": {"clip_index": 0, "effect_type": "blur", "params": {"radius": 5}}},
    },
    "remove_effect": {
        "desc": "移除视觉特效",
        "params": ["timeline_id", "track_id", "clip_id", "clip_index", "effect_type"],
        "example": {"action": "remove_effect", "params": {"clip_index": 0, "effect_type": "blur"}},
    },
    "add_subtitle": {
        "desc": "添加字幕",
        "params": ["timeline_id", "track_id", "text", "start_time", "end_time", "style"],
        "example": {"action": "add_subtitle", "params": {"text": "你好世界", "start_time": 1.0, "end_time": 3.0}},
    },
    "add_title": {
        "desc": "添加标题/文字",
        "params": ["timeline_id", "track_id", "text", "start_time", "duration", "position", "font_size", "color"],
        "example": {"action": "add_title", "params": {"text": "片头标题", "start_time": 0.0, "duration": 3.0}},
    },
    "change_speed": {
        "desc": "变速 (加速/减速/倒放)",
        "params": ["timeline_id", "track_id", "clip_id", "clip_index", "speed", "reverse"],
        "example": {"action": "change_speed", "params": {"clip_index": 0, "speed": 2.0}},
    },
    "adjust_volume": {
        "desc": "调整音量",
        "params": ["timeline_id", "track_id", "clip_id", "clip_index", "volume", "mute"],
        "example": {"action": "adjust_volume", "params": {"clip_index": 0, "volume": 0.5}},
    },
    "replace_audio": {
        "desc": "替换音频/背景音乐",
        "params": ["timeline_id", "track_id", "clip_id", "clip_index", "audio_file"],
        "example": {"action": "replace_audio", "params": {"clip_index": 0, "audio_file": "bgm.mp3"}},
    },
    "add_marker": {
        "desc": "添加时间线标记/章节",
        "params": ["timeline_id", "time", "name", "color"],
        "example": {"action": "add_marker", "params": {"time": 10.0, "name": "高潮", "color": "red"}},
    },
    "add_keyframe": {
        "desc": "添加关键帧动画",
        "params": ["timeline_id", "clip_id", "clip_index", "time", "property", "value"],
        "example": {"action": "add_keyframe", "params": {"clip_index": 0, "time": 1.0, "property": "scale", "value": 1.5}},
    },
    "ripple_delete": {
        "desc": "波纹删除 (删除片段后后续片段自动前移)",
        "params": ["timeline_id", "track_id", "clip_id", "clip_index"],
        "example": {"action": "ripple_delete", "params": {"clip_index": 1}},
    },
    "undo": {
        "desc": "撤销上一步操作",
        "params": ["count"],
        "example": {"action": "undo", "params": {"count": 1}},
    },
}

# ── LLM 系统提示词 ──

_SYSTEM_PROMPT = """你是一个专业的视频编辑助手。用户用自然语言描述编辑需求，你将其转换为结构化的编辑指令。

## 可用指令类型

{command_specs}

## 输出格式

严格返回 JSON 数组，每个元素是一条指令:

```json
[
  {{
    "action": "指令类型",
    "params": {{"key": "value"}},
    "confidence": 0.9,
    "description": "人类可读的描述"
  }}
]
```

## 注意事项

1. clip_index 从 0 开始计数（第1个片段=0，第2个=1）
2. 时间单位是秒
3. 速度倍率: 1.0=原速, 2.0=2倍速, 0.5=半速
4. 音量: 0.0=静音, 1.0=原始音量
5. position 可选: "start", "end", "both"
6. track_type 可选: "video", "audio", "subtitle"
7. transition_type 可选: "fade", "slide", "zoom", "dissolve", "wipe"
8. effect_type 可用: "blur", "sharpen", "brightness", "contrast", "saturation", "lut", "chroma_key"

如果用户请求不明确或无法执行，返回:
```json
[{{"action": "error", "params": {{"message": "说明"}}]}}
```

如果用户只是询问问题（非编辑操作），返回:
```json
[{{"action": "answer", "params": {{"message": "回答内容"}}, "confidence": 0.95}}]
```"""


# ============================================================================
# 规则解析器 (离线回退, 无需 LLM)
# ============================================================================

class RuleBasedParser:
    """基于正则的规则解析器 — 无需 LLM 即可处理常见编辑指令"""

    _RULES = [
        # 删除第N个片段
        (r"删除第?\s*(\d+)\s*个?片段", lambda m: EditCommand(
            action="remove_clip",
            params={"clip_index": int(m.group(1)) - 1},
            description=f"删除第{m.group(1)}个片段",
        )),
        # 删除所有片段
        (r"删除\s*所有\s*片段", lambda m: EditCommand(
            action="remove_clip",
            params={"clip_index": "all"},
            description="删除所有片段",
        )),
        # 加速/减速 N倍
        (r"(加速|减速|快放|慢放)\s*(\d+\.?\d*)\s*倍?", lambda m: EditCommand(
            action="change_speed",
            params={
                "speed": float(m.group(2)) if "加速" in m.group(1) or "快放" in m.group(1) else 1.0 / float(m.group(2)),
                "clip_index": 0,
            },
            description=f"{m.group(1)}{m.group(2)}倍",
        )),
        # 第N个片段加速M倍
        (r"第\s*(\d+)\s*个?片段?\s*(加速|减速)\s*(\d+\.?\d*)\s*倍?", lambda m: EditCommand(
            action="change_speed",
            params={
                "clip_index": int(m.group(1)) - 1,
                "speed": float(m.group(3)) if "加速" in m.group(2) else 1.0 / float(m.group(3)),
            },
            description=f"第{m.group(1)}个片段{m.group(2)}{m.group(3)}倍",
        )),
        # 添加转场 (淡入淡出)
        (r"(添加|加|插入)\s*(一个?)?\s*(淡入淡出|淡入|淡出|滑动|缩放)\s*转场", lambda m: EditCommand(
            action="add_transition",
            params={
                "transition_type": {"淡入淡出": "fade", "淡入": "fade_in", "淡出": "fade_out", "滑动": "slide", "缩放": "zoom"}.get(m.group(3), "fade"),
                "duration": 0.5,
            },
            description=f"添加{m.group(3)}转场",
        )),
        # 静音
        (r"(静音|关闭声音|去掉声音)", lambda m: EditCommand(
            action="adjust_volume",
            params={"mute": True, "clip_index": 0},
            description="静音",
        )),
        # 音量调整为 N%
        (r"音量\s*[调整设为]\s*(\d+)\s*%?", lambda m: EditCommand(
            action="adjust_volume",
            params={"volume": int(m.group(1)) / 100, "clip_index": 0},
            description=f"音量设为{m.group(1)}%",
        )),
        # 添加字幕
        (r"添加字幕\s*[:：]?\s*(.+)", lambda m: EditCommand(
            action="add_subtitle",
            params={"text": m.group(1).strip()},
            description=f"添加字幕: {m.group(1).strip()[:30]}",
        )),
        # 在第N秒添加标记
        (r"在\s*(\d+\.?\d*)\s*秒?\s*[添加标记]\s*[:：]?\s*(.+)?", lambda m: EditCommand(
            action="add_marker",
            params={
                "time": float(m.group(1)),
                "name": m.group(2).strip() if m.lastindex and m.lastindex >= 2 and m.group(2) else "标记",
            },
            description=f"在{m.group(1)}秒处添加标记",
        )),
        # 倒放
        (r"(倒放|反转|反向播放)", lambda m: EditCommand(
            action="change_speed",
            params={"reverse": True, "clip_index": 0},
            description="倒放",
        )),
        # 撤销
        (r"(撤销|回退|Undo)", lambda m: EditCommand(
            action="undo",
            params={"count": 1},
            description="撤销上一步",
        )),
    ]

    @classmethod
    def parse(cls, text: str) -> Optional[List[EditCommand]]:
        """尝试规则匹配，返回指令列表或 None"""
        text = text.strip()
        results: List[EditCommand] = []

        for pattern, factory in cls._RULES:
            match = re.search(pattern, text)
            if match:
                cmd = factory(match)
                cmd.raw_text = text
                cmd.confidence = 0.85  # 规则匹配置信度略低于 LLM
                results.append(cmd)
                break  # 只匹配第一条规则

        return results if results else None


# ============================================================================
# LLM 编辑器
# ============================================================================

class LLMEditor:
    """自然语言编辑器 — 单例"""

    _instance: Optional['LLMEditor'] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        self._timeline_manager = None
        self._ai_engine = None
        self._command_history: List[List[EditCommand]] = []
        self._undo_stack: List[Dict[str, Any]] = []
        self._on_executed_callbacks: List[Callable] = []

        # 构建 LLM prompt
        specs_desc = []
        for action, spec in _EDIT_COMMANDS_SPEC.items():
            specs_desc.append(
                f"- **{action}**: {spec['desc']}\n"
                f"  参数: {', '.join(spec['params'])}\n"
                f"  示例: {json.dumps(spec['example'], ensure_ascii=False)}"
            )
        self._system_prompt = _SYSTEM_PROMPT.format(
            command_specs="\n".join(specs_desc)
        )

        logger.info("[LLMEditor] 初始化完成")

    # ── 绑定依赖 ──

    def bind(self, timeline_manager) -> 'LLMEditor':
        """绑定 TimelineManager 实例"""
        self._timeline_manager = timeline_manager
        return self

    @property
    def timeline(self):
        """获取绑定的 TimelineManager"""
        if not self._timeline_manager:
            from app.core.timeline_manager import timeline_manager
            self._timeline_manager = timeline_manager
        return self._timeline_manager

    @property
    def ai(self):
        """获取 AI 引擎 (延迟加载)"""
        if not self._ai_engine:
            from app.core.ai_engine import ai_engine
            self._ai_engine = ai_engine
        return self._ai_engine

    # ── 核心: 解析自然语言 ──

    def parse(
        self,
        text: str,
        use_ai: bool = True,
        timeline_context: Optional[Dict[str, Any]] = None,
    ) -> ParseResult:
        """将自然语言文本解析为 EditCommand 列表。

        Args:
            text: 用户输入的自然语言指令
            use_ai: 是否使用 AI 解析 (False 时仅用规则匹配)
            timeline_context: 当前时间线上下文 (帮助 AI 理解)

        Returns:
            ParseResult 包含解析后的指令列表
        """
        text = text.strip()
        if not text:
            return ParseResult(commands=[], success=False, error="输入为空")

        # 1) 先尝试规则匹配（快速、离线、不消耗 token）
        rule_commands = RuleBasedParser.parse(text)
        if rule_commands:
            logger.info(f"[LLMEditor] 规则匹配成功: {text[:50]}")
            return ParseResult(commands=rule_commands, model_used="rule")

        # 2) 规则未匹配且允许 AI → 调用 LLM
        if not use_ai:
            return ParseResult(
                commands=[],
                success=False,
                error=f"无法解析指令: {text[:100]}",
            )

        return self._parse_with_ai(text, timeline_context)

    def _parse_with_ai(
        self, text: str, context: Optional[Dict] = None
    ) -> ParseResult:
        """使用 AI 引擎解析"""
        # 构建上下文消息
        user_content = f"用户指令: {text}"

        if context:
            user_content += f"\n\n当前时间线信息:\n{json.dumps(context, ensure_ascii=False, indent=2)}"

        messages = [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": user_content},
        ]

        try:
            raw = ""
            for chunk in self.ai.chat_with_fallback(
                messages=messages,
                providers=["deepseek", "doubao", "zhipu", "qwen"],
                use_cache=True,
                template=lambda: json.dumps([
                    {"action": "error", "params": {"message": "AI 服务不可用"}, "confidence": 0}
                ]),
            ):
                if not chunk.startswith("错误"):
                    raw += chunk

            commands = self._extract_json(raw)

            if not commands:
                return ParseResult(
                    commands=[],
                    success=False,
                    error=f"AI 返回格式异常: {raw[:200]}",
                )

            # 转换为 EditCommand
            result_commands = []
            for item in commands:
                if isinstance(item, dict):
                    action = item.get("action", "unknown")
                    if action == "error":
                        return ParseResult(
                            commands=[],
                            success=False,
                            error=item.get("params", {}).get("message", "未知错误"),
                        )
                    if action == "answer":
                        # 问答回复 → 转为描述性指令
                        result_commands.append(EditCommand(
                            action="info",
                            params={"message": item.get("params", {}).get("message", "")},
                            confidence=item.get("confidence", 0.9),
                            raw_text=text,
                            description=item.get("params", {}).get("message", ""),
                        ))
                        continue

                    cmd = EditCommand(
                        action=action,
                        params=item.get("params", {}),
                        confidence=item.get("confidence", 0.9),
                        raw_text=text,
                        description=item.get("description", f"{action}"),
                    )
                    result_commands.append(cmd)

            if not result_commands:
                return ParseResult(
                    commands=[],
                    success=False,
                    error="未能解析出有效编辑指令",
                )

            return ParseResult(commands=result_commands, model_used="ai")

        except Exception as e:
            logger.error(f"[LLMEditor] AI 解析失败: {e}")
            return ParseResult(
                commands=[],
                success=False,
                error=f"AI 解析异常: {str(e)[:200]}",
            )

    @staticmethod
    def _extract_json(raw: str) -> Optional[List[Dict]]:
        """从 LLM 响应中提取 JSON 数组"""
        # 尝试直接解析
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                return [data]
        except json.JSONDecodeError:
            pass

        # 尝试提取 ```json ... ``` 块
        json_block = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', raw, re.DOTALL)
        if json_block:
            try:
                data = json.loads(json_block.group(1))
                if isinstance(data, list):
                    return data
                if isinstance(data, dict):
                    return [data]
            except json.JSONDecodeError:
                pass

        # 尝试提取最外层 [...] 数组
        array_match = re.search(r'\[.*\]', raw, re.DOTALL)
        if array_match:
            try:
                data = json.loads(array_match.group(0))
                if isinstance(data, list):
                    return data
            except json.JSONDecodeError:
                pass

        return None

    # ── 预览 ──

    def preview(self, commands: List[EditCommand]) -> str:
        """预览指令效果，返回人类可读描述"""
        lines = ["═══ 即将执行的编辑操作 ═══"]
        for i, cmd in enumerate(commands):
            status = "✓" if cmd.confidence > 0.7 else "⚠"
            desc = cmd.description or f"{cmd.action}"
            lines.append(f"  {i + 1}. {status} {desc}")
            if cmd.confidence < 0.7:
                lines.append(f"     (置信度: {cmd.confidence:.0%})")
        return "\n".join(lines)

    # ── 执行 ──

    def execute(
        self,
        commands: List[EditCommand],
        timeline_id: Optional[str] = None,
        dry_run: bool = False,
    ) -> List[Dict[str, Any]]:
        """执行编辑指令列表。

        Args:
            commands: 待执行的指令列表
            timeline_id: 目标时间线 ID (默认使用当前活动时间线)
            dry_run: True 时仅验证不执行

        Returns:
            每条指令的执行结果 [{action, success, message, ...}]
        """
        results: List[Dict[str, Any]] = []

        # 获取当前时间线
        if not timeline_id:
            current = self.timeline.get_current_timeline()
            if not current:
                for cmd in commands:
                    results.append({
                        "action": cmd.action,
                        "success": False,
                        "message": "没有活动的编辑时间线，请先创建或打开一个项目",
                    })
                return results
            timeline_id = current.get("id", "")

        if dry_run:
            for cmd in commands:
                results.append({
                    "action": cmd.action,
                    "success": True,
                    "message": f"[DRY RUN] {cmd.description or cmd.action}",
                    "params": cmd.params,
                })
            return results

        # 记录历史（用于撤销）
        self._command_history.append(commands)

        for cmd in commands:
            try:
                result = self._execute_one(cmd, timeline_id)
                results.append(result)
                # 回调
                for cb in self._on_executed_callbacks:
                    try:
                        cb(cmd, result)
                    except Exception as e:
                        logger.debug(f"[LLMEditor] 执行回调失败: {e}")
            except Exception as e:
                logger.error(f"[LLMEditor] 执行 {cmd.action} 失败: {e}")
                results.append({
                    "action": cmd.action,
                    "success": False,
                    "message": str(e)[:200],
                })

        logger.info(
            f"[LLMEditor] 执行完成: {len(results)} 条指令, "
            f"成功 {sum(1 for r in results if r['success'])}/{len(results)}"
        )
        return results

    def _execute_one(self, cmd: EditCommand, timeline_id: str) -> Dict[str, Any]:
        """执行单条指令"""
        p = cmd.params
        tm = self.timeline

        # ── 获取 clip_id (通过 clip_index) ──
        def _resolve_clip(idx):
            if idx is None:
                return None, None
            if idx == "all":
                return "all", "all"
            tracks = tm.get_timeline(timeline_id)
            if not tracks:
                return None, None
            all_clips = []
            for track_id, track_data in tracks.get("tracks", {}).items():
                for clip in track_data.get("clips", []):
                    all_clips.append((track_id, clip.get("id")))
            if 0 <= idx < len(all_clips):
                return all_clips[idx]
            return None, None

        clip_index = p.get("clip_index", 0)
        track_id = p.get("track_id", "track_1")
        clip_id = p.get("clip_id")

        # ── 路由到具体操作 ──

        if cmd.action == "add_clip":
            tm.add_clip(timeline_id, track_id, {
                "file_path": p["file_path"],
                "start_time": p.get("start_time", 0),
                "duration": p.get("duration", 0),
                "in_point": p.get("in_point", 0),
            })
            return {"action": cmd.action, "success": True, "message": "片段已添加"}

        elif cmd.action == "remove_clip":
            if clip_index == "all":
                # 删除所有片段
                tracks = tm.get_timeline(timeline_id)
                count = 0
                for tid, tdata in (tracks.get("tracks", {}) if tracks else {}).items():
                    for clip in tdata.get("clips", []):
                        tm.delete_clip(timeline_id, tid, clip["id"])
                        count += 1
                return {"action": cmd.action, "success": True, "message": f"已删除 {count} 个片段"}
            else:
                tid, cid = _resolve_clip(clip_index)
                if not cid:
                    return {"action": cmd.action, "success": False, "message": f"未找到第{clip_index + 1}个片段"}
                tm.delete_clip(timeline_id, tid, cid)
                return {"action": cmd.action, "success": True, "message": "片段已删除"}

        elif cmd.action == "move_clip":
            tid, cid = _resolve_clip(clip_index)
            if not cid:
                return {"action": cmd.action, "success": False, "message": f"未找到第{clip_index + 1}个片段"}
            new_time = p.get("new_start_time", 0)
            new_track = p.get("new_track_id")
            tm.move_clip(timeline_id, tid, cid, new_time, new_track)
            return {"action": cmd.action, "success": True, "message": f"片段已移至 {new_time}s"}

        elif cmd.action == "trim_clip":
            tid, cid = _resolve_clip(clip_index)
            if not cid:
                return {"action": cmd.action, "success": False, "message": f"未找到第{clip_index + 1}个片段"}
            new_duration = p.get("new_duration")
            if new_duration:
                tm.resize_clip(timeline_id, tid, cid, new_duration)
            return {"action": cmd.action, "success": True, "message": f"片段已裁剪"}

        elif cmd.action == "split_clip":
            tid, cid = _resolve_clip(clip_index)
            if not cid:
                return {"action": cmd.action, "success": False, "message": f"未找到第{clip_index + 1}个片段"}
            split_time = p.get("split_time", 0)
            # 分割 = 调整原片段时长 + 添加新片段
            clip = tm.get_clip(timeline_id, cid)
            if clip:
                original_duration = clip.get("duration", 0)
                original_start = clip.get("start_time", 0)
                tm.resize_clip(timeline_id, tid, cid, split_time - original_start)
                tm.add_clip(timeline_id, tid, {
                    "file_path": clip.get("file_path", ""),
                    "start_time": original_start + split_time,
                    "duration": original_duration - split_time,
                    "in_point": split_time,
                })
            return {"action": cmd.action, "success": True, "message": f"已在 {split_time}s 处分割"}

        elif cmd.action == "duplicate_clip":
            tid, cid = _resolve_clip(clip_index)
            if not cid:
                return {"action": cmd.action, "success": False, "message": f"未找到第{clip_index + 1}个片段"}
            clip = tm.get_clip(timeline_id, cid)
            if clip:
                new_start = p.get("new_start_time", clip.get("start_time", 0) + clip.get("duration", 1))
                tm.add_clip(timeline_id, tid, {
                    "file_path": clip.get("file_path", ""),
                    "start_time": new_start,
                    "duration": clip.get("duration", 1),
                    "in_point": clip.get("in_point", 0),
                })
            return {"action": cmd.action, "success": True, "message": "片段已复制"}

        elif cmd.action == "add_track":
            tm.add_track(timeline_id, p.get("track_type", "video"), p.get("name", ""))
            return {"action": cmd.action, "success": True, "message": f"{p.get('track_type', 'video')} 轨道已添加"}

        elif cmd.action == "add_transition":
            # 对接 transition_plugin_registry 真实写入片段转场元数据
            transition_type = p.get("transition_type", "fade")
            duration = p.get("duration", 0.5)
            curve = p.get("curve", "线性")
            position = p.get("position", "end")
            tid, cid = _resolve_clip(clip_index)
            if not cid or cid == "all":
                return {"action": cmd.action, "success": False, "message": "无法解析目标片段，请指定片段序号"}
            clip = tm.get_clip(timeline_id, cid)
            if not clip:
                return {"action": cmd.action, "success": False, "message": "未找到目标片段"}
            # 解析 plugin_id（对齐预览双帧混合与导出 xfade 语义）
            plugin_id = None
            try:
                from app.core.transition_plugin_registry import resolve_plugin_id
                plugin_id = resolve_plugin_id(transition_type)
            except Exception:
                plugin_id = None
            transition = {
                "type": transition_type,
                "plugin_id": plugin_id or transition_type,
                "duration": max(0.1, float(duration)),
                "position": position or "end",
                "curve": curve or "线性",
            }
            transitions = list(clip.get("transitions") or [])
            if not isinstance(transitions, list):
                transitions = []
            transitions.append(transition)
            tm.update_clip(timeline_id, cid, transition=transition, transitions=transitions)
            return {"action": cmd.action, "success": True, "message": f"转场 {transition_type} ({duration}s) 已添加"}

        elif cmd.action == "add_effect":
            # 对接 EffectManager 真实应用特效
            from app.core.effect_manager import EffectManager
            effect_type = p.get("effect_type", "")
            effect_params = p.get("params", {})
            if not effect_type:
                return {"action": cmd.action, "success": False, "message": "未指定特效类型"}
            tid, cid = _resolve_clip(clip_index)
            if cid and cid != "all":
                emgr = EffectManager()
                try:
                    instance = emgr.create_effect_instance(effect_type, effect_params)
                except (ValueError, KeyError):
                    instance = {
                        "id": f"effect_{abs(hash(effect_type))}",
                        "effect_id": effect_type,
                        "name": effect_type,
                        "parameters": effect_params,
                    }
                emgr.apply_effect(cid, instance)
                return {"action": cmd.action, "success": True, "message": f"特效 {effect_type} 已应用到片段"}
            else:
                return {"action": cmd.action, "success": False, "message": "无法解析目标片段"}

        elif cmd.action == "add_subtitle" or cmd.action == "add_title":
            # 对接 SubtitleManager 真实添加字幕/标题
            from app.core.subtitle_manager import SubtitleManager
            text = p.get("text", "")
            if not text:
                return {"action": cmd.action, "success": False, "message": "未提供字幕/标题文本"}
            start_time = p.get("start_time", 0)
            end_time = p.get("end_time", start_time + p.get("duration", 3.0))
            style = p.get("style", "default")
            smgr = SubtitleManager()
            if cmd.action == "add_title":
                # 标题附加位置/样式参数
                position = p.get("position", "center")
                font_size = p.get("font_size", 36)
                color = p.get("color", "#FFFFFF")
                style = {"position": position, "font_size": font_size, "color": color}
            result = smgr.add_subtitle(text, start_time, end_time, style)
            return {"action": cmd.action, "success": True, "message": f"字幕已添加: {text[:30]}"}

        elif cmd.action == "change_speed":
            # 通过 TimelineManager.update_clip 真实修改片段速度
            tid, cid = _resolve_clip(clip_index)
            speed = p.get("speed", 1.0)
            reverse = p.get("reverse", False)
            if cid and cid != "all":
                tm.update_clip(timeline_id, cid, speed=speed, reverse=reverse)
                desc = f"{'倒放+变速' if reverse else '变速'} {speed}x"
                return {"action": cmd.action, "success": True, "message": desc}
            else:
                return {"action": cmd.action, "success": False, "message": "无法解析目标片段"}

        elif cmd.action == "adjust_volume":
            # 通过 TimelineManager.update_clip 真实修改片段音量
            tid, cid = _resolve_clip(clip_index)
            volume = p.get("volume", 1.0)
            mute = p.get("mute", False)
            if cid and cid != "all":
                tm.update_clip(timeline_id, cid, volume=volume, mute=mute)
                desc = "静音" if mute else f"音量 {volume}"
                return {"action": cmd.action, "success": True, "message": desc}
            else:
                return {"action": cmd.action, "success": False, "message": "无法解析目标片段"}

        elif cmd.action == "add_marker":
            time_sec = p.get("time", 0)
            name = p.get("name", "标记")
            tm.add_marker(timeline_id, time_sec, name, p.get("color", "blue"))
            return {"action": cmd.action, "success": True, "message": f"标记已添加: {name} @ {time_sec}s"}

        elif cmd.action == "add_keyframe":
            tid, cid = _resolve_clip(clip_index)
            time_sec = p.get("time", 0)
            prop = p.get("property", "")
            value = p.get("value", 0)
            # 修复：此前 cid 解析失败（未找到第 clip_index 个片段）时，
            # if cid 分支被跳过、tm.add_keyframe 根本没被调用，但下面的
            # return 语句在 if 块之外、无条件 success=True——用户会看到
            # "关键帧已添加"，但时间线上什么都没发生。
            if not cid:
                return {"action": cmd.action, "success": False,
                        "message": f"未找到第{clip_index + 1 if isinstance(clip_index, int) else clip_index}个片段，关键帧未添加"}
            tm.add_keyframe(timeline_id, cid, time_sec, prop, value)
            return {"action": cmd.action, "success": True, "message": f"关键帧已添加: {prop}"}

        elif cmd.action == "ripple_delete":
            tid, cid = _resolve_clip(clip_index)
            if not cid:
                return {"action": cmd.action, "success": False, "message": f"未找到片段"}
            tm.ripple_delete_clip(timeline_id, tid, cid)
            return {"action": cmd.action, "success": True, "message": "波纹删除完成"}

        elif cmd.action == "undo":
            # 如实说明：TimelineManager 未提供任何真正的反向操作/快照回滚接口
            # （见 app/core/timeline_manager.py，无 undo/redo 方法），这里只能
            # 把最近一批指令从本地历史里弹出——时间线上已经生效的修改
            # （加片段/删片段/变速等）不会被撤销。此前消息写"已撤销"容易让人
            # 误以为时间线已经真的回退了。
            if self._command_history:
                self._command_history.pop()
                return {"action": cmd.action, "success": True,
                        "message": "已从操作历史中移除最近一条记录（时间线上的实际改动未回滚，"
                                    "TimelineManager 暂不支持真正撤销）"}
            return {"action": cmd.action, "success": False, "message": "没有可撤销的操作"}

        elif cmd.action == "info" or cmd.action == "answer":
            return {"action": cmd.action, "success": True, "message": p.get("message", "")}

        else:
            return {
                "action": cmd.action,
                "success": False,
                "message": f"不支持的指令类型: {cmd.action}",
            }

    # ── 快速编辑 ──

    def quick_edit(
        self,
        text: str,
        use_ai: bool = True,
        preview: bool = True,
        timeline_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """一站式: 解析 → 预览 → 执行

        Args:
            text: 自然语言编辑指令
            use_ai: 是否使用 AI
            preview: 是否打印预览
            timeline_id: 目标时间线

        Returns:
            执行结果列表
        """
        result = self.parse(text, use_ai=use_ai)
        if not result.success or not result.commands:
            return [{"action": "parse_error", "success": False, "message": result.error}]

        if preview:
            logger.info(f"\n{self.preview(result.commands)}")

        return self.execute(result.commands, timeline_id=timeline_id)

    # ── 事件回调 ──

    def on_executed(self, callback: Callable):
        """注册指令执行回调 callback(command: EditCommand, result: dict)"""
        self._on_executed_callbacks.append(callback)

    def get_undo_count(self) -> int:
        """可撤销操作数"""
        return len(self._command_history)

    def get_available_commands(self) -> List[str]:
        """返回所有支持的指令类型"""
        return list(_EDIT_COMMANDS_SPEC.keys())


# ============================================================================
# 全局单例
# ============================================================================

llm_editor = LLMEditor()
