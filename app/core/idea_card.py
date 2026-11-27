# -*- coding: utf-8 -*-
"""选题立意卡（WS-D「上游母版/长篇/立意」第一刀）。

本刀只做模型，不接线 UI/存储
============================
- 不 import PyQt6/PySide6，不读文件、不写文件、不连数据库、不 print；
- 只有 dataclass 与纯函数：构造、校验、set_status、to_dict/from_dict 序列化；
- 立意面板、项目存储、AI 生成接线留给后续刀次，本模块只保证「卡能表达 + 坏数据如实报告」。

诚实失败纪律
============
- 不猜题材 / 受众：create_idea_card 的 genre / audience 缺省 ""，绝不自动补「都市 / 女性向」；
- 空值进 errors：题材、受众没填会被 validate_idea_card 报错，而不是找个默认值糊过去；
- status 只收 draft / ready / blocked：set_status 收到别的值直接 ValueError，不静默回落；
- blocked 必须有 compliance_notes：没有人工写下的合规卡点就报错，绝不臆造备注；
- status 非法值不纠正：from_dict 遇到非法 status 原样保留，交给 validate 报错，
  避免把「草稿」冒充成合法状态；缺 status 才用新建态 draft。

设计取舍
========
- 一律返回新对象（dataclasses.replace），不改入参，便于上层做撤销/快照；
- ready 不额外要求 compliance_notes（只有 blocked 需要），合规备注按状态按需填写；
- tone 允许留空（风格未定不算错误），与 genre / audience 的硬性要求区分开；
- from_dict 只承诺吃 to_dict 的产物：畸形输入不猜、不强转，文本类落回 ""。
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional, Sequence
from uuid import uuid4

# 唯一合法的三种状态；顺序即 UI 上的自然流转顺序
IDEA_CARD_STATUSES = ("draft", "ready", "blocked")


def _text_or_empty(value: Any) -> str:
    """只接受 str；None / 数字 / 对象一律按空处理，避免把非正文冒充成卡面文字。"""
    return value if isinstance(value, str) else ""


def _str_list(value: Any) -> List[str]:
    """只收 list/tuple 中的 str 项；其余类型跳过（不把对象 str() 成备注）。"""
    if not isinstance(value, (list, tuple)):
        return []
    return [item for item in value if isinstance(item, str)]


def _has_text(value: Any) -> bool:
    """非空白 str 才算「填了」；空串 / 纯空格 / 非 str 都不算。"""
    return isinstance(value, str) and bool(value.strip())


def _non_blank_notes(notes: Any) -> List[str]:
    """取真正写了内容的合规备注（去空白项）；非列表 → 空。"""
    if not isinstance(notes, list):
        return []
    return [note for note in notes if _has_text(note)]


@dataclass
class IdeaCard:
    """一张选题立意卡；status 只应是 IDEA_CARD_STATUSES 之一，合法性由 validate 判定。"""

    card_id: str = ""
    title: str = ""
    logline: str = ""
    genre: str = ""
    audience: str = ""
    tone: str = ""
    compliance_notes: List[str] = field(default_factory=list)
    status: str = "draft"

    def to_dict(self) -> Dict[str, Any]:
        """序列化为 JSON 友好 dict；compliance_notes 复制一份，避免共享列表被外部改动。"""
        return {
            "card_id": self.card_id,
            "title": self.title,
            "logline": self.logline,
            "genre": self.genre,
            "audience": self.audience,
            "tone": self.tone,
            "compliance_notes": list(self.compliance_notes),
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: Any) -> "IdeaCard":
        """从 dict 还原；契约是吃 to_dict 的产物，畸形输入不猜、不抛。

        缺 status → 新建态 draft；status 是字符串就原样保留（非法值交给 validate 报错）。
        """
        if not isinstance(data, dict):
            return cls()
        raw_status = data.get("status", "draft")
        return cls(
            card_id=_text_or_empty(data.get("card_id")),
            title=_text_or_empty(data.get("title")),
            logline=_text_or_empty(data.get("logline")),
            genre=_text_or_empty(data.get("genre")),
            audience=_text_or_empty(data.get("audience")),
            tone=_text_or_empty(data.get("tone")),
            compliance_notes=_str_list(data.get("compliance_notes")),
            status=raw_status if isinstance(raw_status, str) else "",
        )


def create_idea_card(
    title: str,
    logline: str = "",
    genre: str = "",
    audience: str = "",
    tone: str = "",
    compliance_notes: Optional[Sequence[str]] = None,
) -> IdeaCard:
    """新建一张立意卡：status 固定为新建态 draft，题材 / 受众缺省留空（不猜）。"""
    return IdeaCard(
        card_id=uuid4().hex,
        title=_text_or_empty(title),
        logline=_text_or_empty(logline),
        genre=_text_or_empty(genre),
        audience=_text_or_empty(audience),
        tone=_text_or_empty(tone),
        compliance_notes=_str_list(compliance_notes),
        status="draft",
    )


def set_status(card: IdeaCard, status: str) -> IdeaCard:
    """返回状态更新后的**新**卡（不改入参）；只收三值，非法值直接 ValueError。

    本函数只管状态值本身；blocked 是否具备 compliance_notes 由 validate_idea_card 判定，
    因此允许先置 blocked 再由校验提示补备注，不在这里替用户编造合规理由。
    """
    if not isinstance(card, IdeaCard):
        raise TypeError("set_status 需要 IdeaCard（不猜、不重建）")
    if status not in IDEA_CARD_STATUSES:
        raise ValueError(
            f"非法 status：{status!r}；只收 {' / '.join(IDEA_CARD_STATUSES)}（不猜业务状态）"
        )
    return replace(card, status=status)


def validate_idea_card(card: IdeaCard) -> List[str]:
    """校验立意卡，返回人可读错误列表（**不抛异常、不自动修复**）；空列表 = 通过。

    规则：title / logline 非空；genre / audience 非空（不猜题材受众）；
    status ∈ {draft, ready, blocked}；status=blocked 时 compliance_notes 至少一条非空备注。
    tone 允许留空（风格未定不是错误）。
    """
    if not isinstance(card, IdeaCard):
        return [f"传入对象不是 IdeaCard（{type(card).__name__}）：无法校验，不猜、不修正"]
    errors: List[str] = []
    if not _has_text(card.title):
        errors.append("标题为空：IdeaCard.title 必须有值（不猜标题）")
    if not _has_text(card.logline):
        errors.append("logline 为空：一句话立意必须有值（不猜、不补写）")
    if not _has_text(card.genre):
        errors.append("题材为空：不猜题材，需人工选择（不自动补「都市/悬疑」等）")
    if not _has_text(card.audience):
        errors.append("受众为空：不猜受众，需人工写明（不自动补「女性向」等）")
    if card.status not in IDEA_CARD_STATUSES:
        allowed = " / ".join(IDEA_CARD_STATUSES)
        errors.append(f"status={card.status!r} 非法：只收 {allowed}，不猜业务状态")
    elif card.status == "blocked" and not _non_blank_notes(card.compliance_notes):
        errors.append("status=blocked 但 compliance_notes 为空：合规卡点必须人工写明，不臆造备注")
    return errors


def to_dict(card: IdeaCard) -> Dict[str, Any]:
    """模块级薄封装，等价于 ``card.to_dict()``，方便纯函数式调用。"""
    return card.to_dict()


def from_dict(data: Any) -> IdeaCard:
    """模块级薄封装，等价于 ``IdeaCard.from_dict(data)``。"""
    return IdeaCard.from_dict(data)
