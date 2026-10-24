# AI特效制作插件 🎨

> 基于深度学习的智能视频/图像特效处理系统  
> **插件版本**: 1.0.0 | **兼容版本**: 拾光剪影 V4.4.0 - V5.9.9

## ✨ 功能特性

本插件提供 **5大AI特效能力**，涵盖视频/图像处理的多个维度：

### 🖼️ 风格迁移 (Style Transfer)
- **8种预设艺术风格**：梵高星空、莫奈睡莲、毕加索抽象、赛博朋克、动漫风、油画、水彩画、素描
- 可调节风格强度（0-100%）
- 可选择保留原图颜色
- 实时预览效果

### 🎬 AI背景替换 (Background Replace)
- **智能语义分割**：自动识别前景人物/物体
- **5种背景类型**：纯色背景、模糊背景、自定义图片、渐变背景、透明背景
- 边缘平滑和抗锯齿处理
- 支持自定义颜色（颜色选择器）

### 🔍 超分辨率增强 (Super Resolution)
- 支持 **2x / 3x / 4x** 放大倍数
- **3种质量模式**：快速模式⚡、均衡模式⚖️、高质量模式🎯
- 内置降噪功能（可调节强度）
- 多尺度细节重建算法

### ✨ 智能美颜 (Beauty Filter)
- 自动人脸检测和关键点定位
- **4维美颜参数**：磨皮、美白、瘦脸、大眼
- 自然效果模式开关
- **4个快捷预设**：自然清新、柔光女神、精致妆容、韩式偶像
- 局部保护，不影响背景细节

### 🗑️ 物体移除 (Object Removal)
- **3种移除模式**：自动检测🤖、手动框选▢、笔刷涂抹🖌️
- **4种填充算法**：
  - AI Inpainting（最佳质量）
  - Content-Aware Fill（内容感知填充）
  - Blur Fill（模糊填充）
  - Clone Stamp（仿制图章）
- 支持批量移除多个物体
- 边缘羽化和平滑过渡
- **11类可检测物体**：文字/水印、Logo、印章、日期戳、人物、汽车、建筑等

---

## 📦 安装部署

### 目录结构
```
app/plugins/ai_effects_plugin/
├── __init__.py                    # 插件入口 + PLUGIN_INFO元信息
├── main.py                        # 核心Plugin类 + IEffectPlugin接口实现
├── manifest.json                  # 插件配置清单
├── effects/                       # AI特效算法模块
│   ├── __init__.py               # 特效模块集合导出
│   ├── style_transfer.py         # 风格迁移模块
│   ├── background_replace.py     # 背景替换模块
│   ├── super_resolution.py       # 超分辨率模块
│   ├── beauty_filter.py          # 智能美颜模块
│   └── object_removal.py         # 物体移除模块
├── ui/                            # 用户界面组件
│   ├── __init__.py               # UI模块导出
│   └── ai_effects_widget.py      # PyQt6控制面板Widget
├── assets/                        # 资源文件目录
│   ├── icons/                    # 图标资源
│   └── templates/                # 模板文件
└── README.md                      # 本文件
```

### 依赖要求

#### 必需依赖
```bash
numpy>=1.21.0
opencv-python>=4.5.0
Pillow>=8.0.0
PyQt6>=6.2.0
```

#### 推荐依赖（启用高级AI功能）
```bash
torch>=1.10.0              # PyTorch深度学习框架
torchvision>=0.11.0        # 视觉模型库
dlib>=19.22.0             # 人脸关键点检测（美颜功能）
mediapipe>=0.8.0          # 轻量级人脸/手势检测
```

### 安装步骤

1. **确认插件目录存在**
   ```bash
   ls app/plugins/ai_effects_plugin/
   ```

2. **安装Python依赖**
   ```bash
   pip install numpy opencv-python Pillow PyQt6
   
   # 可选：安装深度学习框架以获得更好的效果
   pip install torch torchvision dlib mediapipe
   ```

3. **下载预训练模型**（如果使用真实神经网络推理）
   ```bash
   python scripts/download_ai_models.py --all
   ```
   
   模型将存储在 `models/ai_effects/` 目录下。

4. **启动应用并加载插件**
   - 插件会自动被 `PluginLoader` 发现和加载
   - 或者在插件管理器中手动启用"AI特效制作"插件

---

## 🔧 使用指南

