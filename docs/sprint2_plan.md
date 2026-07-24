# Sprint 2 规划：智能剪辑引擎升级 & 进化Agent系统

> 规划时间：2026-06-28 | 状态：待执行
> 
> 前置完成：Sprint 1（ABCD融合矩阵、LLM情绪语义化、多模态情绪融合、情绪历程分析）

---

## 现状诊断

### ✅ 已完成
| 模块 | 功能 | 状态 |
|------|------|------|
| `drama_understanding_engine.py` | ABCD融合矩阵 `extract_highlights()` | ✅ |
| `drama_understanding_engine.py` | LLM优先8维情绪向量 | ✅ |
| `audio_emotion_analyzer.py` | librosa声学情绪分析 | ✅ |
| `drama_understanding_engine.py` | 多模态融合 `_analyze_decision_layer()` v3.0 | ✅ |
| `drama_understanding_engine.py` | 情绪历程 `_analyze_emotion_journey()` | ✅ |
| `content_classifier.py` | 内容品类分类器 | ✅ |
| `viral_detector.py` | LLM病毒基因检测 | ✅ |
| `agent_workflow.py` | PlanAgent→ClipAgent→ReviewAgent协作 | ✅ 基础框架 |

### ❌ 核心断点（前序成果未被下游消费）
| 断点位置 | 问题 | 严重度 |
|----------|------|--------|
| `ai_clip_flow.py` Step 1 | **不调用任何AI引擎**，只提取帧和元数据 | 🔴 致命 |
| `smart_editing_engine.py` | 仍用旧 `EmotionalTone` 枚举，8维向量/情绪历程全未使用 | 🔴 致命 |
| `ai_integration.py` `_run_analysis()` | 用 `random.randint()` 模拟分析，完全不接真实引擎 | 🔴 致命 |
| `smart_editing_engine.py:EMOTION_TRANSITION_MAP` | 硬编码8×2转场映射，无学习、无进化 | 🟡 严重 |
| `smart_editing_engine.py:_analyze_music_beats()` | 返回硬编码 `[i*0.5 for i in range(120)]` | 🟡 严重 |
| `drama_understanding_engine.py:generate_editing_strategy()` | BGM/转场/字幕完全硬编码平台映射 | 🟡 严重 |
| 无 MemoryBank | 无决策记录、无反馈闭环、无进化能力 | 🔴 致命 |

---

## Sprint 2 目标

> **打通 "AI分析 → 智能决策 → 执行剪辑 → 反馈进化" 完整闭环**

---

## 阶段1：下游消费升级（打通前序成果，2-3天）

### 1.1 AutoClip 接入真实AI引擎

**文件**：`app/modules/lego/ai_clip_flow.py`

**当前**：Step 1 只调用 `vp.get_info()` 和 `extract_frames()`，没有AI分析。

**目标**：Step 1 接入 `DramaUnderstandingEngine.extract_highlights()` + `ViralDetector.analyze()`

```python
# 改造 _start_clip_flow() 的 Step 1 (i==0)
if i == 0:
    ac = settings["autoclip"]
    # 1. 调用剧集理解引擎
    from .drama_understanding_engine import DramaUnderstandingEngine
    engine = DramaUnderstandingEngine(
        whisper_model="base", ollama_model="qwen2.5", use_local_ai=True
    )
    drama = engine.analyze_video(current_output)
    
    # 2. ABCD融合提取高光
    highlights = engine.extract_highlights(
        drama, target_duration=ac.duration, platform=ac.platform
    )
    
    # 3. 病毒基因检测
    from app.core.ai.viral_detector import ViralDetector
    detector = ViralDetector()
    viral_result = detector.analyze(drama, use_llm=True)
    
    # 4. 生成剪辑策略（含BGM/转场/字幕推荐）
    strategy = engine.generate_editing_strategy(
        drama, target_platform=ac.platform, video_style=ac.category
    )
    
    # 5. 回填 progress 信息
    results["autoclip"] = current_output
    results["highlights"] = highlights
    results["viral"] = viral_result
    results["strategy"] = strategy
```

### 1.2 SmartEditingEngine 向量化升级

**文件**：`app/modules/lego/smart_editing_engine.py`

**改进点**：

