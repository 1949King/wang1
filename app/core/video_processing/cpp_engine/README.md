# Py+C++ 混合内核编译指南

## 概述

本项目采用 **Py+C++ 混合架构**，核心视频处理功能由 C++ 实现，通过 pybind11 绑定到 Python，实现高性能视频处理。

## 架构说明

```
app/core/video_processing/cpp_engine/
├── video_engine.h          # C++ 视频引擎头文件
├── video_engine.cpp        # C++ 视频引擎实现
├── pybind11_wrapper.cpp    # Python 绑定接口
├── __init__.py             # Python 封装层
├── CMakeLists.txt          # CMake 构建配置
── build.bat               # Windows 编译脚本
```

## 依赖要求

### 必需依赖

| 依赖 | 版本要求 | 说明 |
|------|---------|------|
| CMake | 3.15+ | 构建系统 |
| Python | 3.12+ | Python 环境 |
| pybind11 | 2.10+ | C++/Python 绑定 |
| FFmpeg | 6.0+ | 视频处理库 |
| Visual Studio | 2022 | Windows 编译器 |

### 可选依赖

| 依赖 | 说明 |
|------|------|
| NVIDIA CUDA | GPU 加速编码 |
| Intel Media SDK | Intel QSV 加速 |
| AMD AMF | AMD 硬件加速 |

## 编译步骤

### 1. 安装 FFmpeg 开发库

```powershell
# 下载 FFmpeg 开发包
# 解压到 C:\ffmpeg

# 设置环境变量
$env:FFMPEG_DIR = "C:\ffmpeg"
```

### 2. 安装 Python 依赖

```powershell
pip install pybind11
```

### 3. 编译 C++ 引擎

```powershell
cd app/core/video_processing/cpp_engine
.\build.bat
```

### 4. 验证编译

```python
from app.core.video_processing.cpp_engine import get_engine, is_cpp_engine_available

if is_cpp_engine_available():
    engine = get_engine()
    print("C++ 视频引擎加载成功！")
else:
    print("C++ 视频引擎不可用")
```

## API 使用示例

### 视频分析

```python
from app.core.video_processing.cpp_engine import get_engine

engine = get_engine()
info = engine.analyze_video("input.mp4")

print(f"分辨率: {info.width}x{info.height}")
print(f"帧率: {info.fps}")
print(f"时长: {info.duration}秒")
```

### 视频剪辑

```python
result = engine.clip_video(
    input_path="input.mp4",
    output_path="output.mp4",
    start_time=10.0,
    duration=30.0,
    speed=1.0
)

if result.success:
    print(f"剪辑完成，耗时: {result.processing_time}秒")
```

### 批量提取缩略图

```python
thumbnails = engine.extract_thumbnails(
    filepath="input.mp4",
    count=10,
    output_dir="./thumbnails",
    width=160,
    height=90
)

for thumb in thumbnails:
    print(f"缩略图: {thumb}")
```

### 添加水印

```python
success = engine.add_watermark(
    input_path="input.mp4",
    output_path="output.mp4",
    text="AI短剧编辑器",
    font_size=24,
    color="white"
)
```

### 合并视频片段

```python
from app.core.video_processing.cpp_engine import ClipSegment, ExportConfig

clips = [
    ClipSegment(source_path="clip1.mp4", start_time=0, end_time=10, position=0),
    ClipSegment(source_path="clip2.mp4", start_time=0, end_time=15, position=10),
]

config = ExportConfig()
config.codec = "libx264"
config.bitrate = 5000

result = engine.merge_clips(clips, "output.mp4", config)
```

## 性能优化

### GPU 加速

```python
# 自动检测 GPU 编码器
gpu_encoder = engine.get_gpu_encoder()
print(f"GPU 编码器: {gpu_encoder}")

# 使用 GPU 编码
config = ExportConfig()
config.codec = gpu_encoder if gpu_encoder else "libx264"
config.use_gpu = True
```

### 多线程处理

```python
# 设置线程池大小
engine.set_thread_pool_size(8)

# 处理大文件时启用多线程
result = engine.convert_format(
    input_path="large_video.mp4",
    output_path="output.mp4",
    config=config
)
```

## 故障排除

### 编译失败

1. 检查 CMake 版本：`cmake --version`
2. 检查 FFmpeg 路径：确保 `FFMPEG_DIR` 正确设置
3. 检查 Visual Studio：确保安装了 C++ 桌面开发工作负载

### 运行时错误

1. 检查 pyd 文件是否存在
2. 检查 FFmpeg DLL 是否在 PATH 中
3. 查看日志：`app/logs/cpp_engine.log`

## 许可证

本项目采用 LGPL-3.0-or-later 许可证。