### 方式一：通过UI界面使用（推荐）

1. 在主界面打开 **"插件中心"**
2. 找到 **"AI特效制作"** 插件并点击 **"启动"**
3. 在弹出的控制面板中：
   - 选择顶部标签页切换到需要的特效类别
   - 调节各项参数滑块/下拉框
   - 点击 **"✨ 应用特效"** 按钮
4. 等待处理完成，结果会自动显示

### 方式二：通过代码调用API

```python
from app.plugins.ai_effects_plugin.main import Plugin, AIEffectType
import cv2
import numpy as np

# 1. 创建插件实例
plugin = Plugin()

# 2. 初始化（传入模型路径等信息）
context = {
    'models_path': './models/ai_effects',
    'gpu_enabled': True,           # 是否启用GPU加速
    'cache_dir': './cache'
}
success = plugin.initialize(context)

if success:
    # 3. 加载图像
    image = cv2.imread('input.jpg')
    
    # 4. 应用风格迁移效果
    result = plugin.apply_effect(image, params={
        'effect_type': 'style_transfer',
        'style_name': 'cyberpunk',      # 赛博朋克风格
        'style_strength': 0.8,          # 80%风格强度
        'preserve_color': True          # 保留原色
    })
    
    # 5. 保存结果
    cv2.imwrite('output_cyberpunk.jpg', result)
    
    print("✅ 处理完成！")

# 6. 关闭插件释放资源
plugin.shutdown()
```

### 更多示例

#### 示例1：背景替换
```python
result = plugin.apply_effect(image, params={
    'effect_type': 'background_replace',
    'background_type': 'blur',        # 模糊背景
    'blur_strength': 20,
    'edge_smoothness': 8
})
cv2.imwrite('blurred_bg.jpg', result)
```

#### 示例2：超分辨率放大
```python
result = plugin.apply_effect(image, params={
    'effect_type': 'super_resolution',
    'scale_factor': '4',              # 4倍放大
    'model_quality': 'quality',       # 高质量模式
    'denoise_strength': 0.3           # 轻度降噪
})
print(f"原始: {image.shape} → 放大后: {result.shape}")
```

#### 示例3：智能美颜
```python
result = plugin.apply_effect(image, params={
    'effect_type': 'beauty_filter',
    'smoothing': 0.6,                 # 磨皮60%
    'whitening': 0.35,                # 美白35%
    'face_slimming': 0.15,            # 瘦脸15%
    'eye_enlargement': 0.12,          # 大眼12%
    'natural_look': True               # 自然效果
})
```

#### 示例4：移除水印
```python
result = plugin.apply_effect(image, params={
    'effect_type': 'object_removal',
    'removal_mode': 'auto_detect',     # 自动检测
    'fill_method': 'ai_inpainting',   # AI修复
    'target_objects': ['text', 'logo'], # 移除文字和Logo
    'edge_feathering': 15
})
```

---

## ⚙️ 参数详解

### 风格迁移参数
| 参数 | 类型 | 默认值 | 范围 | 说明 |
|------|------|--------|------|------|
| `style_name` | 字符串 | `'cyberpunk'` | 见下方 | 艺术风格名称 |
| `style_strength` | 浮点数 | `0.8` | 0.0-1.0 | 风格化强度 |
| `preserve_color` | 布尔值 | `True` | - | 是否保留原图颜色 |

**可选风格名称**:
- `vangogh` - 梵高星空
- `monet` - 莫奈睡莲
- `picasso` - 毕加索抽象
- `cyberpunk` - 赛博朋克
- `anime` - 动漫风
- `oil_painting` - 油画
- `watercolor` - 水彩画
- `sketch` - 素描

### 背景替换参数
| 参数 | 类型 | 默认值 | 范围/选项 | 说明 |
|------|------|--------|----------|------|
| `background_type` | 字符串 | `'blur'` | 详见下表 | 背景类型 |
| `background_color` | 字符串 | `'#4A90E2'` | HEX颜色码 | 纯色时的颜色 |
| `blur_strength` | 整数 | `15` | 0-50 | 模糊半径(像素) |
| `edge_smoothness` | 整数 | `5` | 0-20 | 边缘平滑度 |

**背景类型选项**: `solid_color`(纯色), `blur`(模糊), `image`(自定义图片), `gradient`(渐变), `transparent`(透明)

