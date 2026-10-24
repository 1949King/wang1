import os

# 测试路径计算
def test_ffmpeg_path():
    # 模拟 professional_video_engine.py 中的路径计算
    current_file = os.path.abspath(__file__)
    print(f"当前文件: {current_file}")
    
    # 模拟 FFmpegUtils.find_ffmpeg() 中的路径计算
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    print(f"base_dir: {base_dir}")
    
    project_ffmpeg_path = os.path.join(base_dir, 'thirdparty', 'ffmpeg', 'bin', 'ffmpeg.exe')
    print(f"计算的FFmpeg路径: {project_ffmpeg_path}")
    
    # 检查路径是否存在
    if os.path.exists(project_ffmpeg_path):
        print("✓ FFmpeg路径存在!")
    else:
        print("✗ FFmpeg路径不存在!")
    
    # 检查 thirdparty 目录结构
    thirdparty_path = os.path.join(base_dir, 'thirdparty')
    if os.path.exists(thirdparty_path):
        print(f"✓ thirdparty目录存在: {thirdparty_path}")
        ffmpeg_path = os.path.join(thirdparty_path, 'ffmpeg')
        if os.path.exists(ffmpeg_path):
            print(f"✓ ffmpeg目录存在: {ffmpeg_path}")
            bin_path = os.path.join(ffmpeg_path, 'bin')
            if os.path.exists(bin_path):
                print(f"✓ bin目录存在: {bin_path}")
                ffmpeg_exe_path = os.path.join(bin_path, 'ffmpeg.exe')
                if os.path.exists(ffmpeg_exe_path):
                    print(f"✓ ffmpeg.exe存在: {ffmpeg_exe_path}")
                else:
                    print(f"✗ ffmpeg.exe不存在: {ffmpeg_exe_path}")
            else:
                print(f"✗ bin目录不存在: {bin_path}")
        else:
            print(f"✗ ffmpeg目录不存在: {ffmpeg_path}")
    else:
        print(f"✗ thirdparty目录不存在: {thirdparty_path}")

if __name__ == "__main__":
    test_ffmpeg_path()