1. **转场选择** → 用8维情绪向量余弦距离替代 `EmotionalTone` 枚举匹配
   ```python
   def _select_transition_by_vector(
       self, from_vec: np.ndarray, to_vec: np.ndarray
   ) -> TransitionType:
       """基于情绪向量余弦距离选择转场"""
       cos_dist = 1 - np.dot(from_vec, to_vec) / (
           np.linalg.norm(from_vec) * np.linalg.norm(to_vec) + 1e-8
       )
       if cos_dist > 0.6:  # 情绪剧变
           return TransitionType.FLASH
       elif cos_dist > 0.3:  # 情绪变化
           return TransitionType.FADE
       else:
           return TransitionType.CUT
   ```

2. **转场选择** → 集成情绪历程的 `editing_value`
   ```python
   def _select_transition_adaptive(
       self, journey_point: Dict, from_vec, to_vec
   ) -> TransitionType:
       """综合情绪向量+历程转折点选择转场"""
       # journey_point 包含 phase, transition_type, editing_value
       ...
   ```

3. **音乐节拍分析** → 用 `librosa` 真实分析替代硬编码
   ```python
   def _analyze_music_beats(self, audio_path: str) -> List[float]:
       """用librosa真实分析音乐节拍"""
       import librosa
       y, sr = librosa.load(audio_path, sr=22050)
       tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
       beat_times = librosa.frames_to_time(beat_frames, sr=sr)
       return beat_times.tolist()
   ```

4. **`generate_editing_report()`** → 新增情绪旅程可视化数据

### 1.3 AIEditor 去模拟化

**文件**：`app/modules/lego/video_editor/ai_integration.py`

**改进**：`_run_analysis()` 从 `random.randint()` 模拟改为调用真实引擎
```python
def _run_analysis(self) -> Dict[str, Any]:
    from ..drama_understanding_engine import DramaUnderstandingEngine
    from app.core.ai.viral_detector import ViralDetector
    
    # 获取当前时间线中的视频
    ...
    
    engine = DramaUnderstandingEngine(...)
    drama = engine.analyze_video(video_path)
    highlights = engine.extract_highlights(drama, ...)
    
    detector = ViralDetector()
    viral = detector.analyze(drama, use_llm=True)
    
    return {
        'success': True,
        'highlights': [h.__dict__ for h in highlights],
        'viral_score': viral.composite_score,
        'emotion_journey': drama.emotion_journey,
        ...
    }
```

---

## 阶段2：MemoryBank 进化Agent系统（3-4天）

### 2.1 新建 MemoryBank 核心模块

**文件**：`app/core/ai/memory_bank.py`（新建）

**设计**：

```python
@dataclass
class EditingDecision:
    """单次剪辑决策记录"""
    decision_id: str
    timestamp: float
    video_hash: str           # 源视频hash
    genre: str                # 品类
    
    # ABCD评分
    a_plot_score: float
    b_emotion_score: float
    c_scene_score: float
    d_viral_score: float
    
    # 决策参数
    highlight_segments: List[Tuple[float, float]]
    transition_choices: List[str]
    bgm_choice: str
    pacing: str
    
    # 情绪特征
    emotion_arc: Dict         # 情绪弧线摘要
    journey_phases: List[str]
    peak_positions: List[float]
    
    # 结果反馈
    actual_completion_3s: Optional[float]  # 实际3秒完播率
    actual_completion_full: Optional[float]
    actual_like_rate: Optional[float]
    actual_share_rate: Optional[float]
    
    # ReviewAgent评分
    predicted_score: float
    review_passed: bool


class MemoryBank:
    """
    决策记忆库 - Agent进化核心
    
    功能：
    1. 记录每次剪辑决策及结果
    2. 查询相似品类的历史最佳决策
    3. 统计转场/BGM/节奏的品类级效果
    4. 生成进化参数建议
    """
    
    def record_decision(self, decision: EditingDecision) -> str
    def query_similar(self, genre: str, emotion_arc: Dict, k: int = 5) -> List[EditingDecision]
    def get_genre_stats(self, genre: str) -> Dict[str, Any]
    def get_transition_effectiveness(self, genre: str, from_emotion, to_emotion) -> Dict[str, float]
    def get_bgm_effectiveness(self, genre: str, emotion_phase: str) -> Dict[str, float]
    def generate_evolution_hints(self, genre: str) -> Dict[str, Any]
    def export_knowledge(self) -> Dict
    def import_knowledge(self, data: Dict)
```

### 2.2 AgentWorkflow 集成 MemoryBank

