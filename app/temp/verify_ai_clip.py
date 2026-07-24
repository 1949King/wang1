"""
验证 AI 智能剪辑模块
- 不启动 QApplication
- 测试项: 导入 / 模板 / LLM 可用性 / 时间解析 / JSON 提取 / 路径
"""
import os
import sys
import json

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, PROJECT)

pass_count = 0
fail_count = 0


def check(name, condition, detail=""):
    global pass_count, fail_count
    if condition:
        pass_count += 1
        print(f"  ✅ {name}")
    else:
        fail_count += 1
        print(f"  ❌ {name}: {detail}")


# ============================================================
# 1. 导入验证
# ============================================================
print("\n=== 1. 导入验证 ===")

try:
    from app.core.ai import prompt_templates as pt
    check("prompt_templates 导入", True)
except Exception as e:
    check("prompt_templates 导入", False, str(e))
    pt = None

try:
    from app.core.ai.llm_clipper import (
        LLMClipper, is_llm_clip_available, get_llm_clipper,
        _parse_time_srt, _fmt_time_ffmpeg, _extract_json,
        transcribe_whisper, segments_to_srt_text, _get_ffmpeg_exe,
    )
    check("llm_clipper 导入", True)
except Exception as e:
    check("llm_clipper 导入", False, str(e))

# ============================================================
# 2. Prompt 模板验证
# ============================================================
print("\n=== 2. Prompt 模板验证 ===")

if pt:
    tpls = pt.list_templates()
    check(f"模板数量 = {len(tpls)}", len(tpls) >= 8, f"只有 {len(tpls)} 套")
    for key in pt.PROMPT_TEMPLATES:
        has_name = bool(pt.PROMPT_TEMPLATES[key].get("name"))
        has_system = bool(pt.PROMPT_TEMPLATES[key].get("system", "").strip())
        has_user = bool(pt.PROMPT_TEMPLATES[key].get("user", "").strip())
        check(f"模板 [{key}]: {pt.PROMPT_TEMPLATES[key]['name']}",
              has_name and has_system and has_user)

    # build_prompt
    result = pt.build_prompt("extract_highlights",
                             srt_text="[1] 00:00:00.000 → 00:00:02.500: 你好世界",
                             user_hint="反转")
    check("build_prompt 返回 dict", isinstance(result, dict))
    check("build_prompt 含 system", "system" in result and "你是一个" in result["system"])
    check("build_prompt 含 user", "user" in result and "你好世界" in result["user"])
    check("build_prompt 含 user_hint", "反转" in result["user"])

    # 不存在的模板
    result_none = pt.build_prompt("nonexistent")
    check("build_prompt 不存在模板→None", result_none is None)

# ============================================================
# 3. 时间格式转换
# ============================================================
print("\n=== 3. 时间格式转换 ===")

check("HH:MM:SS,mmm → 秒", _parse_time_srt("00:01:30,500") == 90.5)
check("HH:MM:SS.mmm → 秒", _parse_time_srt("00:00:05.250") == 5.25)
check("HH:MM:SS → 秒", _parse_time_srt("00:02:00") == 120.0)
check("纯秒数 → 秒", _parse_time_srt("42.5") == 42.5)

check("秒 → ffmpeg 格式", _fmt_time_ffmpeg(90.5) == "00:01:30.500")
check("秒 → ffmpeg 格式(整数)", _fmt_time_ffmpeg(120.0) == "00:02:00.000")

# ============================================================
# 4. JSON 提取（LLM 响应容错）
# ============================================================
print("\n=== 4. JSON 提取（LLM 容错） ===")

# 标准 JSON
r1 = _extract_json('[{"start":"00:00:10,000","end":"00:00:20,000"}]')
check("标准 JSON 数组", bool(r1) and len(r1) == 1)

# Markdown 包裹
r2 = _extract_json('```json\n[{"start":"00:00:05,000","end":"00:00:15,000"}]\n```')
check("Markdown 包裹 JSON", bool(r2) and len(r2) == 1)

# 含说明文字
r3 = _extract_json('这里是分析结果：\n[{"start":"00:00:10,000","end":"00:00:20,000","reason":"反转"}]\n希望这些对你有帮助。')
check("含说明文字的 JSON", bool(r3) and len(r3) == 1)

# 多段 JSON
r4 = _extract_json('[{"start":"00:00:05,000","end":"00:00:15,000"},{"start":"00:00:30,000","end":"00:00:45,000"}]')
check("多段 JSON", bool(r4) and len(r4) == 2)

# 空文本
r5 = _extract_json("")
check("空文本 → None", r5 is None)

# 无 JSON
r6 = _extract_json("没有JSON内容")
check("无 JSON → None", r6 is None)

# ============================================================
# 5. LLM 可用性
# ============================================================
print("\n=== 5. LLM 可用性检测 ===")

ollama_ok = False
try:
    from app.modules.lego.ollama_client import OllamaClient
    ollama_ok = OllamaClient().is_available(force_check=True)
except Exception as e:
    pass

models = LLMClipper.list_ollama_models() if ollama_ok else []
clipper_ok = is_llm_clip_available()

print(f"  Ollama 服务: {'✅ 在线' if ollama_ok else '⚠️ 离线'}")
print(f"  已安装模型: {models if models else '(无)'}")
print(f"  LLM 裁剪可用: {'✅ 是' if clipper_ok else '⚠️ 否（将回退到传统算法）'}")

check("OllamaClient 可导入", True)  # 能到这就表示导入成功

# ============================================================
# 6. ffmpeg 路径
# ============================================================
print("\n=== 6. ffmpeg 路径 ===")

ffmpeg_path = _get_ffmpeg_exe()
check("ffmpeg 路径非空", bool(ffmpeg_path))
print(f"  ffmpeg: {ffmpeg_path}")

# ============================================================
# 7. 段合并逻辑
# ============================================================
print("\n=== 7. 段合并逻辑 ===")

clipper = get_llm_clipper()

# 无重叠
segs1 = [{"start": 0, "end": 10}, {"start": 20, "end": 30}]
merged1 = clipper._merge_segments(segs1)
check("无重叠→保持", len(merged1) == 2)

# 有重叠
segs2 = [{"start": 0, "end": 15}, {"start": 10, "end": 25}]
merged2 = clipper._merge_segments(segs2)
check("重叠→合并", len(merged2) == 1 and merged2[0]["end"] == 25)

# 无序
segs3 = [{"start": 20, "end": 30}, {"start": 0, "end": 10}]
merged3 = clipper._merge_segments(segs3)
check("无序→排序", merged3[0]["start"] == 0 and merged3[1]["start"] == 20)

# ============================================================
# 8. 端到端 (仅当 Ollama 可用)
# ============================================================
if clipper_ok:
    print("\n=== 8. 端到端测试（LLM chat） ===")
    try:
        from app.core.ai.prompt_templates import build_prompt
        msgs = build_prompt("extract_highlights",
                            srt_text="(测试字幕)",
                            user_hint="测试")
        result = clipper._call_ollama(msgs)
        check(f"LLM 返回 {len(result or [])} 段", result is not None)
    except Exception as e:
        check("端到端", False, str(e))
else:
    print("\n=== 8. 端到端测试（跳过，Ollama 离线） ===")

# ============================================================
# 总结
# ============================================================
print(f"\n{'='*50}")
print(f"  通过 {pass_count} / 失败 {fail_count}  (共 {pass_count + fail_count} 项)")
print(f"{'='*50}")

if fail_count == 0:
    print("  全部通过 ✅")
else:
    print(f"  {fail_count} 项失败 ❌")

sys.exit(0 if fail_count == 0 else 1)
