import os
import sys

def count_lines(directory):
    total_lines = 0
    file_count = 0
    
    for root, dirs, files in os.walk(directory):
        # 跳过一些不需要统计的目录
        dirs[:] = [d for d in dirs if d not in ['.venv', 'venv', 'build', 'dist', '__pycache__', '.git']]
        
        for file in files:
            if file.endswith('.py'):
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        lines = len(f.readlines())
                        total_lines += lines
                        file_count += 1
                except:
                    pass
    
    return total_lines, file_count

if __name__ == "__main__":
    if len(sys.argv) > 1:
        directory = sys.argv[1]
        total_lines, file_count = count_lines(directory)
        print(f"{directory} 目录代码总量: {total_lines} 行")
        print(f"Python文件数量: {file_count} 个")
    else:
        total_lines, file_count = count_lines('.')
        print(f"项目代码总量: {total_lines} 行")
        print(f"Python文件数量: {file_count} 个")
