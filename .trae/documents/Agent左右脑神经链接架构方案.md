# Agent 左右脑神经链接架构方案

## Context

用户要求把已做好的 Agent 功能按"人的大脑左右脑"分工，并用神经网络引擎建立链接，强化 Agent 性能和思考逻辑。

### 现状摸底（调研结论）

| 组件 | 现状 | 可复用性 |
|------|------|---------|
| [neural_engine.py](file:///D:/拾光剪影/app/core/neural_engine.py) | ONNX/Torch 推理引擎，**非**神经网络链接引擎 | ❌ 不可直接复用为"突触" |
| [memory_store.py](file:///D:/拾光剪影/app/core/memory_store.py) | 有 record/query/learn_from_feedback，记忆条目含 score/tags | ✅ 可扩展存"突触权重" |
| [EventBus](file:///D:/拾光剪影/app/modules/lego/core.py) | 已传递 50+ 事件类型 | ✅ 可作"神经递质" |
| [capability_handlers.py](file:///D:/拾光剪影/app/core/capability_handlers.py) | 23 个 capability 已注册 | ✅ 可作"神经元" |
| [agent_feedback_bridge.py](file:///D:/拾光剪影/app/core/agent_feedback_bridge.py) | 已订阅 PUBLISH_RESULT/WORKFLOW_COMPLETED | ✅ 可触发学习 |

### 23 个 capability 左右脑分类

| 归属 | 数量 | capability_id |
|------|------|---------------|
| **右脑（创意）** | 7 | model.chat, model.chat_with_fallback, pipeline.generate, pipeline.generate_script, ext.run_extension, ext.run_skill, account.optimize_strategy |
| **左脑（逻辑）** | 11 | editor.split_clip, editor.apply_filter, editor.add_transition, editor.get_timeline_context, workflow.start, workflow.submit_batch, account.collect_data, account.publish, pipeline.preview_validate, pipeline.regenerate_clip, pipeline.execute_editing |
| **胼胝体（混合）** | 5 | pipeline.route, pipeline.score, pipeline.run_full, model.list_models, ext.list_tools |

## 设计思路

新建一个 `AgentBrain` 模块作为"左右脑神经链接层"，**不重写**任何现有逻辑，只在能力调度和管线完成时**追加**激活与学习调用。

### 类比映射

| 生物大脑概念 | 项目实现 |
|-------------|---------|
| 神经元 | capability_id（23 个已注册能力） |
| 突触 | Synapse 对象（pre→post + weight + last_activated） |
| 神经递质 | EventBus 信号 + MemoryStore 记忆条目 |
| 激活函数 | top-K 相似度 + 阈值 0.5 + 时间衰减 |
| 长期记忆 | MemoryStore 的 JSONL 持久化 |
| 左脑 | 逻辑类 capability 集合 |
| 右脑 | 创意类 capability 集合 |
| 胼胝体 | 混合类 capability + 协同调度方法 |
| 学习 | Hebbian 规则：同时激活的神经元突触权重 +Δ，失败 -Δ |

## 实施步骤（P0+P1，最小侵入）

### 步骤1：新建 `app/core/agent_brain.py`（P0 核心）

**新增类**：

```python
class BrainHemisphere(Enum):
    LEFT = "left"           # 逻辑
    RIGHT = "right"         # 创意
    CORPUS_CALLOSUM = "cc"  # 胼胝体（混合）

@dataclass
class Neuron:
    neuron_id: str          # = capability_id
    hemisphere: BrainHemisphere
    label: str              # 中文名
    activation: float = 0.0 # 当前激活值 [0,1]
    last_fired: float = 0.0 # 时间戳

@dataclass
class Synapse:
    pre: str                # 前神经元 id
    post: str               # 后神经元 id
    weight: float = 0.5     # 突触权重 [0,1]
    fire_count: int = 0     # 共同激活次数

class AgentBrain:
    """Agent 左右脑神经链接引擎（单例）"""
    _instance = None

    def __init__(self):
        self._neurons: Dict[str, Neuron] = {}
        self._synapses: Dict[Tuple[str,str], Synapse] = {}
        self._event_bus = None
        self._memory = None
        self._init_neuron_taxonomy()  # 注册 23 个神经元

    # ─── 神经元注册 ───
    def _init_neuron_taxonomy(self):
        """注册 23 个 capability 为神经元，标记左右脑归属"""
        taxonomy = [
            ("model.chat", BrainHemisphere.RIGHT, "AI 对话"),
            ("pipeline.generate", BrainHemisphere.RIGHT, "AI 视频生成"),
            ("pipeline.generate_script", BrainHemisphere.RIGHT, "剪辑脚本生成"),
            ("editor.split_clip", BrainHemisphere.LEFT, "片段切分"),
            ("pipeline.preview_validate", BrainHemisphere.LEFT, "预览校验"),
            ("pipeline.score", BrainHemisphere.CORPUS_CALLOSUM, "五维打分"),
            ("pipeline.run_full", BrainHemisphere.CORPUS_CALLOSUM, "全链路执行"),
            # ... 共 23 个
        ]
        for nid, hemi, label in taxonomy:
            self._neurons[nid] = Neuron(nid, hemi, label)

    # ─── 激活与扩散 ───
    def activate(self, neuron_id: str, context: Dict, strength: float = 1.0):
        """激活一个神经元，沿突触扩散到相关神经元（联想调用）"""
        if neuron_id not in self._neurons:
            return []
        self._neurons[neuron_id].activation = max(1.0, strength)
        self._neurons[neuron_id].last_fired = time.time()
        # 找出所有 post 突触，按权重排序
        fired = [neuron_id]
        candidates = [(s.post, s.weight) for s in self._synapses.values()
                      if s.pre == neuron_id and s.weight >= 0.5]
        candidates.sort(key=lambda x: -x[1])
        for post_id, w in candidates[:3]:  # top-3 扩散
            self._neurons[post_id].activation = w * strength * 0.7  # 衰减
            fired.append(post_id)
        self._persist_activation(fired, context)
        return fired

    # ─── 学习（Hebbian） ───
    def reinforce_path(self, path: List[str], success: bool, delta: float = 0.05):
        """强化一条链路上的突触（pipeline 完成时调用）"""
        for pre, post in zip(path[:-1], path[1:]):
            key = (pre, post)
            if key not in self._synapses:
                self._synapses[key] = Synapse(pre, post, 0.5)
            syn = self._synapses[key]
            if success:
                syn.weight = min(1.0, syn.weight + delta)
            else:
                syn.weight = max(0.0, syn.weight - delta)
            syn.fire_count += 1
        self._persist_synapses()

    def learn_from_feedback(self, feedback: Dict):
        """反馈桥调用：根据反馈调整权重"""
        issue_type = feedback.get("type", "")
        related = feedback.get("related_capabilities", [])
        if issue_type == "quality":
            self.reinforce_path(related, success=False, delta=0.03)
        elif issue_type == "success":
            self.reinforce_path(related, success=True, delta=0.04)

    # ─── 左右脑协同 ───
    def right_brain_think(self, task: str, context: Dict) -> List[str]:
        """右脑思考：根据任务激活创意类神经元，返回推荐 capability 序列"""
        # 基于 task 关键词匹配神经元 label
        candidates = [n for n in self._neurons.values()
                      if n.hemisphere == BrainHemisphere.RIGHT]
        scored = [(n, self._match_score(task, n.label)) for n in candidates]
        scored.sort(key=lambda x: -x[1])
        return [n.neuron_id for n, _ in scored[:3] if _[1] > 0.3]

    def left_brain_think(self, task: str, context: Dict) -> List[str]:
        """左脑思考：根据任务激活逻辑类神经元"""
        candidates = [n for n in self._neurons.values()
                      if n.hemisphere == BrainHemisphere.LEFT]
        scored = [(n, self._match_score(task, n.label)) for n in candidates]
        scored.sort(key=lambda x: -x[1])
        return [n.neuron_id for n, _ in scored[:3] if _[1] > 0.3]

    def correlate(self, task: str, context: Dict) -> Dict:
        """胼胝体协同：左右脑联合思考，返回完整执行计划"""
        right = self.right_brain_think(task, context)
        left = self.left_brain_think(task, context)
        return {
            "right_brain_plan": right,
            "left_brain_plan": left,
            "correlation_strength": self._calc_correlation(right, left),
        }

    # ─── 持久化 ───
    def _persist_synapses(self):
        """突触权重持久化到 MemoryStore（type=brain_synapse）"""
        try:
            from app.core.memory_store import memory_store
            for (pre, post), syn in self._synapses.items():
                memory_store.record(
                    type="brain_synapse",
                    content=f"{pre}->{post}",
                    tags=[pre, post, "synapse"],
                    score=syn.weight,
                    metadata={"fire_count": syn.fire_count, "weight": syn.weight}
                )
        except Exception as e:
            logger.debug(f"[AgentBrain] 突触持久化失败: {e}")

    def _load_synapses(self):
        """启动时从 MemoryStore 加载历史突触权重"""
        try:
            from app.core.memory_store import memory_store
            entries = memory_store.query(tags=["synapse"], limit=200)
            for e in entries:
                pre, post = e.content.split("->")
                key = (pre, post)
                self._synapses[key] = Synapse(
                    pre, post,
                    weight=e.metadata.get("weight", 0.5),
                    fire_count=e.metadata.get("fire_count", 0)
                )
        except Exception as e:
            logger.debug(f"[AgentBrain] 突触加载失败: {e}")

    # ─── 工具方法 ───
    def _match_score(self, task: str, label: str) -> float:
        """简单关键词匹配（避免引入 embedding 依赖）"""
        task_lower = task.lower()
        for kw in label:
            if kw in task_lower:
                return 0.8
        return 0.2

    def get_brain_status(self) -> Dict:
        """获取大脑状态（供 UI 显示）"""
        return {
            "total_neurons": len(self._neurons),
            "total_synapses": len(self._synapses),
            "right_brain_count": sum(1 for n in self._neurons.values()
                                     if n.hemisphere == BrainHemisphere.RIGHT),
            "left_brain_count": sum(1 for n in self._neurons.values()
                                    if n.hemisphere == BrainHemisphere.LEFT),
            "active_neurons": [n.neuron_id for n in self._neurons.values()
                               if n.activation > 0.3],
            "top_synapses": sorted(
                [{"pre": s.pre, "post": s.post, "weight": s.weight}
                 for s in self._synapses.values()],
                key=lambda x: -x["weight"]
            )[:5],
        }

# 单例
agent_brain = AgentBrain()
```

### 步骤2：在 capability_handlers.py 末尾追加神经元自动注册（P0）

**位置**：[capability_handlers.py](file:///D:/拾光剪影/app/core/capability_handlers.py) `register_builtin_handlers` 函数末尾

```python
def register_builtin_handlers(dispatcher, editor_module_ref=None):
    # ... 既有 23 个 handler 注册 ...

    # ── 新增：让大脑感知所有已注册 capability ──
    try:
        from app.core.agent_brain import agent_brain
        agent_brain.sync_from_dispatcher(dispatcher)
    except Exception as e:
        logger.debug(f"[AgentBrain] 同步 dispatcher 失败: {e}")
```

### 步骤3：在 agent_pipeline_orchestrator.py 完成阶段追加学习（P0）

**位置**：[agent_pipeline_orchestrator.py](file:///D:/拾光剪影/app/core/agent_pipeline_orchestrator.py) `_emit_done` 方法末尾

```python
def _emit_done(self, session):
    # ... 既有逻辑 ...

    # ── 新增：强化链路突触（Hebbian 学习）──
    try:
        from app.core.agent_brain import agent_brain
        path = ["pipeline.route"]
        if session.route and session.route.get("route") == "generation":
            path.extend(["pipeline.generate", "pipeline.preview_validate",
                         "pipeline.score", "pipeline.generate_script",
                         "pipeline.execute_editing"])
        else:
            path.extend(["pipeline.preview_validate", "pipeline.score",
                         "pipeline.generate_script", "pipeline.execute_editing"])
        agent_brain.reinforce_path(path, success=session.success)
    except Exception as e:
        logger.debug(f"[AgentBrain] 链路强化失败: {e}")
```

### 步骤4：在 agent_feedback_bridge.py 反馈处理时触发学习（P1）

**位置**：[agent_feedback_bridge.py](file:///D:/拾光剪影/app/core/agent_feedback_bridge.py) 反馈处理方法末尾

```python
# ── 新增：反馈触发学习 ──
try:
    from app.core.agent_brain import agent_brain
    agent_brain.learn_from_feedback({
        "type": feedback.type,
        "related_capabilities": feedback.related_capabilities,
        "severity": feedback.severity,
    })
except Exception as e:
    logger.debug(f"[AgentBrain] 反馈学习失败: {e}")
```

### 步骤5：在 Agent 面板新增"🧠 大脑状态"小标签（P2 可选）

**位置**：[editor_module.py](file:///D:/拾光剪影/app/modules/lego/editor_module.py) `_create_edit_agent_panel` 配置卡内

新增一个 `QLabel` 显示：
```
🧠 神经元:23 | 突触:15 | 右脑:7 | 左脑:11 | 活跃:3
```

启动时 + 每次 `pipeline_done` 后刷新一次。

## 文件清单

| 文件 | 操作 | 改动量 |
|------|------|-------|
| `app/core/agent_brain.py` | **新建** | ~250 行 |
| `app/core/capability_handlers.py` | 追加 5 行（末尾同步调用） | 5 行 |
| `app/core/agent_pipeline_orchestrator.py` | 追加 12 行（_emit_done 末尾强化） | 12 行 |
| `app/core/agent_feedback_bridge.py` | 追加 8 行（反馈处理时学习） | 8 行 |
| `app/modules/lego/editor_module.py` | 追加 ~25 行（UI 状态标签） | 25 行 |

**总计**：1 个新文件 + 4 个文件小幅追加，约 300 行新代码，**不修改任何既有方法签名**。

## 风险与缓解

| 风险 | 缓解 |
|------|------|
| agent_brain 初始化失败导致 pipeline 崩溃 | 所有调用点都用 `try/except` 包裹 + `logger.debug`，失败静默降级 |
| 突触持久化导致 MemoryStore 膨胀 | 限制 200 条上限 + 老旧记忆自动压缩（复用 MemoryStore 既有的 compress 机制） |
| 学习权重漂移导致联想调用失效 | weight 限制在 [0,1]，delta=0.05 小步长，失败 -Δ，成功 +Δ |
| 冻结区告警 | 完全不触碰冻结区文件（frozen_zones.json 锁定的是 playback/exit-media/clip-transform 等，与本方案无关） |
| 影响现有 capability_dispatcher.invoke 性能 | 大脑只在 invoke 后异步记录激活，不阻塞调用本身 |

## 验证方案

### 静态验证
```
python -m py_compile app/core/agent_brain.py
python -m py_compile app/core/capability_handlers.py
python -m py_compile app/core/agent_pipeline_orchestrator.py
python -m py_compile app/core/agent_feedback_bridge.py
python -m py_compile app/modules/lego/editor_module.py
python scripts/frozen_zone_guard.py
```

### 单元验证
```python
# 验证神经元注册
from app.core.agent_brain import agent_brain, BrainHemisphere
assert len(agent_brain._neurons) == 23
assert agent_brain._neurons["pipeline.generate"].hemisphere == BrainHemisphere.RIGHT
assert agent_brain._neurons["editor.split_clip"].hemisphere == BrainHemisphere.LEFT

# 验证激活扩散
fired = agent_brain.activate("pipeline.generate", {"task": "生成视频"})
assert "pipeline.generate" in fired

# 验证学习
agent_brain.reinforce_path(
    ["pipeline.route", "pipeline.generate", "pipeline.score"],
    success=True
)
assert agent_brain._synapses[("pipeline.route","pipeline.generate")].weight > 0.5

# 验证左右脑协同
plan = agent_brain.correlate("剪辑一个海边日落视频", {})
assert "right_brain_plan" in plan
assert "left_brain_plan" in plan
```

### 端到端验证
```
python -m app.main_qt6
```
1. 启动应用，检查 Agent 面板显示"🧠 神经元:23"状态
2. 执行一次全链路（输入创意 → 启动）
3. 完成后查看 MemoryStore 是否新增 `type=brain_synapse` 记录
4. 重启应用，检查突触是否从 MemoryStore 加载恢复
5. 再次执行全链路，检查联想调用是否推荐了相关 capability

### 行为回归
- 不接入大脑也能跑（try/except 静默降级）
- 现有 23 个 capability 调用路径完全不变
- pipeline.run_full 执行结果与改造前一致

## 交付检查清单

1. ✅ 新建 1 个文件 `app/core/agent_brain.py`，不调整目录结构
2. ✅ 4 个既有文件只追加，不修改既有方法签名
3. ✅ 所有调用点 try/except 包裹，失败静默降级
4. ✅ 突触权重持久化复用 MemoryStore，不新建存储
5. ✅ 不触碰冻结区
6. ✅ py_compile + frozen_zone_guard 通过
7. ✅ 端到端验证：启动 + 全链路执行 + 重启加载突触
