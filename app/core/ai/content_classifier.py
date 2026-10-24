"""
通用内容类型识别器 (ContentClassifier)
========================================

设计目标：
- 不依赖人工规则，通过通用特征提取实现内容类型识别
- 支持 5 样本即可注册新剧种（Few-Shot Meta-Learning）
- 与 ABCD 融合矩阵无缝集成，自动映射到最佳融合权重

核心能力：
1. 通用特征提取（8维：情绪方差/对话密度/场景切换频率/角色数/冲突密度/反转次数/爽点频率/甜度）
2. 元学习分类（余弦相似度 + 原型向量匹配）
3. 自适应策略匹配（类型 → ABCD 权重映射）
4. 新类型自动注册（5 样本即可激活）

参考：
- 方案第12章「分层通用框架」
- drama_understanding_engine.py 的 GENRE_WEIGHTS
"""

import json
import os
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from pathlib import Path

import numpy as np

logger = logging.getLogger("AI短剧编辑器.content_classifier")


# ═══════════════════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════════════════

@dataclass
class GenrePrototype:
    """剧种原型向量"""
    name: str                          # 剧种名称
    feature_vector: List[float]        # 8维特征向量
    sample_count: int                  # 样本数
    abcd_weights: Dict[str, float]     # ABCD融合权重
    confidence: float = 1.0            # 原型可信度

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "feature_vector": self.feature_vector,
            "sample_count": self.sample_count,
            "abcd_weights": self.abcd_weights,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GenrePrototype":
        return cls(
            name=data["name"],
            feature_vector=data["feature_vector"],
            sample_count=data["sample_count"],
            abcd_weights=data["abcd_weights"],
            confidence=data.get("confidence", 1.0),
        )


@dataclass
class ClassificationResult:
    """分类结果"""
    genre: str                         # 判定剧种
    confidence: float                  # 置信度 0-1
    top_candidates: List[Tuple[str, float]]  # 候选排名
    feature_vector: List[float]        # 提取的特征向量
    is_new_type: bool = False          # 是否疑似新类型


# ═══════════════════════════════════════════════════════════════
# 内置剧种原型库（8维特征）
# 特征维度说明：
#   [0] 情绪方差        — 情感波动幅度
#   [1] 对话密度        — 单位时间文本量
#   [2] 场景切换频率    — 镜头变化速率
#   [3] 角色数量        — 归一化角色数
#   [4] 冲突密度        — 冲突类台词占比
#   [5] 反转频率        — 反转事件密度
#   [6] 爽点频率        — 爽点/高能台词密度
#   [7] 甜度指数        — 甜蜜/浪漫内容占比
# ═══════════════════════════════════════════════════════════════

BUILTIN_PROTOTYPES: Dict[str, GenrePrototype] = {
    "甜宠": GenrePrototype(
        name="甜宠",
        feature_vector=[0.30, 0.55, 0.35, 0.30, 0.15, 0.10, 0.40, 0.85],
        sample_count=10,
        abcd_weights={"A": 0.20, "B": 0.45, "C": 0.20, "D": 0.15},
    ),
    "逆袭": GenrePrototype(
        name="逆袭",
        feature_vector=[0.65, 0.40, 0.60, 0.35, 0.75, 0.70, 0.80, 0.10],
        sample_count=10,
        abcd_weights={"A": 0.35, "B": 0.25, "C": 0.15, "D": 0.25},
    ),
    "虐恋": GenrePrototype(
        name="虐恋",
        feature_vector=[0.80, 0.45, 0.40, 0.30, 0.50, 0.55, 0.20, 0.60],
        sample_count=10,
        abcd_weights={"A": 0.25, "B": 0.40, "C": 0.25, "D": 0.10},
    ),
    "悬疑": GenrePrototype(
        name="悬疑",
        feature_vector=[0.55, 0.35, 0.70, 0.40, 0.35, 0.75, 0.20, 0.05],
        sample_count=10,
        abcd_weights={"A": 0.30, "B": 0.15, "C": 0.35, "D": 0.20},
    ),
    "爽文": GenrePrototype(
        name="爽文",
        feature_vector=[0.70, 0.50, 0.65, 0.25, 0.80, 0.60, 0.90, 0.15],
        sample_count=10,
        abcd_weights={"A": 0.25, "B": 0.30, "C": 0.15, "D": 0.30},
    ),
    "家庭伦理": GenrePrototype(
        name="家庭伦理",
        feature_vector=[0.55, 0.60, 0.30, 0.50, 0.60, 0.30, 0.10, 0.25],
        sample_count=10,
        abcd_weights={"A": 0.30, "B": 0.35, "C": 0.15, "D": 0.20},
    ),
    "古装": GenrePrototype(
        name="古装",
        feature_vector=[0.40, 0.35, 0.50, 0.45, 0.50, 0.40, 0.30, 0.30],
        sample_count=10,
        abcd_weights={"A": 0.25, "B": 0.25, "C": 0.30, "D": 0.20},
    ),
    "都市": GenrePrototype(
        name="都市",
        feature_vector=[0.45, 0.55, 0.45, 0.35, 0.45, 0.35, 0.25, 0.40],
        sample_count=10,
        abcd_weights={"A": 0.25, "B": 0.30, "C": 0.20, "D": 0.25},
    ),
}


