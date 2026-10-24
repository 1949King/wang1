"""
爆款基因识别引擎
================
基于抖音/快手爆款短剧的统计规律，从字幕 + 元数据中识别"爆款基因片段"。

核心创新 (相对 FunClip/mcp-video):
    - 黄金 3 秒开场检测 (强冲突/悬念/提问)
    - 15 秒反转点识别
    - 30 秒情绪峰值
    - 60 秒完播率优化节奏
    - 节奏曲线 (每 5 秒一个钩子)

参考:
    - 抖音短剧完播率统计规律 (2024-2025)
    - FunClip 字幕分析思路
    - 项目内 llm_clipper.py 现有 LLM 集成方式

设计原则 (不破坏现有架构):
    - 独立文件, 不修改任何现有模块
    - 输入: 字幕 + 时长 (兼容现有 subtitle_generator 输出)
    - 输出: 高光片段列表 (兼容现有 timeline_dsl)
    - LLM 可选: 优先用规则打分, 无 LLM 时降级可用
"""

import re
import json
import logging
import time
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Tuple, Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass
class SubtitleCue:
    """单条字幕 - 兼容现有 SRT 格式"""
    index: int
    start: float       # 秒
    end: float         # 秒
    text: str

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class GeneHit:
    """单个基因命中"""
    gene_name: str         # 基因名称 (如 "黄金3秒开场")
    start: float           # 命中起始时间
    end: float             # 命中结束时间
    score: float           # 0-100 分
    reason: str            # 命中原因
    weight: float = 1.0    # 基因权重


@dataclass
class ViralSegment:
    """爆款片段 - 输出到 timeline"""
    start: float
    end: float
    total_score: float     # 0-100 综合得分
    genes: List[GeneHit] = field(default_factory=list)
    subtitle: str = ""     # 片段代表字幕
    suggested_title: str = ""  # AI 推荐标题

    def to_dict(self) -> dict:
        return {
            "start": self.start,
            "end": self.end,
            "duration": self.end - self.start,
            "total_score": round(self.total_score, 1),
            "genes": [asdict(g) for g in self.genes],
            "subtitle": self.subtitle,
            "suggested_title": self.suggested_title,
        }


# ---------------------------------------------------------------------------
# 爆款基因定义 (抖音/快手统计规律)
# ---------------------------------------------------------------------------

# 黄金 3 秒关键词 (强冲突/悬念/提问/身份代入)
GOLDEN_3S_KEYWORDS = {
    "conflict": ["打", "杀", "抢", "夺", "抢走", "离婚", "出轨", "背叛", "揭穿", "怒", "滚", "死", "跪",
                 "崩溃", "疯", "爆炸", "血", "刀", "逼", "威胁", "陷害"],
    "suspense": ["突然", "没想到", "原来", "居然", "竟然", "这时", "那一刻", "下一秒", "结果",
                 "真相", "秘密", "发现", "终于", "意外"],
    "question": ["什么", "为什么", "怎么", "谁", "哪", "吗", "？", "?"],
    "identity": ["我", "你", "他", "她", "老公", "老婆", "妈妈", "爸爸", "儿子", "女儿", "总裁", "夫人",
                 "少爷", "小姐"],
    "wakeup": ["开局", "第一", "刚", "原来如此", "震惊", "万万没想到"],
}

# 15 秒反转点关键词
REVERSAL_15S_KEYWORDS = {
    "transition": ["但", "可是", "然而", "没想到", "结果", "真相是", "原来是", "然而", "不过", "实际上"],
    "reveal": ["原来", "真相", "秘密", "身份", "其实", "表面", "背后", "真实"],
    "emotion_shift": ["瞬间", "突然", "猛然", "一下子", "当场", "立刻", "马上"],
}

