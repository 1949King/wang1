# -*- coding: utf-8 -*-
"""长篇剧本结构模型（WS-D「上游母版/长篇/立意」第一刀）。

本刀只做模型，不接线 UI/存储
============================
- 不 import PyQt6，不读文件、不写文件、不连数据库、不 print；
- 只有 dataclass 与纯函数：构造、校验、to_dict/from_dict 序列化；
- 剧本面板、项目存储、导出接线留给后续刀次；本模块只保证「结构能表达 + 坏数据如实报告」。

诚实失败纪律
============
- 不猜集数：create_script_doc 的 episodes 恒为空，只有 add_episode 显式加的集才存在；
- 不编造钩子：hook 缺省 "" 会进 validate 的 errors，绝不自动生成；
- 不猜时长：duration_target 缺省 0.0 表示「未填」，0 进 errors，不按常见集长补值；
- 不猜集号：add_episode 收到 <=0 或重复集号直接 ValueError，不重编号、不覆盖；
- 空 doc 合法：只有标题的 ScriptDoc 可创建、可往返，但 validate 会提示「剧集为空」；
- version 不自动递增：版本语义属于存储层，本模型只透传，不改成「看起来对」的值。

设计取舍
========
- add_episode 用 dataclasses.replace 返回新 doc，不改入参，便于上层做撤销/快照；
- episodes 由 add_episode 按 number 升序维护；直接构造出乱序 episodes 时 validate 报「未升序」；
- from_dict 只承诺吃 to_dict 的产物：畸形输入不猜、不强转，文本类落回 ""，数字类落回 0，
  由 validate_script_doc 统一曝光；非 dict 的 episode 条目跳过，不编造 Episode。
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence
from uuid import uuid4


def _text_or_empty(value: Any) -> str:
    """只接受 str；None / 数字 / 对象一律按空处理，避免把非正文冒充成标题。"""
    return value if isinstance(value, str) else ""


def _str_list(value: Any) -> List[str]:
    """只收 list/tuple 中的 str 项；空串保留原样（是否算缺失由 validate 判）。"""
    if not isinstance(value, (list, tuple)):
        return []
    return [item for item in value if isinstance(item, str)]


def _int_or_zero(value: Any) -> int:
    """只接受真 int（排除 bool）；其余落回 0，让 validate 报「集号非法」。"""
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return 0


def _float_or_zero(value: Any) -> float:
    """只接受 int/float（排除 bool）；其余落回 0.0，不猜时长。"""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return 0.0


def _has_text(value: Any) -> bool:
    """非空白 str 才算「填了」；空串 / 纯空格 / 非 str 都不算。"""
    return isinstance(value, str) and bool(value.strip())


def _is_positive_number(value: Any) -> bool:
    """>0 的真数字（排除 bool）；NaN 也判 False，交给 errors 曝光。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return value > 0


@dataclass
class Episode:
    """单集结构。缺省值代表「未填写」，不是「第 0 集 / 0 秒」这类合理默认。"""

    number: int = 0
    title: str = ""
    synopsis: str = ""
    beats: List[str] = field(default_factory=list)
    hook: str = ""
    duration_target: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """序列化为 JSON 友好 dict；beats 复制一份，避免外部改动共享列表。"""
        return {
            "number": self.number,
            "title": self.title,
            "synopsis": self.synopsis,
            "beats": list(self.beats),
            "hook": self.hook,
            "duration_target": self.duration_target,
        }

    @classmethod
    def from_dict(cls, data: Any) -> "Episode":
        """从 dict 还原；缺字段 / 错类型落回缺省值，不猜值、不修正。"""
        if not isinstance(data, dict):
            return cls()
        return cls(
            number=_int_or_zero(data.get("number")),
            title=_text_or_empty(data.get("title")),
            synopsis=_text_or_empty(data.get("synopsis")),
            beats=_str_list(data.get("beats")),
            hook=_text_or_empty(data.get("hook")),
            duration_target=_float_or_zero(data.get("duration_target")),
        )


@dataclass
class ScriptDoc:
    """一部长篇剧本的元信息 + 分集列表；本身不绑定任何存储层。"""

    doc_id: str = ""
    title: str = ""
    logline: str = ""
    genre: str = ""
    episodes: List[Episode] = field(default_factory=list)
    version: int = 1
    created_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """序列化为 JSON 友好 dict（episodes 逐集调用 Episode.to_dict）。"""
        return {
            "doc_id": self.doc_id,
            "title": self.title,
            "logline": self.logline,
            "genre": self.genre,
            "episodes": [episode.to_dict() for episode in self.episodes],
            "version": self.version,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Any) -> "ScriptDoc":
        """从 dict 还原；契约是吃 to_dict 的产物，畸形输入不猜、不抛。"""
        if not isinstance(data, dict):
            return cls()
        raw_episodes = data.get("episodes")
        episodes = (
            [Episode.from_dict(item) for item in raw_episodes if isinstance(item, dict)]
            if isinstance(raw_episodes, list)
            else []
        )
        version = data.get("version", 1)
        return cls(
            doc_id=_text_or_empty(data.get("doc_id")),
            title=_text_or_empty(data.get("title")),
            logline=_text_or_empty(data.get("logline")),
            genre=_text_or_empty(data.get("genre")),
            episodes=episodes,
            version=_int_or_zero(version),
            created_at=_text_or_empty(data.get("created_at")),
        )