# ═══════════════════════════════════════════════════════════════
# 8维通用特征提取器
# ═══════════════════════════════════════════════════════════════

class UniversalFeatureExtractor:
    """
    通用特征提取器：从对话列表提取 8 维剧种无关特征。

    不依赖剧种标签，适用于任意类型的内容。
    """

    @staticmethod
    def extract(dialogues: List, scenes: List = None,
                plot_points: List = None,
                total_duration: float = 0) -> List[float]:
        """
        提取 8 维特征向量。

        Args:
            dialogues: 对话片段列表（需有 .text, .emotion, .start_time, .end_time）
            scenes: 场景列表（可选，用于场景切换频率）
            plot_points: 情节点列表（可选，用于反转频率）
            total_duration: 视频总时长

        Returns:
            8维浮点特征向量
        """
        if not dialogues:
            return [0.0] * 8

        texts = [d.text for d in dialogues if hasattr(d, 'text') and d.text]
        total_dur = total_duration or (dialogues[-1].end_time if dialogues else 1)

        # [0] 情绪方差：情感波动幅度
        emotion_values = []
        for d in dialogues:
            if hasattr(d, 'emotion') and d.emotion is not None:
                em = d.emotion
                if hasattr(em, 'value'):
                    emotion_values.append({
                        "开心": 0.8, "悲伤": -0.8, "愤怒": -0.6,
                        "紧张": -0.4, "浪漫": 0.9, "悬疑": -0.3,
                        "激动": 1.0, "温馨": 0.7
                    }.get(em.value, 0.0))
        emotion_var = np.var(emotion_values) if len(emotion_values) > 1 else 0.0
        f0 = min(1.0, emotion_var * 3.0)

        # [1] 对话密度：单位时间文本量
        total_chars = sum(len(t) for t in texts)
        dialogue_density = total_chars / max(total_dur, 1)
        f1 = min(1.0, dialogue_density / 30.0)

        # [2] 场景切换频率
        if scenes and total_dur > 0:
            scene_rate = len(scenes) / (total_dur / 60.0)
            f2 = min(1.0, scene_rate / 15.0)
        else:
            f2 = 0.3  # 默认中频

        # [3] 归一化角色数量
        if hasattr(dialogues[0], 'speaker'):
            speakers = set(d.speaker for d in dialogues
                          if hasattr(d, 'speaker') and d.speaker != "未知")
            f3 = min(1.0, len(speakers) / 8.0)
        else:
            f3 = 0.25

        # [4] 冲突密度
        conflict_words = {"打", "杀", "抢", "夺", "离婚", "出轨", "背叛", "怒", "滚",
                          "死", "跪", "崩溃", "疯", "逼", "威胁", "陷害", "混蛋", "该死"}
        conflict_count = sum(1 for t in texts if any(w in t for w in conflict_words))
        f4 = min(1.0, conflict_count / max(len(texts), 1) * 4.0)

        # [5] 反转频率
        if plot_points:
            twists = sum(1 for pp in plot_points
                        if hasattr(pp, 'plot_type') and str(pp.plot_type) in
                        ("PlotPointType.TWIST", "TWIST", "反转"))
            f5 = min(1.0, twists / max(total_dur / 60, 1) * 2.0)
        else:
            reversal_words = {"突然", "没想到", "原来", "居然", "竟然", "真相", "反转",
                              "其实", "背后", "真实"}
            reversal_count = sum(1 for t in texts if any(w in t for w in reversal_words))
            f5 = min(1.0, reversal_count / max(len(texts), 1) * 3.0)

        # [6] 爽点频率
        satisfaction_words = {"赢了", "成功", "厉害", "牛逼", "打脸", "碾压",
                              "跪下", "服了", "太强", "无敌"}
        satisfaction_count = sum(1 for t in texts if any(w in t for w in satisfaction_words))
        f6 = min(1.0, satisfaction_count / max(len(texts), 1) * 3.5)

        # [7] 甜度指数
        sweetness_words = {"爱你", "喜欢", "心动", "甜蜜", "宝贝", "老婆", "老公",
                           "亲爱的", "抱抱", "想你", "吻", "温柔", "浪漫"}
        sweetness_count = sum(1 for t in texts if any(w in t for w in sweetness_words))
        f7 = min(1.0, sweetness_count / max(len(texts), 1) * 3.0)

        features = [f0, f1, f2, f3, f4, f5, f6, f7]
        return [round(f, 4) for f in features]

    @staticmethod
    def cosine_similarity(a: List[float], b: List[float]) -> float:
        """计算余弦相似度"""
        a_arr = np.array(a)
        b_arr = np.array(b)
        dot = np.dot(a_arr, b_arr)
        norm_a = np.linalg.norm(a_arr)
        norm_b = np.linalg.norm(b_arr)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(dot / (norm_a * norm_b))