# 情绪峰值关键词 (用于 30s 节点)
EMOTION_PEAK_KEYWORDS = {
    "climax": ["爱", "恨", "死", "活", "永远", "绝不", "发誓", "承诺", "我爱你", "对不起",
               "原谅", "求你", "求求", "心碎", "崩溃", "大哭", "跪下"],
    "extreme": ["最", "绝对", "完全", "彻底", "永远不", "从今以后", "一辈子"],
}

# 节奏钩子关键词 (每 5 秒) - 用于评分而非命中
RHYTHM_HOOK_KEYWORDS = {
    "new_info": ["他", "她", "它", "这", "那", "新", "另", "一个", "突然", "原来"],
    "action": ["走", "跑", "冲", "来", "去", "打", "抓", "拉", "推", "开", "关"],
    "dialogue": ["说", "喊", "叫", "问", "回答", "笑", "哭", "怒"],
}


# ---------------------------------------------------------------------------
# 字幕解析 (兼容现有 SRT)
# ---------------------------------------------------------------------------

def parse_srt_text(srt_content: str) -> List[SubtitleCue]:
    """解析 SRT 文本为 SubtitleCue 列表"""
    cues: List[SubtitleCue] = []
    if not srt_content:
        return cues

    # SRT 块以空行分隔
    blocks = re.split(r"\n\s*\n", srt_content.strip())
    time_pattern = re.compile(
        r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})"
        r"\s*-->\s*"
        r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})"
    )

    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 2:
            continue

        # 解析时间行
        time_line = lines[1] if len(lines) > 1 else lines[0]
        m = time_pattern.search(time_line)
        if not m:
            continue

        h1, m1, s1, ms1, h2, m2, s2, ms2 = m.groups()
        start = int(h1) * 3600 + int(m1) * 60 + int(s1) + int(ms1) / 1000
        end = int(h2) * 3600 + int(m2) * 60 + int(s2) + int(ms2) / 1000

        # 提取序号 (可能在时间行之前)
        text_lines = lines[2:] if len(lines) > 2 and time_line in lines[1] else lines[1:]
        text = " ".join(l.strip() for l in text_lines).strip()
        if not text:
            continue

        try:
            index = int(lines[0].strip())
        except ValueError:
            index = len(cues) + 1

        cues.append(SubtitleCue(
            index=index, start=start, end=end, text=text
        ))

    return cues