### 超分辨率参数
| 参数 | 类型 | 默认值 | 选项 | 说明 |
|------|------|--------|------|------|
| `scale_factor` | 字符串 | `'2'` | '2','3','4' | 放大倍数 |
| `model_quality` | 字符串 | `'fast'` | 'fast','balanced','quality' | 质量速度权衡 |
| `denoise_strength` | 浮点数 | `0.3` | 0.0-1.0 | 降噪强度 |

### 智能美颜参数
| 参数 | 类型 | 默认值 | 范围 | 说明 |
|------|------|--------|------|------|
| `smoothing` | 浮点数 | `0.5` | 0.0-1.0 | 磨皮光滑程度 |
| `whitening` | 浮点数 | `0.3` | 0.0-1.0 | 皮肤提亮程度 |
| `face_slimming` | 浮点数 | `0.2` | 0.0-1.0 | 脸部轮廓调整幅度 |
| `eye_enlargement` | 浮点数 | `0.15` | 0.0-1.0 | 眼睛放大程度 |
| `natural_look` | 布尔值 | `True` | - | 启用更自然的效果 |

**快捷预设名称**: `natural`(自然清新), `soft`(柔光女神), `glamour`(精致妆容), `korean_idol`(韩式偶像)

### 物体移除参数
| 参数 | 类型 | 默认值 | 选项 | 说明 |
|------|------|--------|------|------|
| `removal_mode` | 字符串 | `'auto_detect'` | 详见下表 | 移除方式 |
| `fill_method` | 字符串 | `'ai_inpainting'` | 详见下表 | 填充算法 |
| `brush_size` | 整数 | `30` | 5-100 | 笔刷大小(像素) |
| `edge_feathering` | 整数 | `10` | 0-50 | 边缘羽化程度 |
| `target_objects` | 列表 | `None` | 见下方 | 自动目标列表 |

**移除模式**: `auto_detect`(自动), `manual_select`(手动框选), `brush_paint`(笔刷涂抹)

**填充方法**: `ai_inpainting`(AI修复), `content_aware`(内容感知), `blur_fill`(模糊填充), `clone_stamp`(仿制图章)

**可检测物体类别**: `text`, `logo`, `stamp`, `date_stamp`, `person`, `car`, `building`, `tree`, `bird`, `dog`, `cat`

---

## 🚀 高级用法

### 预加载模型（提升首次使用体验）

```python
# 在初始化后立即预加载所有或指定效果的模型
plugin.initialize({...})

# 预加载所有模型
for effect in ['style_transfer', 'background_replace', 'super_resolution', 
               'beauty_filter', 'object_removal']:
    plugin.preload_model(effect)
```

### 批量处理视频帧

```python
import cv2

video = cv2.VideoCapture('input.mp4')
writer = cv2.VideoWriter(
    'output.mp4',
    cv2.VideoWriter_fourcc(*'mp4v'),
    30.0,
    (int(video.get(3))*2, int(video.get(4))*2)  # 假设2x放大
)

frame_count = 0
while video.isOpened():
    ret, frame = video.read()
    if not ret:
        break
    
    # 应用超分辨率
    enhanced = plugin.apply_effect(frame, params={
        'effect_type': 'super_resolution',
        'scale_factor': '2',
        'model_quality': 'fast'
    })
    
    writer.write(enhanced)
    frame_count += 1
    
    if frame_count % 30 == 0:
        print(f"已处理 {frame_count} 帧...")

video.release()
writer.release()
print(f"✅ 完成！共处理 {frame_count} 帧")
```

### 注册事件回调

```python
def on_progress(percent):
    print(f"\r处理进度: {percent}%", end='')

def on_complete(result):
    print("\n处理完成！")
    cv2.imwrite('final_result.jpg', result)

def on_error(error_msg):
    print(f"\n❌ 错误: {error_msg}")

# 注册回调
plugin.register_callback('on_progress', on_progress)
plugin.register_callback('on_complete', on_complete)
plugin.register_callback('on_error', on_error)

# 现在调用apply_effect时会触发回调
result = plugin.apply_effect(image, {...})
```

---

## ⚠️ 注意事项

### 性能优化建议

1. **GPU加速**: 强烈建议安装CUDA版本的PyTorch以获得10-50倍的性能提升
   ```bash
   pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118
   ```

2. **内存管理**: 
   - 处理高分辨率图像（>4K）时建议分块处理
   - 及时调用 `shutdown()` 释放显存
   - 使用 `preload_model()` 预加载避免首次延迟

