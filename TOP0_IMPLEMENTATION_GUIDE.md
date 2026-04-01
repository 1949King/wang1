# TOP 0级AI短剧剪辑软件 - 完整实施指南

## 🎯 你已经拥有的核心资产

### ✅ 已完成的模块

1. **AI剧情理解引擎** (`drama_understanding_engine.py`)
   - ✅ 4层理解：语音层、文本层、视觉层、决策层
   - ✅ Whisper语音识别集成
   - ✅ Ollama本地LLM集成
   - ✅ OpenCV视觉分析
   - ✅ 情绪曲线生成
   - ✅ 高光片段提取

2. **专业剪辑引擎** (`professional_video_engine.py`)
   - ✅ FFmpeg专业封装
   - ✅ 无损剪辑（不重新编码）
   - ✅ 硬解码加速（NVIDIA/Intel）
   - ✅ 批量任务处理
   - ✅ 多平台导出预设
   - ✅ 实时进度回调

3. **TOP 0集成模块** (`top0_integration.py`)
   - ✅ 一键式智能剪辑
   - ✅ 批量处理支持
   - ✅ 与现有Skill引擎集成
   - ✅ 完整的分析-策略-执行流程

---

## 📋 实施路线图（从今天开始）

### 第1阶段：环境准备（今天）

#### 1.1 安装依赖

```bash
# 核心依赖
pip install whisper openai-whisper
pip install ollama
pip install opencv-python pillow numpy

# 确保FFmpeg已安装
# Windows: 下载 https://www.gyan.dev/ffmpeg/builds/ 并添加到PATH
# Mac: brew install ffmpeg
# Linux: sudo apt install ffmpeg
```

#### 1.2 配置本地AI

```bash
# 安装Ollama
# Windows/Mac: 从 https://ollama.com 下载安装

# 拉取需要的模型
ollama pull qwen2.5        # 通义千问，中文理解强
ollama pull deepseek-coder  # 代码和结构化输出

# 验证安装
ollama list
```

#### 1.3 验证安装

```python
# 创建测试脚本 test_top0.py
from app.modules.lego.top0_integration import Top0VideoProcessor

processor = Top0VideoProcessor()
print("✅ TOP 0级处理器初始化成功!")
processor.shutdown()
```

---

### 第2阶段：集成到现有系统（明天）

#### 2.1 在modules.py中添加TOP 0剪辑功能

找到 `EditorModule` 类，添加TOP 0智能剪辑按钮：

```python
def _create_ai_tools_tab(self) -> QWidget:
    # ... 现有代码 ...
    
    # 添加TOP 0智能剪辑按钮
    top0_btn = QPushButton("🚀 TOP 0 智能剪辑")
    top0_btn.setStyleSheet("""
        QPushButton {
            background-color: #ff6b6b;
            color: white;
            border: none;
            border-radius: 8px;
            padding: 12px 24px;
            font-size: 14px;
            font-weight: bold;
        }
        QPushButton:hover {
            background-color: #ff5252;
        }
    """)
    top0_btn.clicked.connect(self._top0_smart_clip)
    layout.addWidget(top0_btn)
    
    # ... 其他工具 ...

def _top0_smart_clip(self):
    """TOP 0级智能剪辑"""
    if not self._clips:
        QMessageBox.warning(self, "提示", "请先导入视频")
        return
    
    from .top0_integration import Top0VideoProcessor
    
    # 创建进度对话框
    progress = QProgressDialog("准备智能剪辑...", "取消", 0, 100, self)
    progress.setWindowTitle("TOP 0 智能剪辑")
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.show()
    
    def update_progress(value, message):
        progress.setValue(int(value))
        progress.setLabelText(message)
        QApplication.processEvents()
    
    try:
        processor = Top0VideoProcessor()
        
        result = processor.smart_clip(
            self._clips[0]['path'],
            target_platform="抖音",
            video_style="高光剪辑",
            progress_callback=update_progress
        )
        
        if result['success']:
            QMessageBox.information(
                self, 
                "剪辑完成", 
                f"成功生成 {len(result['output_videos'])} 个高光片段!\n"
                f"输出目录: {os.path.dirname(result['output_videos'][0]['path'])}"
            )
        else:
            QMessageBox.warning(self, "剪辑失败", str(result['errors']))
            
    except Exception as e:
        QMessageBox.critical(self, "错误", f"剪辑失败: {str(e)}")
    finally:
        progress.close()
        if 'processor' in locals():
            processor.shutdown()
```