def _load_srt_file(path: str) -> List[SubtitleCue]:
    """从文件加载 SRT"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return parse_srt_text(f.read())
    except Exception as e:
        logger.error(f"加载 SRT 失败 {path}: {e}")
        return []


# ---------------------------------------------------------------------------
# 基因检测器 (规则版本 - 无需 LLM 即可工作)
# ---------------------------------------------------------------------------

def _match_keywords(text: str, keyword_groups: Dict[str, List[str]]) -> Dict[str, int]:
    """统计每个分组的命中数"""
    hits: Dict[str, int] = {}
    for group, keywords in keyword_groups.items():
        hits[group] = 0
        for kw in keywords:
            if kw in text:
                hits[group] += 1
    return hits


def _score_cue(cue: SubtitleCue, keyword_groups: Dict[str, List[str]]) -> Tuple[float, Dict[str, int]]:
    """对单条字幕打分 (0-100)"""
    hits = _match_keywords(cue.text, keyword_groups)
    total_hits = sum(hits.values())

    if total_hits == 0:
        return 0.0, hits

    # 基础分 + 命中数加权
    base = 40.0
    weighted = min(60.0, total_hits * 15.0)

    # 字幕长度惩罚 (过短或过长降低权重)
    text_len = len(cue.text)
    if text_len < 4:
        weighted *= 0.5
    elif text_len > 80:
        weighted *= 0.7

    return min(100.0, base + weighted), hits


def detect_golden_3s(cues: List[SubtitleCue]) -> List[GeneHit]:
    """检测黄金 3 秒开场 (视频前 10 秒内)"""
    hits: List[GeneHit] = []
    for cue in cues:
        if cue.start > 10.0:  # 超过 10 秒不再算开场
            break
        if cue.end > 12.0:
            continue
        score, kw_hits = _score_cue(cue, GOLDEN_3S_KEYWORDS)
        if score >= 55.0:
            top_group = max(kw_hits.items(), key=lambda x: x[1])[0]
            hits.append(GeneHit(
                gene_name="黄金3秒开场",
                start=cue.start,
                end=cue.end,
                score=score,
                reason=f"开场命中[{top_group}]关键词 {kw_hits[top_group]} 次",
                weight=1.5,  # 开场权重最高
            ))
    return hits


def detect_reversal_15s(cues: List[SubtitleCue]) -> List[GeneHit]:
    """检测 15 秒反转点"""
    hits: List[GeneHit] = []
    for cue in cues:
        # 关注 10-25 秒区间 (15 秒节点附近)
        if cue.start < 8.0 or cue.start > 30.0:
            continue
        score, kw_hits = _score_cue(cue, REVERSAL_15S_KEYWORDS)
        if score >= 55.0:
            top_group = max(kw_hits.items(), key=lambda x: x[1])[0]
            hits.append(GeneHit(
                gene_name="15秒反转点",
                start=cue.start,
                end=cue.end,
                score=score,
                reason=f"反转命中[{top_group}]关键词",
                weight=1.3,
            ))
    return hits


def detect_emotion_peak(cues: List[SubtitleCue]) -> List[GeneHit]:
    """检测 30 秒情绪峰值"""
    hits: List[GeneHit] = []
    for cue in cues:
        if cue.start < 20.0 or cue.start > 50.0:
            continue
        score, kw_hits = _score_cue(cue, EMOTION_PEAK_KEYWORDS)
        if score >= 55.0:
            top_group = max(kw_hits.items(), key=lambda x: x[1])[0]
            hits.append(GeneHit(
                gene_name="30秒情绪峰值",
                start=cue.start,
                end=cue.end,
                score=score,
                reason=f"情绪命中[{top_group}]关键词 {kw_hits[top_group]} 次",
                weight=1.2,
            ))
    return hits


def detect_rhythm_hooks(cues: List[SubtitleCue], total_duration: float) -> List[GeneHit]:
    """检测节奏钩子 (每 5 秒一个钩子, 用于完播率)"""
    hits: List[GeneHit] = []
    # 按 5 秒分桶
    bucket_sec = 5.0
    if total_duration <= 0:
        return hits

    buckets: Dict[int, List[SubtitleCue]] = {}
    for cue in cues:
        bidx = int(cue.start // bucket_sec)
        buckets.setdefault(bidx, []).append(cue)

    for bidx, bucket_cues in sorted(buckets.items()):
        # 合并桶内字幕
        all_text = " ".join(c.text for c in bucket_cues)
        if not all_text.strip():
            continue

        hit_count = sum(_match_keywords(all_text, RHYTHM_HOOK_KEYWORDS).values())
        # 钩子分 = 命中数 × 权重
        if hit_count >= 2:
            score = min(100.0, 50.0 + hit_count * 12.0)
            hits.append(GeneHit(
                gene_name=f"{bidx * 5}-{(bidx + 1) * 5}秒钩子",
                start=bidx * bucket_sec,
                end=min((bidx + 1) * bucket_sec, total_duration),
                score=score,
                reason=f"本 5 秒区间命中 {hit_count} 个节奏钩子",
                weight=0.6,
            ))
    return hits


# ---------------------------------------------------------------------------
# 片段聚合器
# ---------------------------------------------------------------------------

def _find_cue_at(time_s: float, cues: List[SubtitleCue]) -> Optional[SubtitleCue]:
    """找到指定时间对应的字幕"""
    for cue in cues:
        if cue.start <= time_s <= cue.end:
            return cue
    # 否则找最近的
    best = None
    best_diff = float("inf")
    for cue in cues:
        mid = (cue.start + cue.end) / 2
        diff = abs(mid - time_s)
        if diff < best_diff:
            best_diff = diff
            best = cue
    return best


def _merge_close_hits(hits: List[GeneHit], merge_window: float = 2.0) -> List[GeneHit]:
    """合并时间接近的命中 (窗口更小, 保留更多独立片段)"""
    if not hits:
        return hits
    sorted_hits = sorted(hits, key=lambda h: h.start)
    merged: List[GeneHit] = [sorted_hits[0]]
    for hit in sorted_hits[1:]:
        last = merged[-1]
        # 短钩子 (5秒桶) 不与长基因合并, 避免吞噬
        if last.gene_name.endswith("秒钩子") or hit.gene_name.endswith("秒钩子"):
            merged.append(hit)
            continue
        if hit.start - last.end <= merge_window:
            # 合并
            last.end = max(last.end, hit.end)
            last.score = (last.score + hit.score) / 2
            # 只保留前 2 个 reason, 避免过长
            existing = last.reason.split(" + ")
            new_reason = f"{hit.reason}"
            if new_reason not in existing and len(existing) < 2:
                last.reason = " + ".join(existing + [new_reason])
            last.weight = max(last.weight, hit.weight)
        else:
            merged.append(hit)
    return merged


def aggregate_segments(
    cues: List[SubtitleCue],
    total_duration: float,
    min_segment: float = 8.0,
    max_segment: float = 60.0,
    top_k: int = 5,
) -> List[ViralSegment]:
    """将基因命中聚合成最终爆款片段"""
    # 1) 跑所有检测器
    all_hits: List[GeneHit] = []
    all_hits.extend(detect_golden_3s(cues))
    all_hits.extend(detect_reversal_15s(cues))
    all_hits.extend(detect_emotion_peak(cues))
    all_hits.extend(detect_rhythm_hooks(cues, total_duration))

    if not all_hits:
        return []

    # 2) 合并时间接近的
    merged = _merge_close_hits(all_hits, merge_window=2.5)

    # 3) 按权重 × 分数 排序
    merged.sort(key=lambda h: h.score * h.weight, reverse=True)

    # 4) 构建片段
    segments: List[ViralSegment] = []
    used_ranges: List[Tuple[float, float]] = []

    for hit in merged:
        if len(segments) >= top_k:
            break

        # 检查是否与已选片段重叠
        overlap = False
        for s_start, s_end in used_ranges:
            if not (hit.end < s_start - 1.0 or hit.start > s_end + 1.0):
                overlap = True
                break
        if overlap:
            continue

        # 限制片段长度
        seg_start = hit.start
        seg_end = min(seg_start + max_segment, hit.end + min_segment)
        if seg_end - seg_start < min_segment:
            seg_end = seg_start + min_segment
        if seg_end > total_duration:
            seg_end = total_duration

        # 找到该片段的字幕代表
        ref_cue = _find_cue_at((seg_start + seg_end) / 2, cues)
        subtitle = ref_cue.text if ref_cue else hit.reason

        segments.append(ViralSegment(
            start=seg_start,
            end=seg_end,
            total_score=hit.score * hit.weight,
            genes=[hit],
            subtitle=subtitle,
        ))
        used_ranges.append((seg_start, seg_end))

    # 5) 按时间排序
    segments.sort(key=lambda s: s.start)
    return segments


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

class ViralDetector:
    """
    爆款基因识别器 - 主入口 (v2.0)

    v2.0 改进：
    - LLM 优先：语义级基因检测，不再依赖关键词字典
    - 关键词降级为 fallback（LLM 不可用时）
    - 基因得分从"命中计数"变为"语义匹配度"(0-100)

    使用示例:
        detector = ViralDetector(llm_enhance=True)
        result = detector.analyze(srt_text=..., total_duration=120.0)
        for seg in result["segments"]:
            print(f"[{seg['start']:.1f}s - {seg['end']:.1f}s] 得分 {seg['total_score']}")
    """

    # LLM 批量基因检测 prompt 模板
    _GENE_DETECT_PROMPT = """分析以下短剧字幕，检测爆款基因片段。

