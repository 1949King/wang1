with open('app/modules/lego/ai_clip_flow.py', 'r', encoding='utf-8') as f:
    content = f.read()
    lines = content.split('\n')
    
    for i, line in enumerate(lines):
        if 'def _start_clip_flow' in line:
            print(f'Line {i+1}: {line}')
            print('\n'.join(lines[i:i+50]))
            break