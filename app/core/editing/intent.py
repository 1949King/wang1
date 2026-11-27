# -*- coding: utf-8 -*-
"""精剪意图规格 EditIntent —— 整条链路从开环变闭环的那一块。

为什么必须单独有这一层
----------------------
用户原方案是「VLM 读视频 → LLM 判断策略 → 执行」。但"判断"缺判据：
剪成什么样算对？目标时长、给谁看、什么节奏、哪句台词必须保留、哪些片段不许动
——这些**不在视频里**，只能由用户给。它一缺，三个环节同时悬空：

  · 决策层没有目标函数 ⇒ 只能输出「删水词 / 卡点」这类通用优化，结果还是粗剪；
  · 复核层没有验收标准 ⇒ 「通过 / 不通过」无从判定；
  · 记忆层没有索引键   ⇒ 这次为什么这么剪无法按场景召回，下次仍从零判断。

所以 EditIntent 同时是：感知的采样依据、决策的目标函数、复核的判据、配方的键。

不做什么
--------
· 不做创作判断（哪一镜是情绪锚点是人在画布上选 / 模型建议，不是本模块猜）；
· 不碰时间线、不发事件、不写撤销条目（纯数据，调用方决定落点）。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Tuple

__all__ = ["EditIntent", "PACING_VALUES"]

PACING_VALUES = ("fast", "normal", "slow")


@dataclass(frozen=True)
class EditIntent:
    """一次精剪任务的目标函数与硬约束。frozen 保证提案生成期间意图不被偷偷改写。"""

    # ── 目标函数 ──
    target_duration_sec: float = 0.0          # 0 = 不设目标时长
    duration_tolerance_sec: float = 3.0       # 复核时允许的偏差
    pacing: str = "normal"                    # fast / normal / slow
    audience: str = ""                       # 给谁看，写进决策 prompt
    notes: str = ""                          # 一句话创作意图，人话

    # ── 硬约束（复核判据，违反即判不通过）──
    keep_lines: Tuple[str, ...] = ()          # 必须保留的台词片段（子串匹配）
    protected_clip_ids: Tuple[str, ...] = ()
    preserve_ranges: Tuple[Tuple[float, float], ...] = ()  # 时间线绝对秒，禁改区间

    # ── 溯源 ──
    tags: Tuple[str, ...] = field(default_factory=tuple)

    def validate(self) -> List[str]:
        """返回问题清单（空 = 合法）。只报告，不抛异常，便于 UI 一次性展示。"""
        problems: List[str] = []
        if self.target_duration_sec < 0:
            problems.append("target_duration_sec 不能为负")
        if self.duration_tolerance_sec < 0:
            problems.append("duration_tolerance_sec 不能为负")
        if self.pacing not in PACING_VALUES:
            problems.append(f"pacing 必须是 {PACING_VALUES} 之一，当前 {self.pacing!r}")
        for i, (a, b) in enumerate(self.preserve_ranges):
            if b <= a:
                problems.append(f"preserve_ranges[{i}] 区间倒序或零宽：{a}~{b}")
        ordered = sorted(self.preserve_ranges)
        for i in range(1, len(ordered)):
            if ordered[i][0] < ordered[i - 1][1]:
                problems.append(
                    f"preserve_ranges 第 {i} 段与第 {i-1} 段重叠，保护区间必须互不重叠"
                )
        return problems

    def is_protected(self, timeline_in: float, timeline_out: float) -> bool:
        """待删区间是否与任一保护区相交（半开区间语义）。"""
        for pa, pb in self.preserve_ranges:
            if timeline_in < pb and timeline_out > pa:
                return True
        return False

    def is_protected_clip(self, clip_id: str) -> bool:
        return str(clip_id) in {str(x) for x in self.protected_clip_ids}

    def fingerprint(self) -> str:
        """稳定指纹，作为记忆召回键 / 配方键。

        刻意排除 notes 里的标点差异？不排除——指纹用于「相同意图复用配方」，
        意图文字变了就应当视为不同配方，避免拿旧配方套新要求。
        """
        payload = self.to_dict()
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def to_prompt_block(self) -> str:
        """给决策 LLM 的目标函数块。缺项如实写「未指定」，不替用户猜。"""
        lines = [
            "【剪辑意图 / 目标函数】",
            f"节奏：{self.pacing}",
            f"目标时长：{('%.2f 秒（允许偏差 %.2f 秒）' % (self.target_duration_sec, self.duration_tolerance_sec)) if self.target_duration_sec > 0 else '未指定'}",
            f"受众：{self.audience or '未指定'}",
            f"创作意图：{self.notes or '未指定'}",
            f"必须保留台词：{('、'.join(self.keep_lines)) if self.keep_lines else '无'}",
            f"禁改区间（时间线绝对秒）：{list(self.preserve_ranges) if self.preserve_ranges else '无'}",
            f"禁改片段：{list(self.protected_clip_ids) if self.protected_clip_ids else '无'}",
        ]
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target_duration_sec": float(self.target_duration_sec),
            "duration_tolerance_sec": float(self.duration_tolerance_sec),
            "pacing": self.pacing,
            "audience": self.audience,
            "notes": self.notes,
            "keep_lines": list(self.keep_lines),
            "protected_clip_ids": list(self.protected_clip_ids),
            "preserve_ranges": [list(p) for p in self.preserve_ranges],
            "tags": list(self.tags),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "EditIntent":
        d = dict(data or {})
        ranges = tuple(
            (float(a), float(b))
            for a, b in (tuple(p) for p in (d.get("preserve_ranges") or []) if len(tuple(p)) == 2)
        )
        return cls(
            target_duration_sec=float(d.get("target_duration_sec") or 0.0),
            duration_tolerance_sec=float(d.get("duration_tolerance_sec") or 3.0),
            pacing=str(d.get("pacing") or "normal"),
            audience=str(d.get("audience") or ""),
            notes=str(d.get("notes") or ""),
            keep_lines=tuple(str(x) for x in (d.get("keep_lines") or [])),
            protected_clip_ids=tuple(str(x) for x in (d.get("protected_clip_ids") or [])),
            preserve_ranges=ranges,
            tags=tuple(str(x) for x in (d.get("tags") or [])),
        )
