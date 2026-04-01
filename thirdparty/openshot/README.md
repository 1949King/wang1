# OpenShot 双内核视频编辑引擎

## 项目简介

本项目为 AI短剧编辑器添加了**双内核视频编辑引擎**，实现了：
- **轻量内核**：基于原有 lego 模块，快速加载，适合简单编辑
- **专业内核**：基于 OpenShot，支持多轨道、特效、高质量导出

## 快速开始

### 方式一：一键部署（推荐）

```bash
cd thirdparty/openshot
run_all.bat
```

自动完成：下载依赖 → 编译 → 验证

### 方式二：分步部署

```bash
cd thirdparty/openshot

# 1. 下载依赖包
download_deps.bat

# 2. 编译内核
build.bat

# 3. 验证部署
test_deployment.bat
```

## 环境要求

### 必需工具
- **CMake 3.16+**：[下载](https://cmake.org/download/)
- **MinGW-w64** 或 **MSYS2**：[下载](https://www.msys2.org/)

### 推荐安装 MSYS2

```bash
# 安装 MSYS2 后，运行以下命令安装必需依赖
pacman -S mingw-w64-x86_64-ffmpeg
pacman -S mingw-w64-x86_64-ImageMagick
pacman -S mingw-w64-x86_64-freetype
pacman -S mingw-w64-x86_64-pkg-config
```

## 使用方法

### Python 代码示例

```python
from app.core.editor_scheduler import EditorScheduler

# 使用轻量内核（快速预览）
editor = EditorScheduler.get_light_editor()

# 使用专业内核（AI 二创、高质量导出）
timeline = EditorScheduler.get_pro_editor(width=1080, height=1920, fps=30)

# 添加视频片段
clip = EditorScheduler.add_clip(timeline, "video.mp4")

# 应用特效
EditorScheduler.apply_effect(clip, "brightness", brightness=1.2)

# 导出视频
EditorScheduler.export_video(timeline, "output.mp4", quality="high")
```

### 在 UI 中调用

```python
# 在你的 PyQt6 界面中
def on_export_clicked(self):
    try:
        # 切换到专业内核进行高质量导出
        pro_editor = EditorScheduler.get_pro_editor()
        
        # 添加时间轴上的所有片段
        for clip in self.timeline_clips:
            EditorScheduler.add_clip(pro_editor, clip.path, clip.start, clip.end)
        
        # 导出
        output_path = self.get_output_path()
        EditorScheduler.export_video(pro_editor, output_path, quality="high")
        
        QMessageBox.information(self, "成功", "视频导出完成！")
        
    except Exception as e:
        QMessageBox.critical(self, "错误", f"导出失败：{e}")
```

## 目录结构

```
thirdparty/openshot/
├── run_all.bat           # 一键部署总控脚本
├── download_deps.bat     # 下载依赖脚本
├── build.bat             # 编译脚本
├── test_deployment.bat   # 验证部署脚本
├── CMakeLists.txt        # CMake 配置
├── lib/                  # 编译输出的库文件
│   ├── libopenshot.dll
│   └── libopenshot-audio.dll
├── python/               # Python 绑定
│   ├── openshot.py
│   └── _openshot.pyd
├── engine/               # OpenShot 引擎源码
└── deps/                 # 依赖包（FFmpeg 等）
```

## 核心特性

### 1. FFmpeg 隔离技术
- 双 FFmpeg 实例，永不冲突
- 轻量内核使用系统 FFmpeg
- 专业内核使用私有静态 FFmpeg

### 2. 双内核协同
- **轻量内核**：快速预览、简单编辑
- **专业内核**：AI 二创、多轨道、特效、高质量导出

### 3. 自动化部署
- 一键下载、编译、验证
- 完善的错误检测和提示
- 并行编译，充分利用多核 CPU

## 常见问题

### Q: 编译失败，提示找不到 FFmpeg
A: 安装 MSYS2 并运行：
```bash
pacman -S mingw-w64-x86_64-ffmpeg mingw-w64-x86_64-pkg-config
```

### Q: Python 导入 openshot 失败
A: 确保已将 `thirdparty/openshot/python` 添加到 PYTHONPATH：
```python
import sys
sys.path.insert(0, './thirdparty/openshot/python')
import openshot
```

### Q: 编译时间过长
A: 使用并行编译（默认已开启）：
```bash
cmake --build . --parallel 8  # 根据你的 CPU 核心数调整
```

## 技术细节

### CMake 配置说明

```cmake
# 关键配置项
option(BUILD_FFMPEG_STATIC "静态编译 FFmpeg" ON)  # 隔离 FFmpeg
option(BUILD_EXECUTABLE "编译 UI 程序" OFF)        # 只编译库
option(BUILD_PYTHON_BINDINGS "Python 绑定" ON)    # Python 支持
option(ENABLE_OPENCL "OpenCL 加速" ON)            # GPU 加速
```

### 双内核调度原理

```python
# EditorScheduler 根据需求选择合适的内核
def get_editor(mode="auto"):
    if mode == "light" or mode == "auto":
        return get_light_editor()  # 快速加载
    elif mode == "pro":
        return get_pro_editor()    # 完整功能
```

## 下一步

1. ✅ 完成双内核编译部署
2. ✅ 实现 EditorScheduler 调度器
3. ⬜ 在 UI 中集成双内核切换
4. ⬜ 添加更多特效支持
5. ⬜ 优化 AI 二创功能

## 许可证

本项目基于 OpenShot 开发，遵循其开源许可证。

## 贡献

欢迎提交 Issue 和 Pull Request！
