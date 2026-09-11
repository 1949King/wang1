"""
爆款优化引擎 - 核心算法壁垒
==========================
基于平台算法优化视频，实现高完播率、高互动率、高分享率

这是超越剪映和有戏AI的核心竞争力
"""

import json
import numpy as np
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
import os
import logging

logger = logging.getLogger(__name__)


class Platform(Enum):
    """目标平台"""
    DOUYIN = "抖音"
    KUAISHOU = "快手"
    XIAOHONGSHU = "小红书"
    BILIBILI = "B站"
    WECHAT = "视频号"


class ViralFactor(Enum):
    """爆款因子类型"""
    HOOK_3S = "3秒钩子"           # 开场3秒吸引力
    PACING = "节奏控制"            # 整体节奏
    EMOTION_PEAK = "情绪峰值"      # 情绪高点
    CLIFFHANGER = "悬念设置"       # 悬念/钩子
    CONFLICT = "冲突强度"          # 冲突强度
    RELATABILITY = "共鸣度"        # 观众共鸣
    SHARE_VALUE = "分享价值"       # 社交货币
    COMMENT_TRIGGER = "评论引导"   # 引导评论


@dataclass
class VideoFeatures:
    """视频特征"""
    duration: float                    # 视频时长
    scene_count: int                   # 场景数量
    avg_scene_duration: float          # 平均场景时长
    dialogue_density: float            # 对话密度
    emotion_variance: float            # 情绪变化幅度
    conflict_intensity: float          # 冲突强度
    hook_quality: float                # 开场质量
    climax_position: float             # 高潮位置（0-1）
    has_cliffhanger: bool              # 是否有悬念
    visual_attractiveness: float       # 视觉吸引力
    audio_quality: float               # 音频质量
    subtitle_quality: float            # 字幕质量


@dataclass
class PerformancePrediction:
    """表现预测"""
    completion_rate_3s: float          # 3秒完播率预测
    completion_rate_full: float        # 整体完播率预测
    like_rate: float                   # 点赞率预测
    comment_rate: float                # 评论率预测
    share_rate: float                  # 分享率预测
    viral_probability: float           # 爆款概率
    estimated_views: str               # 预估播放量级别
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "3秒完播率": f"{self.completion_rate_3s:.1%}",
            "整体完播率": f"{self.completion_rate_full:.1%}",
            "点赞率": f"{self.like_rate:.2%}",
            "评论率": f"{self.comment_rate:.2%}",
            "分享率": f"{self.share_rate:.2%}",
            "爆款概率": f"{self.viral_probability:.1%}",
            "预估播放量": self.estimated_views
        }


@dataclass
class OptimizationSuggestion:
    """优化建议"""
    factor: ViralFactor
    current_score: float               # 当前得分 0-100
    target_score: float                # 目标得分
    priority: int                      # 优先级 1-5
    suggestion: str                    # 具体建议
    expected_improvement: str          # 预期改善效果


@dataclass
class ViralGenes:
    """爆款基因"""
    pattern_name: str                  # 模式名称
    description: str                   # 描述
    success_rate: float                # 成功率
    key_elements: List[str]            # 关键要素
    applicable_genres: List[str]       # 适用类型


