import re

filepath = r'D:\本地磁盘(当前分区)(C)\Users\Administrator\Desktop\AI短剧编辑器2\app\modules\lego\settings_module.py'
newpath = r'D:\本地磁盘(当前分区)(C)\Users\Administrator\Desktop\AI短剧编辑器2\temp\new_help.txt'

with open(filepath, 'r', encoding='utf-8') as f:
    lines = f.readlines()

with open(newpath, 'r', encoding='utf-8') as f:
    new_lines = f.readlines()

help_start = None
help_end = None
for i, line in enumerate(lines):
    if line.strip().startswith('class HelpModule'):
        help_start = i
    elif help_start is not None and i > help_start + 5 and line.startswith('class ') and not line.startswith('class HelpModule'):
        help_end = i
        break

if help_end is None:
    help_end = len(lines)

new_content = lines[:help_start] + new_lines[:-1] + ['\n']
if help_end < len(lines):
    new_content += lines[help_end:]

with open(filepath, 'w', encoding='utf-8') as f:
    f.writelines(new_content)

print(f'Replaced lines {help_start+1}-{help_end+1} with {len(new_lines)} new lines')
