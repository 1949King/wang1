import os, sys
# 项目根 = 上一级目录的上一级 (temp -> app -> 项目根)
_project_root = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, _project_root)

# suppress logs
import logging
logging.disable(logging.CRITICAL)

# 1. prompt_templates
from app.core.ai.prompt_templates import PROMPT_TEMPLATES, build_prompt
print(f"1. 模板数: {len(PROMPT_TEMPLATES)}")
for k in PROMPT_TEMPLATES:
    print(f"   [{k}]")

r = build_prompt("extract_highlights",
                 srt_text="[1] 00:00:01.000 -> 00:00:03.000: test",
                 user_hint="反转")
assert "你是一个" in r["system"], "system missing"
assert "test" in r["user"], "srt missing"
assert "反转" in r["user"], "hint missing"
print("2. build_prompt OK")

# 2. llm_clipper core
from app.core.ai.llm_clipper import _parse_time_srt, _extract_json, _get_ffmpeg_exe
assert _parse_time_srt("00:01:30,500") == 90.5
assert _parse_time_srt("00:00:05.250") == 5.25
print("3. 时间解析 OK")

r = _extract_json('[{"start":"00:00:10,000","end":"00:00:20,000"}]')
assert r and len(r) == 1
r2 = _extract_json("```json\n[{\"start\":\"00:00:05,000\",\"end\":\"00:00:15,000\"}]\n```")
assert r2 and len(r2) == 1
r3 = _extract_json("")
assert r3 is None
print("4. JSON提取 OK")

ff = _get_ffmpeg_exe()
assert ff, "ffmpeg not found"
print(f"5. ffmpeg: {ff}")

print("\nALL OK")
