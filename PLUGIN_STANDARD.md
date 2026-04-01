# AI短剧编辑器插件开发规范标准

## 1. 插件开发规范

### 1.1 插件结构

每个插件应遵循以下目录结构：

```
plugin_name/
├── __init__.py          # 插件入口文件
├── main.py              # 插件主逻辑
├── manifest.json        # 插件配置文件
├── assets/              # 资源文件目录
│   ├── icons/           # 图标文件
│   └── templates/       # 模板文件
└── README.md            # 插件说明文档
```

### 1.2 插件入口文件 (__init__.py)

插件入口文件必须包含以下内容：

```python
"""
插件名称
插件描述
"""

from .main import PluginClass

# 插件元信息
PLUGIN_INFO = {
    "name": "插件名称",
    "version": "1.0.0",
    "author": "作者名称",
    "description": "插件描述",
    "category": "插件分类",
    "icon": "icon.png",
    "entry_point": "PluginClass"
}

# 导出插件类
__all__ = ["PluginClass", "PLUGIN_INFO"]
```

### 1.3 插件主类

插件主类必须继承自 `BasePlugin` 类，并实现以下方法：

```python
from lego.core import BasePlugin

class PluginClass(BasePlugin):
    def __init__(self):
        super().__init__()
        self.name = "插件名称"
        self.version = "1.0.0"
    
    def initialize(self):
        """初始化插件"""
        pass
    
    def run(self, data):
        """运行插件逻辑"""
        pass
    
    def cleanup(self):
        """清理插件资源"""
        pass
```

### 1.4 插件配置文件 (manifest.json)

插件配置文件必须包含以下字段：

```json
{
    "name": "插件名称",
    "version": "1.0.0",
    "author": "作者名称",
    "description": "插件描述",
    "category": "插件分类",
    "icon": "icon.png",
    "entry_point": "PluginClass",
    "dependencies": [],
    "compatibility": {
        "min_version": "3.0.0",
        "max_version": "3.9.9"
    }
}
```

### 1.5 插件分类

插件应属于以下分类之一：

- `video_processing` - 视频处理
- `ai_function` - AI功能
- `tool` - 工具
- `operation` - 运营
- `effect` - 特效
- `transition` - 转场
- `subtitle` - 字幕
- `audio` - 音频
- `export` - 导出

## 2. 插件导入标准

### 2.1 插件文件格式

插件可以以以下格式导入：

1. **单个Python文件** (.py) - 适用于简单插件
2. **ZIP压缩包** (.zip) - 适用于包含多个文件和资源的插件
3. **插件包** (.plugin) - 标准插件格式，本质是ZIP压缩包

### 2.2 导入流程

1. 用户选择插件文件
2. 系统验证插件格式
3. 提取插件信息
4. 验证插件兼容性
5. 安装插件到插件目录
6. 加载插件
7. 显示导入成功消息

### 2.3 插件目录

插件将被安装到以下目录：

```
app/plugins/
└── plugin_name/
    └── ... 插件文件 ...
```

## 3. 插件商店标准

### 3.1 插件商店结构

插件商店应包含以下部分：

1. **首页** - 推荐插件和最新插件
2. **分类浏览** - 按分类浏览插件
3. **搜索功能** - 搜索插件
4. **插件详情** - 插件详细信息和截图
5. **用户评价** - 用户评分和评论
6. **我的插件** - 已安装的插件

### 3.2 插件发布标准

插件发布到插件商店需要满足以下要求：

1. 提供完整的插件结构
2. 包含详细的README.md文档
3. 提供插件截图（至少1张）
4. 提供版本更新日志
5. 通过安全性检查
6. 提供清晰的插件功能描述

### 3.3 插件评分系统

插件商店应实现以下评分系统：

- 5星评分制
- 用户评论功能
- 评分统计和展示
- 热门插件推荐

### 3.4 插件更新机制

插件商店应提供以下更新机制：

- 自动检查更新
- 手动检查更新
- 批量更新插件
- 更新日志展示

## 4. 插件API参考

### 4.1 核心API

```python
# 插件基类
class BasePlugin:
    def initialize(self):
        """初始化插件"""
        pass
    
    def run(self, data):
        """运行插件逻辑"""
        pass
    
    def cleanup(self):
        """清理插件资源"""
        pass

# 事件总线
from lego.core import EventBus, EventType

# 数据总线
from lego.core import DataBus

# 技能引擎
from lego.skill_engine import SkillEngine
```

### 4.2 视频处理API

```python
from lego.core import VideoProcessor

# 视频处理示例
def process_video(video_path):
    processor = VideoProcessor()
    result = processor.process_video(video_path, "AutoClip")
    return result
```

