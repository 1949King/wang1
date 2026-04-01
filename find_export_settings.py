with open('app/modules/lego/ai_clip_flow.py', 'r', encoding='utf-8') as f:
    content = f.read()
    lines = content.split('\n')
    
    # 查找创建方法
    for i, line in enumerate(lines):
        if 'def _create_' in line:
            print(f'Line {i+1}: {line}')
    
    # 查找导出相关设置
    print('\n导出相关设置:')
    for i, line in enumerate(lines):
        if 'export' in line.lower():
            print(f'Line {i+1}: {line}')