#### 2.2 添加新的Skill

在 `account_skills.py` 中添加TOP 0剪辑Skill：

```python
class Top0SmartClipSkill(Skill):
    """TOP 0级智能剪辑Skill"""
    
    def __init__(self):
        super().__init__(
            skill_id="top0_smart_clip",
            name="TOP 0智能剪辑",
            description="使用AI理解剧情，自动生成高光片段",
            version="1.0.0"
        )
        self.processor = None
    
    def execute(self, context: SkillContext) -> SkillResult:
        video_path = context.get_param("video_path")
        platform = context.get_param("platform", "抖音")
        style = context.get_param("style", "高光剪辑")
        
        if not self.processor:
            from ..top0_integration import Top0VideoProcessor
            self.processor = Top0VideoProcessor()
        
        result = self.processor.smart_clip(
            video_path,
            target_platform=platform,
            video_style=style
        )
        
        return SkillResult(
            success=result['success'],
            data=result,
            message=f"生成 {len(result['output_videos'])} 个片段"
        )
    
    def shutdown(self):
        if self.processor:
            self.processor.shutdown()
```

---

### 第3阶段：优化和测试（本周内）

#### 3.1 性能优化

```python
# 在 drama_understanding_engine.py 中添加缓存

class DramaUnderstandingEngine:
    def __init__(self, ...):
        # ... 现有代码 ...
        self._analysis_cache = {}  # 添加缓存
    
    def analyze_video(self, video_path: str) -> DramaStructure:
        # 检查缓存
        cache_key = self._get_cache_key(video_path)
        if cache_key in self._analysis_cache:
            print("🔄 使用缓存的分析结果")
            return self._analysis_cache[cache_key]
        
        # 执行分析
        drama = self._perform_analysis(video_path)
        
        # 保存到缓存
        self._analysis_cache[cache_key] = drama
        
        return drama
    
    def _get_cache_key(self, video_path: str) -> str:
        import hashlib
        stat = os.stat(video_path)
        key = f"{video_path}_{stat.st_size}_{stat.st_mtime}"
        return hashlib.md5(key.encode()).hexdigest()
```

#### 3.2 添加更多平台预设

```python
# 在 professional_video_engine.py 中扩展平台预设

PLATFORM_PRESETS = {
    "抖音": ExportSettings(...),
    "快手": ExportSettings(...),
    "小红书": ExportSettings(...),
    "B站": ExportSettings(...),
    "视频号": ExportSettings(
        resolution=(1080, 1920),
        fps=30.0,
        video_bitrate="4M",
        # 视频号特殊要求
        extra_args=["-movflags", "+faststart"]  # 快速启动
    ),
    "YouTube": ExportSettings(
        resolution=(1920, 1080),
        fps=60.0,
        video_codec=VideoCodec.H264,
        video_bitrate="12M",
        preset="slow",
        crf=18
    )
}
```

#### 3.3 添加更多剪辑风格

```python
# 在 drama_understanding_engine.py 中扩展风格

VIDEO_STYLES = {
    "高光剪辑": {
        "structure": "钩子 → 爽点 → 反转 → 悬念",
        "effects": ["快速剪辑", "强调音效", "大字幕"],
        "target_duration": 15
    },
    "剧情解说": {
        "structure": "背景 → 冲突 → 高潮 → 结局",
        "effects": ["旁白", "转场", "背景音乐"],
        "target_duration": 180
    },
    "CP向混剪": {
        "structure": "相遇 → 甜蜜 → 虐心 → 重逢",
        "effects": ["慢动作", "柔光", "浪漫音乐"],
        "target_duration": 60
    },
    "悬疑向": {
        "structure": "悬念 → 线索 → 误导 → 真相",
        "effects": ["快速切换", "紧张音乐", "黑白滤镜"],
        "target_duration": 30
    },
    "搞笑向": {
        "structure": "铺垫 → 笑点 → 反转 → callback",
        "effects": ["表情包", "音效", "放大特效"],
        "target_duration": 15
    }
}
```