爆款基因定义：
1. 黄金3秒开场：前10秒内是否有强冲突/悬念/身份代入/认知唤醒
2. 15秒反转：10-25秒间是否有剧情转折/真相揭露/情绪突变
3. 30秒情绪峰值：20-50秒间是否有情绪爆发点（爱恨生死承诺崩溃等）
4. 节奏钩子：每5秒区间是否有新信息/动作/对话推动

字幕（时间+内容）:
{subtitle_block}

返回 JSON:
{{
    "genes": [
        {{"gene": "基因名(黄金3秒/15秒反转/30秒情绪峰值/节奏钩子)",
          "start": 开始秒, "end": 结束秒, "score": 0-100,
          "reason": "一句话说明为什么这是爆款基因"}}
    ]
}}"""

    def __init__(self, llm_enhance: bool = False):
        """
        Args:
            llm_enhance: True=LLM语义检测优先, False=纯关键词规则
        """
        self.llm_enhance = llm_enhance
        self._llm_client = None

    def _try_get_llm(self):
        """尝试加载 LLM 客户端 (软依赖, 失败则降级)"""
        if self._llm_client is not None:
            return self._llm_client
        try:
            from .llm_clipper import _get_ollama_client  # type: ignore
            self._llm_client = _get_ollama_client()
        except Exception as e:
            logger.debug(f"LLM 客户端不可用, 使用规则版: {e}")
            self._llm_client = False
        return self._llm_client

    def _llm_detect_genes(self, cues: List[SubtitleCue],
                           total_duration: float) -> List[GeneHit]:
        """
        LLM 语义级基因检测：一次请求分析全部字幕，返回所有基因命中。

        相比关键词方案的优势：
        - "你居然背叛我" → LLM 理解"背叛"的情绪强度，无需关键词字典收录"背叛"
        - "这一切都是你设计的？" → LLM 理解反转含义，而非等关键词"原来/居然"
        """
        client = self._try_get_llm()
        if not client or client is False:
            return []

        # 构建字幕块（限制长度避免超上下文）
        subtitle_block = "\n".join(
            f"[{cue.start:.1f}s-{cue.end:.1f}s] {cue.text[:120]}"
            for cue in cues[:60]  # 取前60条字幕
        )
        prompt = self._GENE_DETECT_PROMPT.format(subtitle_block=subtitle_block)

        try:
            response_parts = []
            for chunk in client.generate(prompt, max_tokens=800, format="json"):
                response_parts.append(chunk)
            raw = "".join(response_parts).strip()
            if not raw:
                return []
            result = json.loads(raw)
            genes_data = result.get("genes", [])

            hits = []
            for g in genes_data:
                gene_name = g.get("gene", "")
                start = float(g.get("start", 0))
                end = float(g.get("end", 0))
                score = min(100.0, max(0.0, float(g.get("score", 50))))
                reason = g.get("reason", "")

                # 确定权重
                weight = 1.0
                if "黄金3秒" in gene_name:
                    weight = 1.5
                elif "反转" in gene_name:
                    weight = 1.3
                elif "情绪峰值" in gene_name:
                    weight = 1.2
                elif "钩子" in gene_name:
                    weight = 0.6

                hits.append(GeneHit(
                    gene_name=gene_name,
                    start=max(0, start),
                    end=min(total_duration, end),
                    score=score,
                    reason=reason,
                    weight=weight,
                ))
            return hits
        except Exception as e:
            logger.debug(f"LLM基因检测失败，降级关键词: {e}")
            return []

    def _rule_based_detect(self, cues: List[SubtitleCue],
                            total_duration: float) -> List[GeneHit]:
        """关键词规则检测 (fallback)"""
        all_hits: List[GeneHit] = []
        all_hits.extend(detect_golden_3s(cues))
        all_hits.extend(detect_reversal_15s(cues))
        all_hits.extend(detect_emotion_peak(cues))
        all_hits.extend(detect_rhythm_hooks(cues, total_duration))
        return all_hits

    def analyze(
        self,
        srt_path: Optional[str] = None,
        srt_text: Optional[str] = None,
        total_duration: float = 0.0,
        top_k: int = 5,
    ) -> Dict[str, Any]:
        """
        分析字幕, 返回爆款片段

        Args:
            srt_path: SRT 文件路径
            srt_text: SRT 文本内容 (二选一)
            total_duration: 视频总时长 (秒), 用于节奏分析
            top_k: 最多返回几个片段

        Returns:
            {
                "segments": [ViralSegment.to_dict(), ...],
                "total_genes_detected": int,
                "analyzer_version": str,
                "duration_analyzed": float,
                "detection_mode": "llm" | "rule",
            }
        """
        start_time = time.time()

        # 1) 加载字幕
        if srt_path:
            cues = _load_srt_file(srt_path)
        elif srt_text:
            cues = parse_srt_text(srt_text)
        else:
            logger.warning("未提供字幕, 跳过分析")
            return self._empty_result("no_subtitle")

        if not cues:
            return self._empty_result("empty_subtitle")

        # 2) 推断总时长
        if total_duration <= 0:
            total_duration = max(cue.end for cue in cues)

        # 3) 基因检测：LLM 优先，关键词 fallback
        detection_mode = "rule"
        if self.llm_enhance:
            all_hits = self._llm_detect_genes(cues, total_duration)
            if all_hits:
                detection_mode = "llm"
            else:
                all_hits = self._rule_based_detect(cues, total_duration)
        else:
            all_hits = self._rule_based_detect(cues, total_duration)

        # 4) 聚合成片段（使用 LLM 命中的 start/end，不依赖 aggregate_segments 旧逻辑）
        if detection_mode == "llm":
            segments = self._build_segments_from_hits(all_hits, cues, total_duration, top_k)
        else:
            segments = aggregate_segments(cues, total_duration, top_k=top_k)

        # 5) LLM 增强标题
        if self.llm_enhance and segments:
            segments = self._enhance_titles_with_llm(segments)

        elapsed = (time.time() - start_time) * 1000
        logger.info(
            f"爆款基因分析完成 [{detection_mode}]: {len(cues)} 条字幕, "
            f"识别 {len(all_hits)} 个基因, "
            f"输出 {len(segments)} 个爆款片段, 耗时 {elapsed:.0f}ms"
        )

        return {
            "segments": [s.to_dict() for s in segments],
            "total_genes_detected": len(all_hits),
            "analyzer_version": "viral-gene-v2.0",
            "duration_analyzed": total_duration,
            "cues_analyzed": len(cues),
            "elapsed_ms": round(elapsed, 1),
            "detection_mode": detection_mode,
        }

    def _build_segments_from_hits(self, hits: List[GeneHit],
                                   cues: List[SubtitleCue],
                                   total_duration: float,
                                   top_k: int) -> List[ViralSegment]:
        """从 LLM 命中的基因直接构建片段（不再需要关键词聚合）"""
        # 合并时间接近的命中
        merged = _merge_close_hits(hits, merge_window=3.0)

        segments = []
        for hit in sorted(merged, key=lambda h: h.score, reverse=True)[:top_k * 2]:
            # 找到对应字幕
            cue = _find_cue_at(hit.start, cues)
            subtitle = cue.text if cue else ""

            # 检查是否与已有片段重叠
            overlaps = False
            for existing in segments:
                if not (hit.end <= existing.start or hit.start >= existing.end):
                    overlaps = True
                    break
            if overlaps:
                continue

            segments.append(ViralSegment(
                start=max(0, hit.start - 1),
                end=min(total_duration, hit.end + 1),
                total_score=hit.score,
                genes=[hit],
                subtitle=subtitle[:100],
                suggested_title="",
            ))

            if len(segments) >= top_k:
                break

        # 按时间排序
        segments.sort(key=lambda s: s.start)
        return segments

    def _enhance_titles_with_llm(self, segments: List[ViralSegment]) -> List[ViralSegment]:
        """用 LLM 为片段生成推荐标题 (软依赖)"""
        client = self._try_get_llm()
        if not client or client is False:
            return segments

        for seg in segments:
            try:
                prompt = (
                    f"为以下短剧片段起一个吸引人的 15 字以内标题:\n"
                    f"字幕: {seg.subtitle[:100]}\n"
                    f"片段时长: {seg.end - seg.start:.1f} 秒\n"
                    f"命中基因: {', '.join(g.gene_name for g in seg.genes)}\n"
                    f"只返回标题文字, 不要任何其他内容。"
                )
                response_parts = []
                for chunk in client.generate(prompt, max_tokens=50):
                    response_parts.append(chunk)
                title = "".join(response_parts).strip()
                if title:
                    seg.suggested_title = title[:30]
            except Exception as e:
                logger.debug(f"LLM 标题生成失败: {e}")
        return segments

    def _empty_result(self, reason: str) -> Dict[str, Any]:
        return {
            "segments": [],
            "total_genes_detected": 0,
            "analyzer_version": "viral-gene-v2.0",
            "duration_analyzed": 0.0,
            "cues_analyzed": 0,
            "reason": reason,
            "detection_mode": "none",
        }


# ---------------------------------------------------------------------------
# 便捷函数 (供外部调用)
# ---------------------------------------------------------------------------

def quick_detect(srt_text: str, total_duration: float = 0.0,
                 top_k: int = 3, use_llm: bool = False) -> List[Dict]:
    """
    快速检测爆款基因片段。

    Args:
        srt_text: SRT 字幕文本
        total_duration: 视频总时长
        top_k: 返回片段数
        use_llm: True=LLM语义检测, False=关键词规则

    Returns:
        片段字典列表, 按综合得分降序
    """
    detector = ViralDetector(llm_enhance=use_llm)
    result = detector.analyze(srt_text=srt_text, total_duration=total_duration, top_k=top_k)
    return result["segments"]


# ---------------------------------------------------------------------------
# 单元自测
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # 自测用例
    sample_srt = """1
