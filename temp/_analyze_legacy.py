"""清理 ai_video_editor_local.py 中的重复定义"""
import re

path = "app/ai_video_editor_local.py"
with open(path, "r", encoding="utf-8") as f:
    lines = f.readlines()

# 1. 查找两个 class AIVideoEditorLocal 定义行（0-indexed）
class_lines = []
for i, line in enumerate(lines):
    if line.strip().startswith("class AIVideoEditorLocal:"):
        class_lines.append(i)

print(f"Found {len(class_lines)} class AIVideoEditorLocal definitions:")
for i, line_no in enumerate(class_lines):
    print(f"  #{i+1}: line {line_no + 1}")

if len(class_lines) != 2:
    print("ERROR: Expected exactly 2 class definitions")
    exit(1)

# 2. 找到第一个 if __name__ == "__main__": 块（在旧类之后）
main_blocks = []
for i, line in enumerate(lines):
    if line.strip() == 'if __name__ == "__main__":':
        main_blocks.append(i)

print(f"Found {len(main_blocks)} __main__ blocks:")
for i, line_no in enumerate(main_blocks):
    print(f"  #{i+1}: line {line_no + 1}")

# 3. 确认：第一个 __main__ 块在两个 class 之间
if main_blocks[0] < class_lines[1]:
    print(f"First __main__ (line {main_blocks[0]+1}) is before second class (line {class_lines[1]+1}) - will remove")
else:
    print("ERROR: First __main__ is not in the expected position")
    exit(1)

# 4. 找到 stray imports 的结束位置（"# --- Whisper" 注释之前）
stray_end = None
for i in range(main_blocks[0], len(lines)):
    if "# --- Whisper" in lines[i]:
        stray_end = i
        break

if stray_end is None:
    print("ERROR: Could not find Whisper section")
    exit(1)

print(f"Stray imports end before line {stray_end + 1}")

# 5. 构建新文件：保留前后部分，移除中间
# 第一部分：从开头到第一个class定义之前
# 第二部分：从 stray_end 到文件末尾

# 检查第一个class上一行的缩进，确定它属于哪个作用域
prev_line = lines[class_lines[0] - 1].strip() if class_lines[0] > 0 else ""
print(f"Line before first class: '{prev_line}'")

# 实际上，我们只想重命名第一个类，并移除第一个__main__和stray imports
# 这样是最安全的 
print("\n=== Plan ===")
print(f"1. Rename first class at line {class_lines[0]+1}: AIVideoEditorLocal -> _LegacyAIVideoEditor")
print(f"2. Remove first __main__ block (line {main_blocks[0]+1}) through stray imports (before line {stray_end+1})")
print("\nLines to analyze...")
print(f"  Last line before first __main__: {lines[main_blocks[0]-1].strip()[:80]}")
print(f"  First line after stray imports: {lines[stray_end].strip()[:80]}")