**文件**：`app/modules/lego/agent_workflow.py`

**改进**：PlanAgent 决策前查询 MemoryBank，ReviewAgent 完成后写入 MemoryBank

```python
class PlanAgent:
    def analyze(self, ...):
        # 查询历史最佳实践
        hints = memory_bank.generate_evolution_hints(genre)
        # 用进化提示调整ABCD权重
        if hints.get("emotion_heavy"):
            weights = {"A": 0.20, "B": 0.45, "C": 0.15, "D": 0.20}
        ...
```

### 2.3 Thompson Sampling 转场选择器

**文件**：`app/core/ai/transition_selector.py`（新建）

**设计**：

```python
class ThompsonTransitionSelector:
    """
    Thompson采样转场选择器
    
    对每个 (genre, from_emotion_dims, to_emotion_dims) 组合，
    用Beta分布建模各转场的成功率，通过Thompson采样平衡探索与利用
    """
    
    def __init__(self):
        # {key: {transition: (alpha, beta)}}
        self._beta_params: Dict[str, Dict[str, Tuple[float, float]]] = {}
    
    def select(self, genre: str, from_vec: np.ndarray, to_vec: np.ndarray) -> str:
        """Thompson采样选择最佳转场"""
        ...
    
    def update(self, genre: str, from_vec, to_vec, transition: str, reward: float):
        """根据实际完播率反馈更新Beta分布参数"""
        ...
```

---

## 阶段3：BGM情绪实时匹配（1-2天）

### 3.1 BGM情绪分析器

**文件**：`app/core/ai/bgm_emotion_matcher.py`（新建）

**设计**：

```python
class BGMEmotionMatcher:
    """
    BGM情绪匹配器
    
    1. 分析BGM库中每首曲目的情绪曲线（用librosa + 8维向量映射）
    2. 构建BGM情绪指纹库
    3. 对目标视频的情绪历程，匹配最佳BGM
    """
    
    def build_library(self, bgm_dir: str) -> Dict[str, np.ndarray]
    def analyze_bgm(self, bgm_path: str) -> Dict[str, Any]
    def match(self, emotion_journey: List[Dict], genre: str, top_k: int = 3) -> List[Tuple[str, float]]
    def match_phase(self, phase_emotion: Dict, genre: str) -> List[Tuple[str, float]]
```

### 3.2 连线 generate_editing_strategy

**文件**：`app/modules/lego/drama_understanding_engine.py`

将硬编码的 `bgm_style_map` 替换为 `BGMEmotionMatcher.match()` 调用。

---

## 执行优先级

| 序号 | 任务 | 预估工时 | 依赖 | 价值 |
|------|------|----------|------|------|
| 1 | AutoClip接入真实AI引擎 | 1天 | 无 | 🔴 关键 |
| 2 | SmartEditingEngine向量化升级 | 1.5天 | 无 | 🔴 关键 |
| 3 | AIEditor去模拟化 | 0.5天 | 1 | 🟡 重要 |
| 4 | MemoryBank核心模块 | 2天 | 无 | 🔴 关键 |
| 5 | Thompson采样转场选择器 | 1天 | 4 | 🟡 重要 |
| 6 | AgentWorkflow集成MemoryBank | 1天 | 4, 5 | 🔴 关键 |
| 7 | BGM情绪匹配器 | 1.5天 | 无 | 🟢 增强 |
| 8 | generate_editing_strategy升级 | 0.5天 | 7 | 🟢 增强 |

**建议执行顺序**：1→3→2（打通管线）→ 4→5→6（进化系统）→ 7→8（增强体验）

---

## 预期成果

执行完Sprint 2后，系统将达到：

- ✅ `ai_clip_flow` Step 1 产出真实的AI高光片段（非假帧提取）
- ✅ 转场选择从8个硬编码规则 → Thompson采样 + 向量余弦距离
- ✅ BGM从 "用户手动选" → 情绪曲线自动匹配
- ✅ `ai_integration.py` 从随机数模拟 → 真实引擎调用
- ✅ 剪辑决策可记录、可查询、可进化
- ✅ Agent系统具备"从经验中学习"能力
- 📊 整体AI能力覆盖从当前的 ~45% → ~75%

---

## 下一步预告 Sprint 3

- 视觉情绪分析（OpenCV面部/动作强度）
- 剪辑效果A/B测试框架
- 跨视频知识迁移
- 用户偏好个性化学习