### 4.3 UI组件API

```python
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QPushButton

# 创建UI示例
def create_ui():
    widget = QWidget()
    layout = QVBoxLayout(widget)
    button = QPushButton("点击我")
    layout.addWidget(button)
    return widget
```

## 5. 安全规范

### 5.1 安全要求

1. 插件不得访问用户敏感信息
2. 插件不得修改系统文件
3. 插件不得执行恶意代码
4. 插件必须通过安全性检查

### 5.2 权限管理

插件应声明所需的权限：

- `read_video` - 读取视频文件
- `write_video` - 写入视频文件
- `read_audio` - 读取音频文件
- `write_audio` - 写入音频文件
- `read_image` - 读取图片文件
- `write_image` - 写入图片文件
- `network` - 网络访问

## 6. 最佳实践

### 6.1 代码规范

1. 遵循PEP 8代码风格
2. 提供清晰的文档
3. 使用类型提示
4. 处理异常情况

### 6.2 性能优化

1. 避免阻塞主线程
2. 使用线程池处理耗时操作
3. 优化内存使用
4. 缓存计算结果

### 6.3 用户体验

1. 提供清晰的用户界面
2. 显示操作进度
3. 提供详细的错误信息
4. 支持撤销/重做操作

## 7. 示例插件

### 7.1 简单插件示例

```python
# simple_plugin.py

"""
简单插件示例
这是一个简单的插件示例，演示了插件的基本结构
"""

class SimplePlugin:
    def __init__(self):
        self.name = "简单插件"
        self.version = "1.0.0"
    
    def initialize(self):
        print("简单插件初始化")
    
    def run(self, data):
        print(f"处理数据: {data}")
        return f"处理结果: {data}"
    
    def cleanup(self):
        print("简单插件清理")

# 插件元信息
PLUGIN_INFO = {
    "name": "简单插件",
    "version": "1.0.0",
    "author": "示例作者",
    "description": "这是一个简单的插件示例",
    "category": "tool",
    "icon": "icon.png",
    "entry_point": "SimplePlugin"
}

__all__ = ["SimplePlugin", "PLUGIN_INFO"]
```

### 7.2 视频处理插件示例

```python
# video_plugin.py

"""
视频处理插件示例
这是一个视频处理插件示例，演示了如何处理视频文件
"""

from lego.core import BasePlugin, VideoProcessor

class VideoProcessingPlugin(BasePlugin):
    def __init__(self):
        super().__init__()
        self.name = "视频处理插件"
        self.version = "1.0.0"
        self.processor = VideoProcessor()
    
    def initialize(self):
        print("视频处理插件初始化")
    
    def run(self, video_path):
        print(f"处理视频: {video_path}")
        result = self.processor.process_video(video_path, "AutoClip")
        return result
    
    def cleanup(self):
        print("视频处理插件清理")

# 插件元信息
PLUGIN_INFO = {
    "name": "视频处理插件",
    "version": "1.0.0",
    "author": "示例作者",
    "description": "这是一个视频处理插件示例",
    "category": "video_processing",
    "icon": "video_icon.png",
    "entry_point": "VideoProcessingPlugin"
}

__all__ = ["VideoProcessingPlugin", "PLUGIN_INFO"]
```

## 8. 插件开发工具

### 8.1 开发环境设置

1. 安装Python 3.8+
2. 安装依赖：`pip install PyQt6 opencv-python ffmpeg-python`
3. 克隆AI短剧编辑器代码库
4. 创建插件目录结构

### 8.2 测试工具

1. 使用`plugin_test.py`测试插件
2. 运行`python plugin_test.py your_plugin.py`
3. 检查插件是否正常工作

### 8.3 打包工具

1. 使用`plugin_packer.py`打包插件
2. 运行`python plugin_packer.py plugin_directory`
3. 生成`.plugin`文件

## 9. 常见问题

### 9.1 插件导入失败

- 检查插件格式是否正确
- 检查插件依赖是否满足
- 检查插件是否兼容当前版本

### 9.2 插件运行错误

- 检查插件代码是否有语法错误
- 检查插件是否有权限访问所需资源
- 检查插件是否处理了异常情况

### 9.3 插件性能问题

- 优化插件代码
- 使用线程池处理耗时操作
- 减少内存使用

## 10. 联系方式

如有问题或建议，请联系：

- 邮箱：support@ai-editor.com
- 论坛：https://forum.ai-editor.com
- GitHub：https://github.com/ai-editor/plugins

---

**版本**: 1.0.0
**更新日期**: 2026-03-24
**适用版本**: AI短剧编辑器 v3.0+