class ViralOptimizationEngine:
    """
    爆款优化引擎
    
    核心功能：
    1. 完播率预测 - 基于视频特征预测完播率
    2. 平台算法适配 - 针对不同平台优化
    3. 爆款基因分析 - 分析历史爆款，提取成功要素
    4. 优化建议生成 - 提供具体的改进建议
    """
    
    # 平台算法权重配置
    PLATFORM_WEIGHTS = {
        Platform.DOUYIN: {
            "hook_3s": 0.35,           # 抖音最看重前3秒
            "completion_rate": 0.30,
            "interaction": 0.20,
            "share": 0.15
        },
        Platform.KUAISHOU: {
            "hook_3s": 0.25,
            "completion_rate": 0.25,
            "interaction": 0.30,       # 快手更看重互动
            "share": 0.20
        },
        Platform.XIAOHONGSHU: {
            "hook_3s": 0.20,
            "completion_rate": 0.20,
            "interaction": 0.25,
            "share": 0.35              # 小红书更看重分享
        }
    }
    
    # 爆款基因库
    # 如实说明：下列 success_rate 是基于短剧行业经验总结的启发式估值
    # （编辑规则库），不是从真实播放数据统计出来的实测成功率，请勿当作
    # 精确的历史数据指标展示给用户；用途是给同类套路排个大致优先级。
    VIRAL_GENES_LIBRARY = [
        ViralGenes(
            pattern_name="黄金3秒钩子",
            description="开场3秒必须有强烈吸引力，可以是冲突、疑问、视觉冲击",
            success_rate=0.85,
            key_elements=["冲突开场", "悬念提问", "视觉冲击", "情绪爆发"],
            applicable_genres=["甜宠", "虐恋", "逆袭", "悬疑"]
        ),
        ViralGenes(
            pattern_name="15秒情绪过山车",
            description="每15秒必须有一个情绪起伏，保持观众注意力",
            success_rate=0.78,
            key_elements=["情绪转折", "节奏变化", "小高潮", "意外发展"],
            applicable_genres=["甜宠", "虐恋", "都市", "古装"]
        ),
        ViralGenes(
            pattern_name="悬念前置",
            description="在视频前半段设置悬念，后半段逐步揭晓",
            success_rate=0.82,
            key_elements=["悬念设置", "信息控制", "逐步揭晓", "结尾反转"],
            applicable_genres=["悬疑", "推理", "反转", "穿越"]
        ),
        ViralGenes(
            pattern_name="爽点密集轰炸",
            description="短时间内连续多个爽点，不给观众喘息机会",
            success_rate=0.75,
            key_elements=["打脸", "逆袭", "反转", "高光时刻", "连续高潮"],
            applicable_genres=["逆袭", "战神", "赘婿", "重生"]
        ),
        ViralGenes(
            pattern_name="CP糖分超标",
            description="高甜互动，让观众嗑糖上头",
            success_rate=0.80,
            key_elements=["眼神杀", "肢体接触", "甜蜜对话", "吃醋", "护短"],
            applicable_genres=["甜宠", "校园", "都市", "古装"]
        ),
        ViralGenes(
            pattern_name="共鸣暴击",
            description="击中观众痛点或爽点，引发强烈共鸣",
            success_rate=0.77,
            key_elements=["职场困境", "家庭矛盾", "情感共鸣", "社会话题"],
            applicable_genres=["都市", "职场", "家庭", "现实"]
        )
    ]
    
    def __init__(self):
        """初始化引擎"""
        try:
            logger.info(f'[ViralOptimizationEngine] ready, genes={len(self.VIRAL_GENES_LIBRARY)}')
        except Exception as e:
            logger.debug("ViralOptimizationEngine初始化日志输出失败: %s", e)
    
    def predict_performance(self, features: VideoFeatures, 
                           platform: Platform = Platform.DOUYIN) -> PerformancePrediction:
        """
        预测视频表现
        
        Args:
            features: 视频特征
            platform: 目标平台
            
        Returns:
            PerformancePrediction: 表现预测结果
        """
        weights = self.PLATFORM_WEIGHTS.get(platform, self.PLATFORM_WEIGHTS[Platform.DOUYIN])
        
        # 计算3秒完播率（基于开场质量）
        completion_3s = self._calculate_3s_completion(features, weights)
        
        # 计算整体完播率
        completion_full = self._calculate_full_completion(features, weights)
        
        # 计算互动率
        like_rate = self._calculate_like_rate(features)
        comment_rate = self._calculate_comment_rate(features)
        share_rate = self._calculate_share_rate(features, weights)
        
        # 计算爆款概率
        viral_prob = self._calculate_viral_probability(
            completion_3s, completion_full, like_rate, comment_rate, share_rate
        )
        
        # 预估播放量
        estimated_views = self._estimate_views(viral_prob, platform)
        
        return PerformancePrediction(
            completion_rate_3s=completion_3s,
            completion_rate_full=completion_full,
            like_rate=like_rate,
            comment_rate=comment_rate,
            share_rate=share_rate,
            viral_probability=viral_prob,
            estimated_views=estimated_views
        )
    
    def _calculate_3s_completion(self, features: VideoFeatures, weights: Dict) -> float:
        """计算3秒完播率"""
        score = 0.0
        
        # 开场质量权重最高
        score += features.hook_quality * 0.4
        
        # 视觉吸引力
        score += features.visual_attractiveness * 0.3
        
        # 音频质量
        score += features.audio_quality * 0.2
        
        # 字幕质量
        score += features.subtitle_quality * 0.1
        
        # 归一化到0-1
        return min(1.0, max(0.0, score / 100))
    
    def _calculate_full_completion(self, features: VideoFeatures, weights: Dict) -> float:
        """计算整体完播率"""
        score = 0.0
        
        # 节奏控制
        optimal_duration = 60 if features.duration > 60 else features.duration
        duration_score = 1.0 - abs(features.duration - optimal_duration) / optimal_duration
        score += duration_score * 0.25
        
        # 情绪变化
        score += features.emotion_variance * 0.25
        
        # 冲突强度
        score += features.conflict_intensity * 0.2
        
        # 高潮位置（最佳在60-80%位置）
        optimal_climax = 0.7
        climax_score = 1.0 - abs(features.climax_position - optimal_climax) * 2
        score += max(0, climax_score) * 0.2
        
        # 悬念设置
        if features.has_cliffhanger:
            score += 0.1
        
        return min(1.0, max(0.0, score))
    
    def _calculate_like_rate(self, features: VideoFeatures) -> float:
        """计算点赞率"""
        # 基于情绪峰值和共鸣度
        base_rate = 0.02  # 基础点赞率2%
        
        # 情绪贡献
        emotion_boost = features.emotion_variance * 0.03
        
        # 冲突贡献
        conflict_boost = features.conflict_intensity * 0.02
        
        return min(0.15, base_rate + emotion_boost + conflict_boost)
    
    def _calculate_comment_rate(self, features: VideoFeatures) -> float:
        """计算评论率"""
        # 基于悬念和争议性
        base_rate = 0.005  # 基础评论率0.5%
        
        # 悬念贡献
        cliffhanger_boost = 0.02 if features.has_cliffhanger else 0
        
        # 冲突贡献（争议性）
        conflict_boost = features.conflict_intensity * 0.015
        
        return min(0.08, base_rate + cliffhanger_boost + conflict_boost)
    
    def _calculate_share_rate(self, features: VideoFeatures, weights: Dict) -> float:
        """计算分享率"""
        # 基于共鸣度和情绪强度
        base_rate = 0.001  # 基础分享率0.1%
        
        # 情绪贡献
        emotion_boost = features.emotion_variance * 0.008
        
        # 共鸣度贡献（这里用冲突强度作为代理）
        relatable_boost = features.conflict_intensity * 0.006
        
        return min(0.05, base_rate + emotion_boost + relatable_boost)
    
    def _calculate_viral_probability(self, completion_3s: float, 
                                    completion_full: float,
                                    like_rate: float, 
                                    comment_rate: float,
                                    share_rate: float) -> float:
        """计算爆款概率"""
        # 加权计算
        score = (
            completion_3s * 0.30 +      # 3秒完播率最重要
            completion_full * 0.25 +    # 整体完播率
            like_rate * 5 * 0.20 +      # 点赞率（归一化）
            comment_rate * 20 * 0.15 +  # 评论率（归一化）
            share_rate * 50 * 0.10      # 分享率（归一化）
        )
        
        return min(1.0, max(0.0, score))
    
    def _estimate_views(self, viral_prob: float, platform: Platform) -> str:
        """预估播放量级别"""
        if viral_prob >= 0.8:
            return "100万+ (爆款)"
        elif viral_prob >= 0.6:
            return "10-100万 (热门)"
        elif viral_prob >= 0.4:
            return "1-10万 (推荐)"
        elif viral_prob >= 0.2:
            return "1000-1万 (普通)"
        else:
            return "<1000 (需优化)"
    
    def generate_optimization_suggestions(self, features: VideoFeatures,
                                         platform: Platform = Platform.DOUYIN) -> List[OptimizationSuggestion]:
        """
        生成优化建议
        
        Args:
            features: 视频特征
            platform: 目标平台
            
        Returns:
            List[OptimizationSuggestion]: 优化建议列表
        """
        suggestions = []
        
        # 1. 3秒钩子优化
        if features.hook_quality < 70:
            suggestions.append(OptimizationSuggestion(
                factor=ViralFactor.HOOK_3S,
                current_score=features.hook_quality,
                target_score=85,
                priority=1,
                suggestion="开场3秒需要更强的吸引力，建议：\n" +
                          "• 直接展示冲突或高潮\n" +
                          "• 使用悬念式提问\n" +
                          "• 添加视觉冲击画面\n" +
                          "• 避免平淡的开场白",
                expected_improvement="3秒完播率提升 15-25%"
            ))
        
        # 2. 节奏控制优化
        optimal_scenes = features.duration / 3  # 平均每3秒一个场景
        if features.scene_count < optimal_scenes * 0.7:
            suggestions.append(OptimizationSuggestion(
                factor=ViralFactor.PACING,
                current_score=50,
                target_score=80,
                priority=2,
                suggestion="节奏偏慢，建议：\n" +
                          "• 增加场景切换频率\n" +
                          "• 删减冗余对话\n" +
                          "• 使用更快的转场\n" +
                          "• 保持每3-5秒有变化",
                expected_improvement="整体完播率提升 10-20%"
            ))
        
        # 3. 情绪峰值优化
        if features.emotion_variance < 0.5:
            suggestions.append(OptimizationSuggestion(
                factor=ViralFactor.EMOTION_PEAK,
                current_score=features.emotion_variance * 100,
                target_score=70,
                priority=2,
                suggestion="情绪变化不够强烈，建议：\n" +
                          "• 增加情绪转折\n" +
                          "• 强化爽点/虐点\n" +
                          "• 使用BGM配合情绪\n" +
                          "• 每15秒一个情绪起伏",
                expected_improvement="互动率提升 20-30%"
            ))
        
        # 4. 悬念设置优化
        if not features.has_cliffhanger:
            suggestions.append(OptimizationSuggestion(
                factor=ViralFactor.CLIFFHANGER,
                current_score=0,
                target_score=80,
                priority=3,
                suggestion="缺乏悬念设置，建议：\n" +
                          "• 在关键处戛然而止\n" +
                          "• 留下未解之谜\n" +
                          "• 使用\"欲知后事\"手法\n" +
                          "• 引导观众看后续",
                expected_improvement="评论率提升 30-50%"
            ))
        
        # 5. 冲突强度优化
        if features.conflict_intensity < 0.6:
            suggestions.append(OptimizationSuggestion(
                factor=ViralFactor.CONFLICT,
                current_score=features.conflict_intensity * 100,
                target_score=75,
                priority=3,
                suggestion="冲突不够强烈，建议：\n" +
                          "• 强化正反对立\n" +
                          "• 增加打脸情节\n" +
                          "• 突出主角困境\n" +
                          "• 让反派更嚣张",
                expected_improvement="分享率提升 15-25%"
            ))
        
        # 按优先级排序
        suggestions.sort(key=lambda x: x.priority)
        
        return suggestions
    
    def analyze_viral_genes(self, genre: str = "甜宠") -> List[ViralGenes]:
        """
        分析适用的爆款基因
        
        Args:
            genre: 短剧类型
            
        Returns:
            List[ViralGenes]: 适用的爆款基因列表
        """
        applicable_genes = []
        
        for gene in self.VIRAL_GENES_LIBRARY:
            if genre in gene.applicable_genres or "all" in gene.applicable_genres:
                applicable_genes.append(gene)
        
        # 按成功率排序
        applicable_genes.sort(key=lambda x: x.success_rate, reverse=True)
        
        return applicable_genes
    
    def optimize_for_platform(self, features: VideoFeatures,
                             platform: Platform) -> Dict[str, Any]:
        """
        针对特定平台优化
        
        Args:
            features: 视频特征
            platform: 目标平台
            
        Returns:
            Dict: 优化方案
        """
        # 预测当前表现
        prediction = self.predict_performance(features, platform)
        
        # 生成优化建议
        suggestions = self.generate_optimization_suggestions(features, platform)
        
        # 获取适用的爆款基因
        viral_genes = self.analyze_viral_genes()
        
        return {
            "platform": platform.value,
            "current_prediction": prediction.to_dict(),
            "optimization_suggestions": [
                {
                    "factor": s.factor.value,
                    "current_score": s.current_score,
                    "target_score": s.target_score,
                    "priority": s.priority,
                    "suggestion": s.suggestion,
                    "expected_improvement": s.expected_improvement
                }
                for s in suggestions
            ],
            "recommended_viral_genes": [
                {
                    "name": g.pattern_name,
                    "description": g.description,
                    "success_rate": f"{g.success_rate:.1%}",
                    "key_elements": g.key_elements
                }
                for g in viral_genes[:3]
            ],
            "optimal_settings": self._get_optimal_settings(platform)
        }
    
    def _get_optimal_settings(self, platform: Platform) -> Dict[str, Any]:
        """获取平台最优设置"""
        settings = {
            Platform.DOUYIN: {
                "duration_range": "15-60秒",
                "aspect_ratio": "9:16",
                "resolution": "1080x1920",
                "fps": 30,
                "bitrate": "4-8Mbps",
                "key_elements": ["3秒钩子", "快节奏", "强情绪", "悬念结尾"]
            },
            Platform.KUAISHOU: {
                "duration_range": "30-90秒",
                "aspect_ratio": "9:16",
                "resolution": "1080x1920",
                "fps": 30,
                "bitrate": "4-6Mbps",
                "key_elements": ["接地气", "真实感", "互动引导", "连续剧情"]
            },
            Platform.XIAOHONGSHU: {
                "duration_range": "30-120秒",
                "aspect_ratio": "3:4或9:16",
                "resolution": "1080x1440",
                "fps": 30,
                "bitrate": "6-10Mbps",
                "key_elements": ["高颜值", "精致感", "实用价值", "分享欲"]
            }
        }
        
        return settings.get(platform, settings[Platform.DOUYIN])
    
    def generate_ab_test_versions(self, base_features: VideoFeatures,
                                  platform: Platform = Platform.DOUYIN) -> List[Dict[str, Any]]:
        """
        生成A/B测试版本
        
        Args:
            base_features: 基础视频特征
            platform: 目标平台
            
        Returns:
            List[Dict]: A/B测试版本方案
        """
        versions = []
        
        # 版本A: 强调3秒钩子
        version_a = {
            "version_name": "A - 强钩子版",
            "focus": "优化前3秒吸引力",
            "modifications": [
                "开场直接展示高潮片段",
                "使用悬念式标题",
                "添加强烈的视觉冲击",
                "前3秒音量提高20%"
            ],
            "expected_completion_3s": "75-85%",
            "target_audience": "注意力分散的用户"
        }
        versions.append(version_a)
        
        # 版本B: 强调情绪过山车
        version_b = {
            "version_name": "B - 情绪版",
            "focus": "强化情绪起伏",
            "modifications": [
                "每15秒设置一个情绪转折",
                "BGM配合情绪变化",
                "强化爽点和虐点",
                "使用慢动作强调情绪"
            ],
            "expected_completion_full": "60-70%",
            "target_audience": "情感共鸣型用户"
        }
        versions.append(version_b)
        
        # 版本C: 强调悬念
        version_c = {
            "version_name": "C - 悬念版",
            "focus": "设置强烈悬念",
            "modifications": [
                "在关键处戛然而止",
                "添加\"未完待续\"提示",
                "引导评论互动",
                "结尾留下未解之谜"
            ],
            "expected_comment_rate": "3-5%",
            "target_audience": "好奇心强的用户"
        }
        versions.append(version_c)
        
        return versions