# ═══════════════════════════════════════════════════════════════
# 内容分类器主类
# ═══════════════════════════════════════════════════════════════

class ContentClassifier:
    """
    通用内容类型分类器。

    工作流程：
    1. 提取 8 维通用特征
    2. 与所有已注册原型做余弦相似度匹配
    3. 返回最佳匹配 + 置信度
    4. 如果最高相似度 < 阈值 → 标记为新类型候选

    支持 5 样本注册新类型：
        classifier.register_genre("电竞", samples=[...5个特征向量...], weights={...})
    """

    # 分类置信度阈值
    MIN_CONFIDENCE = 0.55       # 低于此值视为未分类
    NEW_TYPE_THRESHOLD = 0.40   # 低于此值标记为疑似新类型
    MIN_SAMPLES_FOR_REGISTER = 5  # 注册新类型最少样本数

    def __init__(self, prototypes_dir: Optional[str] = None):
        """
        Args:
            prototypes_dir: 自定义原型存储目录，None 则使用默认路径
        """
        self._prototypes: Dict[str, GenrePrototype] = dict(BUILTIN_PROTOTYPES)
        self._extractor = UniversalFeatureExtractor()

        # 持久化路径
        if prototypes_dir:
            self._storage_dir = Path(prototypes_dir)
        else:
            self._storage_dir = Path(__file__).resolve().parent.parent.parent / "data"
        self._storage_file = self._storage_dir / "genre_prototypes.json"

        # 从磁盘加载自定义原型
        self._load_custom_prototypes()

    @property
    def registered_genres(self) -> List[str]:
        return list(self._prototypes.keys())

    def classify(self, dialogues: List,
                 scenes: List = None,
                 plot_points: List = None,
                 total_duration: float = 0,
                 top_k: int = 3) -> ClassificationResult:
        """
        分类视频内容类型。

        Args:
            dialogues: 对话片段列表
            scenes: 场景列表
            plot_points: 情节点列表
            total_duration: 视频总时长
            top_k: 返回前k个候选

        Returns:
            ClassificationResult
        """
        # Step 1: 提取特征
        features = self._extractor.extract(
            dialogues, scenes, plot_points, total_duration
        )

        # Step 2: 与所有原型计算余弦相似度
        candidates = []
        for name, proto in self._prototypes.items():
            sim = self._extractor.cosine_similarity(features, proto.feature_vector)
            # 引入样本数修正：样本越多置信度越高
            adjusted_sim = sim * min(1.0, proto.sample_count / 20 + 0.5)
            candidates.append((name, adjusted_sim, sim))

        candidates.sort(key=lambda x: x[1], reverse=True)
        top_candidates = [(name, round(raw_sim, 3))
                          for name, adj_sim, raw_sim in candidates[:top_k]]

        # Step 3: 判定结果
        best_match, best_conf, raw_best = candidates[0] if candidates else ("未知", 0.0, 0.0)

        is_new = raw_best < self.NEW_TYPE_THRESHOLD and len(self._prototypes) >= 3

        if best_conf < self.MIN_CONFIDENCE:
            genre = "未知"
            confidence = best_conf
        else:
            genre = best_match
            confidence = best_conf

        logger.info(f"内容分类: {genre} (置信度: {confidence:.2f})")
        if len(top_candidates) > 1:
            logger.info(f"  候选: {top_candidates}")

        return ClassificationResult(
            genre=genre,
            confidence=round(confidence, 3),
            top_candidates=top_candidates,
            feature_vector=features,
            is_new_type=is_new,
        )

    def get_abcd_weights(self, genre: str) -> Dict[str, float]:
        """获取指定剧种的 ABCD 融合权重"""
        proto = self._prototypes.get(genre)
        if proto:
            return dict(proto.abcd_weights)
        # 回退到通用权重
        return {"A": 0.25, "B": 0.30, "C": 0.25, "D": 0.20}

    def register_genre(self, name: str,
                       sample_features: List[List[float]],
                       abcd_weights: Optional[Dict[str, float]] = None,
                       save: bool = True) -> bool:
        """
        注册新剧种（最少 5 个样本）。

        Args:
            name: 剧种名称
            sample_features: 样本特征向量列表（每个 8 维）
            abcd_weights: ABCD 融合权重（None 则使用默认）
            save: 是否持久化到磁盘

        Returns:
            是否注册成功
        """
        if len(sample_features) < self.MIN_SAMPLES_FOR_REGISTER:
            logger.warning(
                f"注册失败：{name} 需要至少 {self.MIN_SAMPLES_FOR_REGISTER} 个样本，"
                f"当前 {len(sample_features)} 个"
            )
            return False

        # 计算原型向量（所有样本的均值）
        samples_arr = np.array(sample_features)
        proto_vector = list(np.mean(samples_arr, axis=0))

        # 验证向量维度
        if len(proto_vector) != 8:
            logger.error(f"特征维度错误：预期 8，实际 {len(proto_vector)}")
            return False

        # 权重处理
        if abcd_weights is None:
            abcd_weights = {"A": 0.25, "B": 0.30, "C": 0.25, "D": 0.20}

        # 创建原型
        prototype = GenrePrototype(
            name=name,
            feature_vector=proto_vector,
            sample_count=len(sample_features),
            abcd_weights=abcd_weights,
            confidence=min(1.0, len(sample_features) / 10.0),
        )

        self._prototypes[name] = prototype

        if save:
            self._save_custom_prototypes()

        logger.info(f"✅ 注册新剧种: {name} (样本数: {len(sample_features)})")
        return True

    def update_prototype(self, name: str,
                         new_features: List[float],
                         weight: float = 0.3) -> bool:
        """
        在线更新已有原型的特征向量（指数移动平均）。

        Args:
            name: 剧种名称
            new_features: 新样本的 8 维特征
            weight: 新样本权重（0-1）

        Returns:
            是否更新成功
        """
        proto = self._prototypes.get(name)
        if proto is None:
            logger.warning(f"更新失败：未找到剧种 {name}")
            return False

        old_vec = np.array(proto.feature_vector)
        new_vec = np.array(new_features)
        updated = old_vec * (1 - weight) + new_vec * weight
        proto.feature_vector = list(updated)
        proto.sample_count += 1
        proto.confidence = min(1.0, proto.sample_count / 20 + 0.5)

        # 保存
        self._save_custom_prototypes()
        logger.info(f"📈 更新原型 {name}: 样本数 → {proto.sample_count}")
        return True

    # ── 持久化 ──

    def _load_custom_prototypes(self):
        """从磁盘加载自定义原型（合并到内置原型之上）"""
        if not self._storage_file.exists():
            return
        try:
            with open(self._storage_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            for item in data:
                proto = GenrePrototype.from_dict(item)
                # 自定义原型覆盖内置同名
                self._prototypes[proto.name] = proto
            logger.info(f"📂 从磁盘加载 {len(data)} 个自定义原型")
        except Exception as e:
            logger.warning(f"加载原型文件失败: {e}")

    def _save_custom_prototypes(self):
        """保存所有原型的副本到磁盘"""
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        try:
            data = [p.to_dict() for p in self._prototypes.values()]
            with open(self._storage_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存原型文件失败: {e}")


# ═══════════════════════════════════════════════════════════════
# 单例 + 便捷函数
# ═══════════════════════════════════════════════════════════════

_classifier_instance: Optional[ContentClassifier] = None


def get_classifier() -> ContentClassifier:
    """获取全局单例分类器"""
    global _classifier_instance
    if _classifier_instance is None:
        _classifier_instance = ContentClassifier()
    return _classifier_instance


def classify_content(dialogues: List,
                     scenes: List = None,
                     plot_points: List = None,
                     total_duration: float = 0) -> ClassificationResult:
    """
    便捷函数：一步完成内容分类。

    用法：
        result = classify_content(drama.dialogues, drama.scenes,
                                   drama.plot_points, drama.total_duration)
        print(result.genre, result.confidence)
    """
    return get_classifier().classify(dialogues, scenes, plot_points, total_duration)


def get_genre_weights(genre: str) -> Dict[str, float]:
    """便捷函数：获取剧种的 ABCD 权重"""
    return get_classifier().get_abcd_weights(genre)


# ═══════════════════════════════════════════════════════════════
# 自测
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 50)
    print("ContentClassifier 自测")
    print("=" * 50)

    # 模拟对话数据
    class MockDialogue:
        def __init__(self, text, emotion_val, start, end, speaker="未知"):
            self.text = text
            self._emotion = type('Emotion', (), {'value': emotion_val})()
            self.emotion = self._emotion
            self.start_time = start
            self.end_time = end
            self.speaker = speaker

    # 模拟甜宠剧对话
    sweet_dialogues = [
        MockDialogue("你好漂亮", "浪漫", 0, 2),
        MockDialogue("我喜欢你很久了", "浪漫", 3, 5),
        MockDialogue("做我女朋友好吗", "激动", 6, 8),
        MockDialogue("我愿意", "开心", 9, 11),
        MockDialogue("我好幸福", "浪漫", 12, 14),
    ]

    # 模拟逆袭剧对话
    revenge_dialogues = [
        MockDialogue("你竟敢背叛我", "愤怒", 0, 2),
        MockDialogue("我要让你们付出代价", "愤怒", 3, 5),
        MockDialogue("三年后...", "紧张", 6, 8),
        MockDialogue("曾经的废柴如今已是总裁", "激动", 9, 11),
        MockDialogue("跪下", "愤怒", 12, 13),
    ]

    # 测试分类
    clf = get_classifier()
    print(f"\n已注册剧种: {clf.registered_genres}")

    r1 = clf.classify(sweet_dialogues, total_duration=15)
    print(f"\n甜宠对话 → {r1.genre} (置信度: {r1.confidence})")

    r2 = clf.classify(revenge_dialogues, total_duration=14)
    print(f"逆袭对话 → {r2.genre} (置信度: {r2.confidence})")

    # 测试 5 样本注册新类型
    print("\n" + "=" * 50)
    print("测试 5 样本注册「电竞」类型")
    gaming_features = [
        UniversalFeatureExtractor.extract([
            MockDialogue("三杀", "激动", 0, 1),
            MockDialogue("nice!", "开心", 2, 3),
            MockDialogue("他在偷塔", "紧张", 4, 5),
            MockDialogue("团灭对面", "激动", 6, 7),
            MockDialogue("赢了!", "激动", 8, 9),
        ]),
        UniversalFeatureExtractor.extract([
            MockDialogue("守家", "紧张", 0, 1),
            MockDialogue("别让他回来", "紧张", 2, 3),
            MockDialogue("五杀了!", "激动", 4, 5),
        ]),
        UniversalFeatureExtractor.extract([
            MockDialogue("开局先打野", "紧张", 0, 1),
            MockDialogue("中路集合", "紧张", 2, 3),
            MockDialogue("一波推", "激动", 4, 5),
        ]),
        UniversalFeatureExtractor.extract([
            MockDialogue("他操作太强了", "开心", 0, 2),
            MockDialogue("没办法被秀了", "悲伤", 3, 4),
        ]),
        UniversalFeatureExtractor.extract([
            MockDialogue("抢到大龙", "激动", 0, 1),
            MockDialogue("反打", "紧张", 2, 3),
        ]),
    ]

    ok = clf.register_genre(
        "电竞",
        gaming_features,
        abcd_weights={"A": 0.20, "B": 0.30, "C": 0.10, "D": 0.40},
    )
    print(f"注册结果: {'成功' if ok else '失败'}")

    if ok:
        r3 = clf.classify([
            MockDialogue("对面在打龙", "紧张", 0, 1),
            MockDialogue("我去抢", "激动", 2, 3),
            MockDialogue("漂亮拿下了", "激动", 4, 5),
        ])
        print(f"电竞对话 → {r3.genre} (置信度: {r3.confidence})")
        print(f"  ABCD权重: {clf.get_abcd_weights(r3.genre)}")