3. **实时处理**:
   - 视频实时处理推荐使用 `fast` 质量模式和 `2x` 放大
   - 美颜功能在1080p以下可实现接近实时的性能

### 已知限制

1. **演示模式**: 当前版本使用传统算法模拟深度学习效果（用于展示架构），生产环境需替换为真实的神经网络模型
2. **人脸检测精度**: 当前基于Haar级联分类器，精度有限；建议替换为dlib/Mediapipe
3. **物体移除**: 自动检测功能对复杂场景的准确率有待提升

### 故障排查

| 问题 | 可能原因 | 解决方案 |
|------|---------|---------|
| 插件未被发现 | 目录结构错误 | 确保 `__init__.py` 存在且包含 `PLUGIN_INFO` |
| 模型加载失败 | 依赖缺失 | 安装torch/dlib等必需库 |
| GPU不可用 | CUDA驱动过旧 | 更新NVIDIA驱动到最新版 |
| 内存不足 | 图像过大 | 降低分辨率或分块处理 |
| 处理结果异常 | 参数超出范围 | 检查参数是否在允许范围内 |

---

## 📊 技术架构

```
┌─────────────────────────────────────────────┐
│            UI层 (PyQt6 Widget)              │
│         AIEffectsWidget                     │
│  ┌─────────┬─────────┬─────────┬─────────┐  │
│  │风格迁移  │背景替换  │超分辨率  │智能美颜  │  │
│  ├─────────┼─────────┼─────────┼─────────┤  │
│  │物体移除  │         │         │         │  │
│  └─────────┴─────────┴─────────┴─────────┘  │
└──────────────────────┬──────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────┐
│           Plugin核心层 (main.py)             │
│         Plugin (IEffectPlugin)               │
│  • 参数验证与路由                            │
│  • 模型生命周期管理                          │
│  • 并发与线程安全                            │
│  • 回调系统                                  │
└──────────────────────┬──────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────┐
│         特效算法层 (effects/)                │
│  ┌─────────────┐  ┌──────────────────────┐  │
│  │StyleTransfer│  │ BackgroundReplace    │  │
│  │ Effect      │  │ Effect              │  │
│  ├─────────────┤  ├──────────────────────┤  │
│  │SuperReso-   │  │ BeautyFilterEffect   │  │
│  │ lutionEffect│  │ ObjectRemovalEffect   │  │
│  └─────────────┘  └──────────────────────┘  │
└─────────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────┐
│           底层基础设施                        │
│  • NumPy/OpenCV 图像处理                     │
│  • PyTorch 深度学习推理                      │
│  • PyQt6 GUI渲染                             │
└─────────────────────────────────────────────┘
```

---

## 🔄 版本历史

### v1.0.0 (2026-07-11)
- ✅ 初始版本发布
- ✅ 实现5大AI特效模块完整功能
- ✅ 完整的PyQt6用户界面
- ✅ 符合项目PLUGIN_STANDARD规范
- ✅ 支持插件热加载
- ✅ 完善的文档和示例代码

### 计划中的功能 (v1.1.0+)
- [ ] 集成真实深度学习模型（LaMa inpainting、Real-ESRGAN等）
- [ ] 批量处理队列和任务调度器
- [ ] 效果叠加和混合模式
- [ ] 自定义风格训练接口
- [ ] GPU显存监控和自适应降级
- [ ] 多语言UI支持
- [ ] 插件商店发布

---

## 📝 许可证

MIT License - 仅供拾光剪影项目内部使用

---

## 🤝 贡献指南

欢迎提交Issue和Pull Request！

**开发规范**:
1. 遵循项目的 `PLUGIN_STANDARD.md` 编码规范
2. 所有新增特效必须继承对应的Effect基类
3. UI组件必须支持深色/浅色主题切换
4. 新增功能必须提供单元测试
5. 代码注释覆盖率 > 80%

---

## 📞 技术支持

如遇到问题，请检查：
1. 日志输出：查看 `[AI特效]` 开头的日志信息
2. 依赖版本：确保所有依赖满足最低版本要求
3. 配置文件：检查 `manifest.json` 和 `PLUGIN_INFO` 格式正确性
4. 系统环境：确认GPU驱动、Python版本等符合要求

---

**祝您创作愉快！🎨✨**