# 使用示例
if __name__ == "__main__":
    # 初始化引擎
    engine = ViralOptimizationEngine()
    
    # 示例视频特征
    features = VideoFeatures(
        duration=45.0,
        scene_count=12,
        avg_scene_duration=3.75,
        dialogue_density=0.7,
        emotion_variance=0.6,
        conflict_intensity=0.8,
        hook_quality=65,
        climax_position=0.75,
        has_cliffhanger=True,
        visual_attractiveness=75,
        audio_quality=80,
        subtitle_quality=70
    )
    
    # 预测表现
    print("=" * 70)
    print("🎯 视频表现预测")
    print("=" * 70)
    
    for platform in [Platform.DOUYIN, Platform.KUAISHOU, Platform.XIAOHONGSHU]:
        prediction = engine.predict_performance(features, platform)
        print(f"\n📱 {platform.value}:")
        for key, value in prediction.to_dict().items():
            print(f"   {key}: {value}")
    
    # 生成优化建议
    print("\n" + "=" * 70)
    print("💡 优化建议")
    print("=" * 70)
    
    suggestions = engine.generate_optimization_suggestions(features, Platform.DOUYIN)
    for i, suggestion in enumerate(suggestions[:3], 1):
        print(f"\n{i}. {suggestion.factor.value} (优先级: {suggestion.priority})")
        print(f"   当前得分: {suggestion.current_score:.0f}/100")
        print(f"   目标得分: {suggestion.target_score:.0f}/100")
        print(f"   建议:\n{suggestion.suggestion}")
        print(f"   预期改善: {suggestion.expected_improvement}")
    
    # 获取爆款基因
    print("\n" + "=" * 70)
    print("🧬 推荐爆款基因")
    print("=" * 70)
    
    genes = engine.analyze_viral_genes("甜宠")
    for i, gene in enumerate(genes[:3], 1):
        print(f"\n{i}. {gene.pattern_name} (成功率: {gene.success_rate:.1%})")
        print(f"   {gene.description}")
        print(f"   关键要素: {', '.join(gene.key_elements)}")