def create_script_doc(title: str, logline: str = "", genre: str = "") -> ScriptDoc:
    """新建一部长篇剧本：episodes 恒为空（不猜集数），version=1，created_at 取当前 UTC。"""
    return ScriptDoc(
        doc_id=uuid4().hex,
        title=_text_or_empty(title),
        logline=_text_or_empty(logline),
        genre=_text_or_empty(genre),
        episodes=[],
        version=1,
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


def add_episode(
    doc: ScriptDoc,
    *,
    number: int,
    title: str = "",
    synopsis: str = "",
    beats: Optional[Sequence[str]] = None,
    hook: str = "",
    duration_target: float = 0.0,
) -> ScriptDoc:
    """追加一集并返回**新** ScriptDoc（不改入参），按 number 升序插入。

    只拦「结构性错误」：集号非正整数、集号重复、beats 类型不对。
    内容缺失（标题 / hook / 时长）**不拦**，交给 validate_script_doc 如实报 errors。
    duration_target 缺省 0.0 = 未填，不猜时长；显式传非数字同样落进 errors。
    """
    if not isinstance(doc, ScriptDoc):
        raise TypeError("add_episode 需要 ScriptDoc（不猜、不重建）")
    if not isinstance(number, int) or isinstance(number, bool) or number <= 0:
        raise ValueError(f"集号必须为正整数：收到 {number!r}（不猜起始集号）")
    if any(isinstance(episode, Episode) and episode.number == number for episode in doc.episodes):
        raise ValueError(f"集号 {number} 已存在：本模型不覆盖、不自动重编号")
    beat_list: List[str]
    if beats is None:
        beat_list = []
    elif isinstance(beats, str) or not isinstance(beats, (list, tuple)):
        raise ValueError("beats 需为字符串列表/元组（不把整段文本拆成单字）")
    elif any(not isinstance(beat, str) for beat in beats):
        raise ValueError("beats 每条都必须是 str（不把非文本冒充成分节）")
    else:
        beat_list = list(beats)
    episode = Episode(
        number=number,
        title=_text_or_empty(title),
        synopsis=_text_or_empty(synopsis),
        beats=beat_list,
        hook=_text_or_empty(hook),
        duration_target=duration_target if isinstance(duration_target, (int, float)) else 0.0,
    )
    return replace(doc, episodes=sorted([*doc.episodes, episode], key=lambda item: item.number))


def validate_script_doc(doc: ScriptDoc) -> List[str]:
    """校验剧本结构，返回人可读错误列表（**不抛异常、不自动修复**）；空列表 = 通过。

    规则：title 非空；episodes 非空；每集 number 为正整数且唯一、episodes 按 number 升序；
    每集 title / hook 非空；duration_target 必须是 >0 的数字（缺省 0 = 未填，进 errors）。
    空 doc（无任何集）是合法对象，但会得到「剧集为空」提示——不猜集数、不补样板集。
    """
    if not isinstance(doc, ScriptDoc):
        return [f"传入对象不是 ScriptDoc（{type(doc).__name__}）：无法校验，不猜、不修正"]
    errors: List[str] = []
    if not _has_text(doc.title):
        errors.append("标题为空：ScriptDoc.title 必须有值（不猜标题）")
    episodes = doc.episodes if isinstance(doc.episodes, list) else []
    if not episodes:
        errors.append("剧集为空：尚未添加任何 Episode（不猜集数）")
    numbers: List[Any] = []
    for index, episode in enumerate(episodes, start=1):
        if not isinstance(episode, Episode):
            errors.append(f"第 {index} 项不是 Episode 实例：无法校验（不猜）")
            continue
        numbers.append(episode.number)
        position = f"第 {index} 集（number={episode.number!r}）"
        if (
            not isinstance(episode.number, int)
            or isinstance(episode.number, bool)
            or episode.number <= 0
        ):
            errors.append(f"{position} 集号非法：必须为正整数（不猜集号）")
        if not _has_text(episode.title):
            errors.append(f"{position} 标题为空：不猜集标题")
        if not _has_text(episode.hook):
            errors.append(f"{position} hook 为空：不编造钩子，需人工填写")
        if not _is_positive_number(episode.duration_target):
            errors.append(
                f"{position} duration_target={episode.duration_target!r}："
                "缺省 0 表示未填，不猜时长，需人工补 >0 秒"
            )
    int_numbers = [
        number for number in numbers if isinstance(number, int) and not isinstance(number, bool)
    ]
    counts: Dict[int, int] = {}
    for number in int_numbers:
        counts[number] = counts.get(number, 0) + 1
    duplicates = sorted(number for number, count in counts.items() if count > 1)
    if duplicates:
        errors.append(f"集号重复：{duplicates}（number 必须唯一，不自动重编号）")
    if int_numbers and int_numbers != sorted(int_numbers):
        errors.append(f"剧集未按 number 升序排列：{int_numbers}")
    return errors


def to_dict(doc: ScriptDoc) -> Dict[str, Any]:
    """模块级薄封装，等价于 ``doc.to_dict()``，方便纯函数式调用。"""
    return doc.to_dict()


def from_dict(data: Any) -> ScriptDoc:
    """模块级薄封装，等价于 ``ScriptDoc.from_dict(data)``。"""
    return ScriptDoc.from_dict(data)