---

### 第4阶段：高级功能（下周）

#### 4.1 添加字幕自动生成

```python
# 在 drama_understanding_engine.py 中添加

def generate_subtitles(self, drama: DramaStructure) -> str:
    """生成字幕文件"""
    srt_content = []
    
    for i, dialogue in enumerate(drama.dialogues, 1):
        start = self._seconds_to_srt_time(dialogue.start_time)
        end = self._seconds_to_srt_time(dialogue.end_time)
        
        srt_content.append(f"{i}")
        srt_content.append(f"{start} --> {end}")
        srt_content.append(dialogue.text)
        srt_content.append("")
    
    return "\n".join(srt_content)

def _seconds_to_srt_time(self, seconds: float) -> str:
    """转换为SRT时间格式"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"
```

#### 4.2 添加BGM自动匹配

```python
# 创建 bgm_matcher.py

class BGMMatcher:
    """BGM自动匹配器"""
    
    BGM_LIBRARY = {
        "高能电音": ["bgm/energetic_1.mp3", "bgm/energetic_2.mp3"],
        "紧张悬疑": ["bgm/suspense_1.mp3", "bgm/suspense_2.mp3"],
        "浪漫温馨": ["bgm/romantic_1.mp3", "bgm/romantic_2.mp3"],
        "搞笑欢快": ["bgm/funny_1.mp3", "bgm/funny_2.mp3"],
        "悲伤抒情": ["bgm/sad_1.mp3", "bgm/sad_2.mp3"]
    }
    
    def match_bgm(self, drama: DramaStructure) -> str:
        """根据剧情匹配合适的BGM"""
        # 分析情绪分布
        emotions = [d.emotion for d in drama.dialogues]
        
        # 统计情绪
        emotion_counts = {}
        for e in emotions:
            emotion_counts[e] = emotion_counts.get(e, 0) + 1
        
        # 找到主导情绪
        dominant_emotion = max(emotion_counts, key=emotion_counts.get)
        
        # 映射到BGM风格
        bgm_style = self._emotion_to_bgm(dominant_emotion)
        
        # 随机选择一首
        import random
        return random.choice(self.BGM_LIBRARY.get(bgm_style, self.BGM_LIBRARY["高能电音"]))
    
    def _emotion_to_bgm(self, emotion: EmotionalTone) -> str:
        mapping = {
            EmotionalTone.EXCITING: "高能电音",
            EmotionalTone.HAPPY: "搞笑欢快",
            EmotionalTone.ROMANTIC: "浪漫温馨",
            EmotionalTone.SUSPENSE: "紧张悬疑",
            EmotionalTone.SAD: "悲伤抒情",
            EmotionalTone.ANGRY: "高能电音",
            EmotionalTone.TENSE: "紧张悬疑"
        }
        return mapping.get(emotion, "高能电音")
```

#### 4.3 添加封面自动生成

```python
# 创建 cover_generator.py

class CoverGenerator:
    """封面生成器"""
    
    def generate_cover(self, video_path: str, 
                      highlight: HighlightClip,
                      title: str) -> str:
        """生成视频封面"""
        import cv2
        from PIL import Image, ImageDraw, ImageFont
        
        # 提取关键帧
        cap = cv2.VideoCapture(video_path)
        cap.set(cv2.CAP_PROP_POS_MSEC, highlight.start_time * 1000)
        ret, frame = cap.read()
        cap.release()
        
        if not ret:
            return None
        
        # 转换为PIL Image
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(frame_rgb)
        
        # 添加文字
        draw = ImageDraw.Draw(image)
        
        # 添加标题
        try:
            font = ImageFont.truetype("arial.ttf", 60)
        except:
            font = ImageFont.load_default()
        
        # 计算文字位置（居中底部）
        bbox = draw.textbbox((0, 0), title, font=font)
        text_width = bbox[2] - bbox[0]
        x = (image.width - text_width) // 2
        y = image.height - 150
        
        # 添加文字阴影
        draw.text((x+2, y+2), title, font=font, fill="black")
        draw.text((x, y), title, font=font, fill="white")
        
        # 保存
        cover_path = video_path.replace('.mp4', '_cover.jpg')
        image.save(cover_path, quality=95)
        
        return cover_path
```

