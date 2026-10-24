# -*- coding: utf-8 -*-
"""进入软件时的**首个提示**（配置加密 / 设备绑定 的免责与风险告知）。

为什么需要这个提示（背景，须与实现一致）
========================================
本会用**机器指纹**（由系统信息算出的特征值）派生密钥：
  · **加密保存**用户配置（如各家 API Key）；
  · 做**设备绑定**（授权跟着这台机器走）。

指纹一旦变化，**用旧指纹加密的内容就解不开**。会改变指纹的情况包括：换硬件（主板/网卡/CPU）、
重装或更换操作系统、**系统查询接口变化**（例如 Win11 移除 `wmic`、改为 CIM 查询）、
虚拟机迁移/克隆等。后果是「配置像丢了」「授权要重新绑定」。

2026-10-06 的真实例子：把三处 `wmic` 查询换成 CIM 优先（`app/core/win_query.py`）时，
虽然已用**等价性测试**证明取值逐字未变（`test_win_query.py`），但这恰恰说明
**取值的形状是承重的** —— 任何后续改动（包括操作系统自己变）都可能让旧密文解不开。

于是本模块负责在**首启**把这件事讲清楚，并明确**责任边界**：
由此产生的数据丢失/使用中断，**与作者本人及本项目无关**，请用户自行备份。

设计要点
========
· **版本化记忆**：状态存 `data/first_run_notice.json`（本项目运行态惯例）。
  文本有实质变化时把 `NOTICE_VERSION` +1 ⇒ 老用户会**再看一次**（而不是悄悄改条款）。
· **失败即显示**：状态文件缺失/损坏/读不动 ⇒ 一律**显示**（宁可多提示一次，不可漏告知）。
· **纯逻辑与 UI 分离**：本模块不 import Qt，可被单测直接覆盖；Qt 弹窗在
  `app/modules/lego/notice_dialog.py`。
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# 文本/条款有实质变化时 +1（老用户会再看到一次，而不是被静默改条款）
NOTICE_VERSION = 1

_STATE_REL = os.path.join("data", "first_run_notice.json")

# ── 提示正文（用户可见）──────────────────────────────────────────────
NOTICE_TITLE = "重要提示 · 配置加密与设备绑定"

NOTICE_BODY = """本软件会用**这台机器**的指纹（由系统信息算出的特征值）来做两件事：

  · 加密保存你的配置（例如各家 API Key）；
  · 设备绑定（授权跟着这台机器走）。

⚠️ 这意味着：**机器指纹一旦变化，用旧指纹加密的内容就解不开了。**

常见会让指纹变化的情况：
  · 更换或加装硬件（主板、网卡、CPU 等）；
  · 重装 / 更换操作系统，或换用另一套系统镜像；
  · 系统查询接口变化（例如 Win11 下 wmic 被移除、改走 CIM 查询）；
  · 虚拟机迁移 / 克隆、云主机重建；
  · 手动修改或清理了系统标识。

可能出现的结果：
  · 已保存的 API Key 等**加密配置无法解密**（看起来像"配置丢了"）；
  · **设备绑定失效**，需要重新授权。

⚠️ 以上因指纹变化导致的**数据丢失或使用中断，与作者本人及本项目无关**。

建议：在换机器 / 重装系统**之前**，先自行导出或抄录重要配置（API Key、授权信息等）做好备份。"""


def repo_root() -> str:
    """仓库根目录（本文件位于 <root>/app/core/ 下）。"""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def state_path() -> str:
    """首启提示的状态文件路径（`data/first_run_notice.json`）。"""
    return os.path.join(repo_root(), _STATE_REL)


def load_state(path: Optional[str] = None) -> Dict[str, Any]:
    """读状态；缺失/损坏一律返回空 dict（**不抛异常**）。"""
    p = path or state_path()
    try:
        with open(p, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as e:
        logger.debug("[first_run_notice] 状态文件不可读（按未确认处理）: %s", e)
        return {}


def should_show(path: Optional[str] = None, version: int = NOTICE_VERSION) -> bool:
    """是否应显示首个提示。

    判据：已确认的版本 **>= 当前版本** 才不显示；其余情况（含文件损坏）都显示。
    —— 宁可多提示一次，也不可漏告知（这是免责告知，不是可选广告）。
    """
    st = load_state(path)
    try:
        ack = int(st.get("acknowledged_version") or 0)
    except (TypeError, ValueError):
        ack = 0
    return ack < int(version)


def mark_acknowledged(path: Optional[str] = None, version: int = NOTICE_VERSION) -> bool:
    """记录「用户已阅读并知晓」；写失败返回 False（但**不抛**，不阻断启动）。"""
    p = path or state_path()
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        payload = {
            "acknowledged_version": int(version),
            "acknowledged_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.warning("[first_run_notice] 状态写入失败（不影响使用，下次仍会提示）: %s", e)
        return False


def full_text() -> str:
    """标题 + 正文（供弹窗与「帮助」里再次查看）。"""
    return NOTICE_BODY
