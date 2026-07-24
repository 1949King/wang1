"""Replace EditorModule class in modules.py with import from editor_module.py"""
import os

base = r'c:\Users\Administrator\Desktop\拾光剪影\app\modules\lego'
filepath = os.path.join(base, 'modules.py')

with open(filepath, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Keep lines 1-3117 (everything before EditorModule)
# Replace lines 3118-9248 with import
# Keep lines 9249+ (everything after EditorModule)
new_lines = lines[:3117]  # 0-indexed: lines 0 to 3116 = original lines 1 to 3117

# Add import
new_lines.append('\n')
new_lines.append('# EditorModule 已拆分为独立文件 editor_module.py\n')
new_lines.append('from .editor_module import EditorModule\n')
new_lines.append('\n')

# Add remaining lines (original lines 9249+)
new_lines.extend(lines[9248:])

with open(filepath, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print(f"Original lines: {len(lines)}")
print(f"New lines: {len(new_lines)}")
print(f"Removed: {len(lines) - len(new_lines)} lines (EditorModule: 6131 lines)")
print("Done!")