---

## 🚀 快速启动命令

### 启动应用

```bash
# 进入项目目录
cd "d:\本地磁盘(当前分区)(C)\Users\Administrator\Desktop\AI短剧编辑器2\app"

# 激活虚拟环境（如果有）
..\venv\Scripts\activate

# 启动应用
python main_qt6.py
```

### 测试TOP 0功能

```python
# 创建测试脚本
from app.modules.lego.top0_integration import Top0VideoProcessor
import os

processor = Top0VideoProcessor()

# 测试分析
result = processor.analyze_only("path/to/your/video.mp4")
print(f"标题: {result['title']}")
print(f"类型: {result['genre']}")
print(f"高光片段: {len(result['highlights'])}")

# 测试剪辑
clip_result = processor.smart_clip(
    "path/to/your/video.mp4",
    target_platform="抖音",
    video_style="高光剪辑"
)

print(f"剪辑成功: {clip_result['success']}")
print(f"输出视频: {len(clip_result['output_videos'])} 个")

processor.shutdown()
```

---

## 📊 性能基准测试

### 测试目标

| 指标 | 目标值 | 说明 |
|------|--------|------|
| 视频分析速度 | 1分钟视频 < 30秒 | AI理解4层分析 |
| 无损剪辑速度 | 10秒片段 < 1秒 | 不重新编码 |
| 重新编码速度 | 10秒片段 < 5秒 | 使用硬件加速 |
| 批量处理 | 100个视频 < 30分钟 | 4线程并行 |
| 内存占用 | < 4GB | 处理4K视频 |

### 优化建议

1. **使用更大的Whisper模型**：base → small → medium（精度提升，速度降低）
2. **启用硬件加速**：NVIDIA NVENC比CPU快10倍
3. **调整采样率**：视觉分析每2秒采样→每5秒采样（速度提升，精度略降）
4. **使用SSD**：视频读写速度提升5倍

---

## 🎯 下一步行动清单

### 今天必须完成

- [ ] 安装所有依赖（whisper, ollama, opencv）
- [ ] 配置Ollama并拉取qwen2.5模型
- [ ] 验证FFmpeg安装
- [ ] 运行测试脚本验证TOP 0处理器

### 明天完成

- [ ] 在modules.py中添加TOP 0剪辑按钮
- [ ] 添加进度对话框
- [ ] 测试完整剪辑流程
- [ ] 修复可能出现的bug

### 本周完成

- [ ] 添加缓存机制
- [ ] 扩展平台预设（视频号、YouTube）
- [ ] 添加更多剪辑风格
- [ ] 性能优化

### 下周完成

- [ ] 自动生成字幕
- [ ] BGM自动匹配
- [ ] 封面自动生成
- [ ] 批量处理优化

---

## 💡 关键提示

### 关于AI模型选择

**Whisper模型**：
- `tiny`: 最快，精度最低（适合测试）
- `base`: 平衡选择（推荐）
- `small`: 较好精度
- `medium`/`large`: 最高精度，但慢

**Ollama模型**：
- `qwen2.5`: 中文理解最强（推荐）
- `deepseek-coder`: 结构化输出好
- `llama3.2`: 英文好，中文一般

### 关于硬件加速

**NVIDIA显卡**：
```python
# 自动检测并使用NVENC
settings = ExportSettings(
    video_codec=VideoCodec.H264_NVENC,
    preset="fast"
)
```

**Intel核显**：
```python
settings = ExportSettings(
    video_codec=VideoCodec.H264_QSV,
    preset="fast"
)
```

### 关于错误处理

```python
try:
    result = processor.smart_clip(video_path)
    if not result