00:00:00,500 --> 00:00:03,200
老公,你听我解释!

2
00:00:03,200 --> 00:00:06,800
滚!我已经看到了,你给我滚!

3
00:00:06,800 --> 00:00:10,500
不,这不是真的,你听我说!

4
00:00:10,500 --> 00:00:15,200
突然,门被推开了,她愣住了。

5
00:00:15,200 --> 00:00:20,800
原来,真正的真相是......

6
00:00:20,800 --> 00:00:28,500
她颤抖着说: 我爱你,永远爱你,求你原谅我。

7
00:00:28,500 --> 00:00:35,000
那一刻,他的心彻底崩溃了。

8
00:00:35,000 --> 00:00:45,000
从今以后,我会用一辈子来弥补。
"""

    print("=" * 60)
    print("爆款基因识别自测")
    print("=" * 60)

    detector = ViralDetector(llm_enhance=False)
    result = detector.analyze(srt_text=sample_srt, total_duration=45.0, top_k=3)

    print(f"\n分析耗时: {result.get('elapsed_ms', 0)}ms")
    print(f"字幕条数: {result['cues_analyzed']}")
    print(f"识别基因: {result['total_genes_detected']} 个")
    print(f"输出片段: {len(result['segments'])} 个\n")

    for i, seg in enumerate(result["segments"], 1):
        print(f"【片段 {i}】 {seg['start']:.1f}s - {seg['end']:.1f}s "
              f"({seg['duration']:.1f}s) 得分 {seg['total_score']:.1f}")
        print(f"  命中基因: {[g['gene_name'] for g in seg['genes']]}")
        print(f"  代表字幕: {seg['subtitle']}")
        print(f"  命中原因: {seg['genes'][0]['reason']}")
        print()
