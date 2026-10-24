# ShortPlayAI Engine V1.0 API文档

## 目录

1. [核心API](#核心api)
2. [插件API](#插件api)
3. [编辑器API](#编辑器api)
4. [音频处理API](#音频处理api)
5. [AI功能API](#ai功能api)
6. [事件系统API](#事件系统api)
7. [错误处理](#错误处理)

---

## 核心API

### 编辑器工厂

#### 创建编辑器实例

```python
from app.core.editor_interface import EditorFactory

editor = EditorFactory.create_editor(editor_type: str) -> IEditor
```

**参数：**
- `editor_type` (str): 编辑器类型
  - `"timeline"`: 时间线编辑器
  - `"clip"`: 片段编辑器
  - `"effect"`: 特效编辑器
  - `"transition"`: 转场编辑器
  - `"filter"`: 滤镜编辑器

**返回：**
- `IEditor`: 编辑器实例

**示例：**
```python
timeline_editor = EditorFactory.create_editor("timeline")
if timeline_editor.initialize():
    print("编辑器初始化成功")
```

### 基础编辑器接口

#### 初始化编辑器

```python
editor.initialize() -> bool
```

**返回：**
- `bool`: 初始化是否成功

#### 关闭编辑器

```python
editor.shutdown() -> bool
```

**返回：**
- `bool`: 关闭是否成功

---

## 插件API

### 插件管理器

#### 创建插件管理器

```python
from app.core.plugin_hotloader import PluginManager

manager = PluginManager()
```

#### 添加插件目录

```python
manager.add_plugin_dir(directory: str) -> bool
```

**参数：**
- `directory` (str): 插件目录路径

**返回：**
- `bool`: 添加是否成功

**示例：**
```python
import os
plugins_dir = os.path.join(os.path.dirname(__file__), "plugins")
manager.add_plugin_dir(plugins_dir)
```

#### 发现插件

```python
plugins = manager.discover_plugins() -> List[PluginInfo]
```

**返回：**
- `List[PluginInfo]`: 插件信息列表

#### 加载插件

```python
success = manager.load_plugin(
    plugin_id: str,
    context: Optional[Dict[str, Any]] = None,
    auto_initialize: bool = True
) -> bool
```

**参数：**
- `plugin_id` (str): 插件ID
- `context` (Optional[Dict[str, Any]]): 插件上下文
- `auto_initialize` (bool): 是否自动初始化

**返回：**
- `bool`: 加载是否成功

**示例：**
```python
plugins = manager.discover_plugins()
for plugin in plugins:
    if manager.load_plugin(plugin.id):
        print(f"插件 {plugin.name} 加载成功")
```

#### 卸载插件

```python
success = manager.unload_plugin(plugin_id: str) -> bool
```

**参数：**
- `plugin_id` (str): 插件ID

**返回：**
- `bool`: 卸载是否成功

#### 重新加载插件

```python
success = manager.reload_plugin(plugin_id: str) -> bool
```

**参数：**
- `plugin_id` (str): 插件ID

**返回：**
- `bool`: 重新加载是否成功

#### 获取插件实例

```python
plugin = manager.get_plugin(plugin_id: str) -> Optional[IPlugin]
```

**参数：**
- `plugin_id` (str): 插件ID

**返回：**
- `Optional[IPlugin]`: 插件实例，如果不存在返回None

#### 获取插件信息

```python
info = manager.get_plugin_info(plugin_id: str) -> Optional[PluginInfo]
```

**参数：**
- `plugin_id` (str): 插件ID

**返回：**
- `Optional[PluginInfo]`: 插件信息，如果不存在返回None

#### 获取插件状态

```python
state = manager.get_plugin_state(plugin_id: str) -> Optional[PluginState]
```

**参数：**
- `plugin_id` (str): 插件ID

**返回：**
- `Optional[PluginState]`: 插件状态，如果不存在返回None

#### 列出插件

```python
plugins = manager.list_plugins(
    plugin_type: Optional[PluginType] = None,
    category: Optional[PluginCategory] = None,
    state: Optional[PluginState] = None
) -> List[PluginInfo]
```

**参数：**
- `plugin_type` (Optional[PluginType]): 插件类型过滤
- `category` (Optional[PluginCategory]): 插件分类过滤
- `state` (Optional[PluginState]): 插件状态过滤

**返回：**
- `List[PluginInfo]`: 过滤后的插件列表

**示例：**
```python
# 获取所有特效插件
effect_plugins = manager.list_plugins(plugin_type=PluginType.EFFECT)

# 获取已加载的插件
loaded_plugins = manager.list_plugins(state=PluginState.LOADED)
```

#### 搜索插件

```python
results = manager.search_plugins(query: str) -> List[PluginInfo]
```

**参数：**
- `query` (str): 搜索关键词

**返回：**
- `List[PluginInfo]`: 匹配的插件列表

**示例：**
```python
results = manager.search_plugins("金光")
for plugin in results:
    print(f"找到插件: {plugin.name}")
```

#### 获取统计信息

```python
stats = manager.get_statistics() -> Dict[str, Any]
```

**返回：**
- `Dict[str, Any]`: 统计信息
  - `total_plugins`: 总插件数
  - `loaded_plugins`: 已加载插件数
  - `initialized_plugins`: 已初始化插件数
  - `error_plugins`: 错误插件数
  - `by_type`: 按类型统计
  - `by_category`: 按分类统计

**示例：**
```python
stats = manager.get_statistics()
print(f"总插件数: {stats['total_plugins']}")
print(f"已加载: {stats['loaded_plugins']}")
```

### 插件接口

#### 基础插件接口

```python
from app.core.plugin_loader import IPlugin, PluginInfo

class MyPlugin(IPlugin):
    @property
    def plugin_info(self) -> PluginInfo:
        return PluginInfo(
            id="my_plugin",
            name="我的插件",
            version="1.0.0",
            description="插件描述",
            author="开发者",
            plugin_type=PluginType.EFFECT,
            category=PluginCategory.GENERAL,
            file_path=__file__,
            tags=["标签1", "标签2"]
        )
    
    def initialize(self, context: Dict[str, Any]) -> bool:
        """初始化插件"""
        return True
    
    def shutdown(self) -> bool:
        """关闭插件"""
        return True
    
    def get_ui_config(self) -> Dict[str, Any]:
        """获取UI配置"""
        return {
            "name": "我的插件",
            "icon": "🔧",
            "params": []
        }
```

#### 特效插件接口

```python
from app.core.plugin_loader import IEffectPlugin

class MyEffectPlugin(IEffectPlugin):
    def apply_effect(self, frame_data: Any, params: Dict[str, Any]) -> Any:
        """
        应用特效
        
        参数:
            frame_data: 帧数据
            params: 特效参数
        
        返回:
            处理后的帧数据
        """
        pass
    
    def get_effect_params(self) -> Dict[str, Any]:
        """获取特效参数"""
        pass
```

#### 转场插件接口

```python
from app.core.plugin_loader import ITransitionPlugin

class MyTransitionPlugin(ITransitionPlugin):
    def apply_transition(self, from_frame: Any, to_frame: Any,
                        progress: float, params: Dict[str, Any]) -> Any:
        """
        应用转场
        
        参数:
            from_frame: 起始帧
            to_frame: 结束帧
            progress: 转场进度 (0.0-1.0)
            params: 转场参数
        
        返回:
            转场后的帧数据
        """
        pass
    
    def get_transition_params(self) -> Dict[str, Any]:
        """获取转场参数"""
        pass
```

---

## 编辑器API

### 多轨道编辑器

#### 创建轨道

```python
from app.core.multitrack_editor import MultiTrackEditor, TrackType

editor = MultiTrackEditor()
track = editor.create_track(
    name: str,
    track_type: TrackType,
    index: Optional[int] = None
) -> Track
```

**参数：**
- `name` (str): 轨道名称
- `track_type` (TrackType): 轨道类型
  - `TrackType.VIDEO`: 视频轨道
  - `TrackType.AUDIO`: 音频轨道
  - `TrackType.SUBTITLE`: 字幕轨道
  - `TrackType.EFFECT`: 特效轨道
  - `TrackType.TITLE`: 标题轨道
  - `TrackType.OVERLAY`: 叠加轨道
- `index` (Optional[int]): 轨道索引

**返回：**
- `Track`: 轨道对象

**示例：**
```python
video_track = editor.create_track("Video Track 1", TrackType.VIDEO)
audio_track = editor.create_track("Audio Track 1", TrackType.AUDIO)
```

#### 删除轨道

```python
success = editor.delete_track(track_id: str) -> bool
```

**参数：**
- `track_id` (str): 轨道ID

**返回：**
- `bool`: 删除是否成功

#### 获取轨道

```python
track = editor.get_track(track_id: str) -> Optional[Track]
```

**参数：**
- `track_id` (str): 轨道ID

**返回：**
- `Optional[Track]`: 轨道对象，如果不存在返回None

#### 创建片段

```python
clip = editor.create_clip(
    track_id: str,
    name: str,
    media_path: str,
    start: float,
    end: float,
    source_start: float = 0.0,
    source_end: Optional[float] = None
) -> Optional[Clip]
```

**参数：**
- `track_id` (str): 轨道ID
- `name` (str): 片段名称
- `media_path` (str): 媒体文件路径
- `start` (float): 开始时间（秒）
- `end` (float): 结束时间（秒）
- `source_start` (float): 源开始时间（秒）
- `source_end` (Optional[float]): 源结束时间（秒）

**返回：**
- `Optional[Clip]`: 片段对象，如果创建失败返回None

**示例：**
```python
clip = editor.create_clip(
    track_id=video_track.id,
    name="My Video",
    media_path="video.mp4",
    start=0.0,
    end=10.0
)
```

#### 删除片段

```python
success = editor.delete_clip(clip_id: str) -> bool
```

**参数：**
- `clip_id` (str): 片段ID

**返回：**
- `bool`: 删除是否成功

#### 移动片段

```python
success = editor.move_clip(
    clip_id: str,
    delta: float,
    mode: Optional[EditMode] = None
) -> bool
```

**参数：**
- `clip_id` (str): 片段ID
- `delta` (float): 移动时间偏移（秒）
- `mode` (Optional[EditMode]): 编辑模式

**返回：**
- `bool`: 移动是否成功

**示例：**
```python
from app.core.multitrack_editor import EditMode

# 向右移动2秒
editor.move_clip(clip_id, 2.0)

# 使用波纹模式移动
editor.move_clip(clip_id, 2.0, EditMode.RIPPLE)
```

#### 调整片段大小

```python
success = editor.resize_clip(
    clip_id: str,
    start: float,
    end: float
) -> bool
```

**参数：**
- `clip_id` (str): 片段ID
- `start` (float): 新的开始时间
- `end` (float): 新的结束时间

**返回：**
- `bool`: 调整是否成功

#### 分割片段

```python
clips = editor.split_clip(
    clip_id: str,
    position: float
) -> Optional[List[str]]
```

**参数：**
- `clip_id` (str): 片段ID
- `position` (float): 分割位置（秒）

**返回：**
- `Optional[List[str]]`: 新片段ID列表，如果分割失败返回None

#### 设置编辑模式

```python
editor.set_edit_mode(mode: EditMode) -> None
```

**参数：**
- `mode` (EditMode): 编辑模式
  - `EditMode.NORMAL`: 普通模式
  - `EditMode.RIPPLE`: 波纹模式
  - `EditMode.ROLLING`: 滚动模式
  - `EditMode.SLIP`: 滑动模式
  - `EditMode.SLIDE`: 滑移模式

**示例：**
```python
editor.set_edit_mode(EditMode.RIPPLE)
```

#### 添加标记

```python
marker_id = editor.add_marker(
    position: float,
    name: str,
    color: str = "#f39c12",
    comment: str = ""
) -> str
```

**参数：**
- `position` (float): 标记位置（秒）
- `name` (str): 标记名称
- `color` (str): 标记颜色
- `comment` (str): 标记注释

**返回：**
- `str`: 标记ID

---

## 音频处理API

### 音频处理器

#### 创建音频处理器

```python
from app.core.audio_processor import AudioProcessor

processor = AudioProcessor()
```

#### 检测BGM节拍

```python
beats = processor.detect_bgm_beats(
    audio_data: np.ndarray,
    sample_rate: int,
    progress_callback: Optional[Callable[[int, str], None]] = None
) -> List[BeatPoint]
```

**参数：**
- `audio_data` (np.ndarray): 音频数据
- `sample_rate` (int): 采样率
- `progress_callback` (Optional[Callable[[int, str], None]]): 进度回调

**返回：**
- `List[BeatPoint]`: 节拍点列表

**示例：**
```python
import numpy as np
import librosa

# 加载音频
audio_data, sample_rate = librosa.load("bgm.mp3", sr=None)

# 检测节拍
beats = processor.detect_bgm_beats(audio_data, sample_rate)

for beat in beats:
    print(f"节拍位置: {beat.time}s, 强度: {beat.intensity}")
```

#### 去除口水音

```python
cleaned_audio = processor.remove_mouth_sounds(
    audio_data: np.ndarray,
    sample_rate: int,
    progress_callback: Optional[Callable[[int, str], None]] = None
) -> np.ndarray
```

**参数：**
- `audio_data` (np.ndarray): 音频数据
- `sample_rate` (int): 采样率
- `progress_callback` (Optional[Callable[[int, str], None]]): 进度回调

**返回：**
- `np.ndarray`: 处理后的音频数据

#### 应用变声

```python
changed_audio = processor.apply_voice_change(
    audio_data: np.ndarray,
    sample_rate: int,
    profile_name: str,
    progress_callback: Optional[Callable[[int, str], None]] = None
) -> np.ndarray
```

**参数：**
- `audio_data` (np.ndarray): 音频数据
- `sample_rate` (int): 采样率
- `profile_name` (str): 声线配置名称
  - `"male_deep"`: 男声深沉
  - `"male_normal"`: 男声正常
  - `"female_sweet"`: 女声甜美
  - `"female_mature"`: 女声成熟
  - `"child_cute"`: 童声可爱
- `progress_callback` (Optional[Callable[[int, str], None]]): 进度回调

**返回：**
- `np.ndarray`: 变声后的音频数据

**示例：**
```python
# 应用女声甜美变声
sweet_voice = processor.apply_voice_change(audio_data, sample_rate, "female_sweet")
```

#### 应用人声闪避

```python
voice_audio, bgm_audio = processor.apply_voice_ducking(
    voice_audio: np.ndarray,
    bgm_audio: np.ndarray,
    sample_rate: int,
    ducking_amount: float = 0.7,
    attack_time: float = 0.1,
    release_time: float = 0.5,
    progress_callback: Optional[Callable[[int, str], None]] = None
) -> Tuple[np.ndarray, np.ndarray]
```

**参数：**
- `voice_audio` (np.ndarray): 人声音频
- `bgm_audio` (np.ndarray): BGM音频
- `sample_rate` (int): 采样率
- `ducking_amount` (float): 闪避强度 (0.0-1.0)
- `attack_time` (float): 攻击时间（秒）
- `release_time` (float): 释放时间（秒）
- `progress_callback` (Optional[Callable[[int, str], None]]): 进度回调

**返回：**
- `Tuple[np.ndarray, np.ndarray]`: 处理后的人声和BGM音频

**示例：**
```python
# 应用人声闪避
processed_voice, processed_bgm = processor.apply_voice_ducking(
    voice_audio, bgm_audio, sample_rate, ducking_amount=0.7
)
```

#### 获取声线配置

```python
profiles = processor.get_voice_profiles() -> List[VoiceProfile]
```

**返回：**
- `List[VoiceProfile]`: 声线配置列表

---

## AI功能API

### AI剪辑助手

#### 创建AI助手

```python
from app.core.ai_editing_assistant import AIEditingAssistant

assistant = AIEditingAssistant()
```

#### 分析视频

```python
result = assistant.analyze_video(
    video_frames: List[np.ndarray],
    progress_callback: Optional[callable] = None
) -> Dict[str, Any]
```

**参数：**
- `video_frames` (List[np.ndarray]): 视频帧列表
- `progress_callback` (Optional[callable]): 进度回调

**返回：**
- `Dict[str, Any]`: 分析结果
  - `total_scenes`: 总场景数
  - `total_suggestions`: 总建议数
  - `scene_types`: 场景类型统计
  - `suggestion_types`: 建议类型统计
  - `average_confidence`: 平均置信度

**示例：**
```python
import numpy as np

# 生成测试帧
frames = [np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8) 
           for _ in range(10)]

# 分析视频
result = assistant.analyze_video(frames)
print(f"发现 {result['total_scenes']} 个场景")
print(f"生成 {result['total_suggestions']} 条建议")
```

### 字幕生成器

#### 创建字幕生成器

```python
from app.core.subtitle_generator import SubtitleGenerator

generator = SubtitleGenerator()
```

#### 转写音频

```python
subtitles = generator.transcribe_audio(
    audio_path: str,
    language: str = "zh",
    model_size: str = "base",
    progress_callback: Optional[callable] = None
) -> List[SubtitleSegment]
```

**参数：**
- `audio_path` (str): 音频文件路径
- `language` (str): 语言代码
- `model_size` (str): 模型大小
  - `"tiny"`: 最小模型
  - `"base"`: 基础模型
  - `"small"`: 小型模型
  - `"medium"`: 中型模型
  - `"large"`: 大型模型
- `progress_callback` (Optional[callable]): 进度回调

**返回：**
- `List[SubtitleSegment]`: 字幕片段列表

**示例：**
```python
# 生成字幕
subtitles = generator.transcribe_audio("audio.wav", language="zh")

for segment in subtitles:
    print(f"{segment.start}s - {segment.end}s: {segment.text}")
```

#### 导出字幕

```python
success = generator.export_subtitles(
    subtitles: List[SubtitleSegment],
    output_path: str,
    format: str = "srt"
) -> bool
```

**参数：**
- `subtitles` (List[SubtitleSegment]): 字幕片段列表
- `output_path` (str): 输出文件路径
- `format` (str): 输出格式
  - `"srt"`: SRT格式
  - `"ass"`: ASS格式
  - `"vtt"`: VTT格式
  - `"txt"`: TXT格式

**返回：**
- `bool`: 导出是否成功

### 音乐推荐引擎

#### 创建音乐推荐引擎

```python
from app.core.music_recommendation import MusicRecommendationEngine

engine = MusicRecommendationEngine()
```

#### 推荐音乐

```python
recommendations = engine.recommend_music(
    requirement: SceneMusicRequirement,
    progress_callback: Optional[callable] = None
) -> List[MusicTrack]
```

**参数：**
- `requirement` (SceneMusicRequirement): 场景音乐需求
  - `scene_type`: 场景类型
  - `emotion`: 情感
  - `duration`: 时长
  - `preferred_genres`: 偏好类型
  - `excluded_genres`: 排除类型
  - `min_bpm`: 最小BPM
  - `max_bpm`: 最大BPM
  - `vocal_preference`: 人声偏好
- `progress_callback` (Optional[callable]): 进度回调

**返回：**
- `List[MusicTrack]`: 推荐音乐列表

**示例：**
```python
from app.core.music_recommendation import SceneMusicRequirement

# 创建需求
requirement = SceneMusicRequirement(
    scene_type="emotion",
    emotion="happy",
    duration=30.0,
    min_bpm=90,
    max_bpm=120
)

# 获取推荐
recommendations = engine.recommend_music(requirement)

for track in recommendations:
    print(f"{track.title} - {track.artist}")
```

### 语音生成器

#### 创建语音生成器

```python
from app.core.voice_generator import AIVoiceGenerator

generator = AIVoiceGenerator()
```

#### 生成配音

```python
result = generator.generate_voice(
    request: VoiceGenerationRequest,
    progress_callback: Optional[callable] = None
) -> VoiceGenerationResult
```

**参数：**
- `request` (VoiceGenerationRequest): 语音生成请求
  - `text`: 要生成的文本
  - `voice_profile`: 声线配置
  - `speed`: 语速
  - `pitch`: 音调
  - `emotion`: 情感
- `progress_callback` (Optional[callable]): 进度回调

**返回：**
- `VoiceGenerationResult`: 生成结果
  - `success`: 是否成功
  - `audio_path`: 音频文件路径
  - `duration`: 音频时长
  - `error`: 错误信息

**示例：**
```python
from app.core.voice_generator import VoiceGenerationRequest, VoiceProfile

# 创建请求
request = VoiceGenerationRequest(
    text="欢迎使用ShortPlayAI Engine",
    voice_profile=VoiceProfile.FEMALE_SWEET,
    speed=1.0,
    pitch=1.0,
    emotion="happy"
)

# 生成语音
result = generator.generate_voice(request)

if result.success:
    print(f"语音生成成功: {result.audio_path}")
```

---

## 事件系统API

### 事件总线

#### 获取事件总线实例

```python
from app.core.event_bus import EventBus

event_bus = EventBus.get_instance()
```

#### 发送事件

```python
event_bus.emit(
    event_type: EventType,
    data: Dict[str, Any]
) -> None
```

**参数：**
- `event_type` (EventType): 事件类型
- `data` (Dict[str, Any]): 事件数据

**示例：**
```python
from app.core.event_bus import EventType

event_bus.emit(
    EventType.PROJECT_SAVED,
    {"project_id": "123", "path": "/path/to/project"}
)
```

#### 订阅事件

```python
event_bus.subscribe(
    event_type: EventType,
    callback: Callable[[Event], None]
) -> str
```

**参数：**
- `event_type` (EventType): 事件类型
- `callback` (Callable[[Event], None]): 回调函数

**返回：**
- `str`: 订阅ID

**示例：**
```python
def on_project_saved(event):
    print(f"项目已保存: {event.data}")

subscription_id = event_bus.subscribe(
    EventType.PROJECT_SAVED,
    on_project_saved
)
```

#### 取消订阅

```python
event_bus.unsubscribe(subscription_id: str) -> bool
```

**参数：**
- `subscription_id` (str): 订阅ID

**返回：**
- `bool`: 取消订阅是否成功

---

## 错误处理

### 异常类型

#### 插件异常

```python
from app.core.plugin_loader import PluginLoadError, PluginDependencyError

try:
    manager.load_plugin(plugin_id)
except PluginLoadError as e:
    print(f"插件加载失败: {e}")
except PluginDependencyError as e:
    print(f"插件依赖错误: {e}")
```

#### 编辑器异常

```python
from app.core.multitrack_editor import TrackNotFoundError, ClipNotFoundError

try:
    track = editor.get_track(track_id)
except TrackNotFoundError as e:
    print(f"轨道不存在: {e}")
except ClipNotFoundError as e:
    print(f"片段不存在: {e}")
```

#### 音频处理异常

```python
from app.core.audio_processor import AudioProcessingError

try:
    beats = processor.detect_bgm_beats(audio_data, sample_rate)
except AudioProcessingError as e:
    print(f"音频处理失败: {e}")
```

#### AI功能异常

```python
from app.core.ai_editing_assistant import AIAnalysisError

try:
    result = assistant.analyze_video(frames)
except AIAnalysisError as e:
    print(f"AI分析失败: {e}")
```

### 错误处理最佳实践

```python
from app.core.plugin_loader import PluginLoadError
from app.core.multitrack_editor import TrackNotFoundError
import logging

logger = logging.getLogger(__name__)

def safe_plugin_load(manager, plugin_id):
    """安全的插件加载"""
    try:
        if manager.load_plugin(plugin_id):
            logger.info(f"插件 {plugin_id} 加载成功")
            return True
        else:
            logger.warning(f"插件 {plugin_id} 加载失败")
            return False
    except PluginLoadError as e:
        logger.error(f"插件加载异常: {e}")
        return False
    except Exception as e:
        logger.error(f"未知错误: {e}")
        return False

def safe_track_operation(editor, track_id):
    """安全的轨道操作"""
    try:
        track = editor.get_track(track_id)
        if track:
            return track
        else:
            logger.warning(f"轨道 {track_id} 不存在")
            return None
    except TrackNotFoundError as e:
        logger.error(f"轨道操作失败: {e}")
        return None
    except Exception as e:
        logger.error(f"未知错误: {e}")
        return None
```

---

**文档版本**：V1.0  
**最后更新**：2026年3月29日  
**适用版本**：ShortPlayAI Engine V1.0