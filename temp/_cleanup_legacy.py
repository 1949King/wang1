"""临时脚本：移除 ai_video_editor_local.py 中的遗留类和冗余代码"""
import re

path = "app/ai_video_editor_local.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()
    lines = content.split("\n")

# 查找关键行
legacy_start = None
whisper_start = None

for i, line in enumerate(lines):
    if "class _LegacyAIVideoEditor:" in line and legacy_start is None:
        legacy_start = i
    if "# --- Whisper" in line and whisper_start is None:
        whisper_start = i

# 检查是否有真正的第二个 __main__ 块
second_main = None
main_count = 0
for i, line in enumerate(lines):
    if 'if __name__ == "__main__":' in line:
        main_count += 1
        if main_count == 2:
            second_main = i

print(f"Legacy class starts: line {legacy_start + 1 if legacy_start else 'NOT FOUND'}")
print(f"Whisper section: line {whisper_start + 1 if whisper_start else 'NOT FOUND'}")
print(f"Second __main__ block: line {second_main + 1 if second_main else 'NOT FOUND'}")
print(f"Total __main__ blocks: {main_count}")
print(f"Legacy code lines to remove: {whisper_start - legacy_start}")
