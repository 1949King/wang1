# -*- coding: utf-8 -*-
"""Windows WMI 查询助手（刀 A5 / A-14，2026-10-05）。

为什么要有这个模块
==================
项目里三处用 `wmic` 取 Windows 硬件信息，而 **`wmic` 在 Win11 已弃用**（微软宣布逐步移除），
同时它也是沙箱环境的噪音源。同一件事写三遍还会各自漂移，故收成一处：

  | 调用方 | 取什么 | 用途 |
  |---|---|---|
  | `config_manager._get_machine_id` | `Win32_ComputerSystemProduct.UUID` | 机器码 → **加密密钥派生** |
  | `auth._get_device_id` | 同上 | 设备指纹 → 授权绑定 |
  | `gpu_acceleration._detect_intel` | `Win32_VideoController.Name` | 显卡识别 |

★ **最要紧的一条纪律：机器码/设备指纹必须逐字不变**
--------------------------------------------------
前两处的取值会参与 **sha256 指纹派生**：
  · `config_manager` 用它派生的密钥**加密过用户已保存的配置**（API Keys 等）；
  · `auth` 用它做**设备绑定/授权**。
⇒ 一旦派生字符串变了，**已保存的加密配置会解不开、已绑定设备会失效**（用户的真实数据损失）。
所以本模块**只换查询机制，不换取值形状**：

  · `machine_uuid()` 返回**UUID 值本身**（与旧代码过滤掉 `UUID` 表头后取的那一行同值）；
  · `wmic_stdout_shape()` 专门给 `auth` 用 —— 它当年取的是 `wmic` 输出的 `stdout.strip()`，
    即 **`"UUID\\n<值>"`** 这个"带表头"的怪字符串。为了指纹不变，这里**照样复现它**
    （看着奇怪，但它是承重的历史契约，不是笔误）。

机制：**CIM 优先 + wmic 兜底**
-----------------------------
· CIM（`powershell -NoProfile -Command "Get-CimInstance ..."`）：Win11 可用，不再有弃用风险；
· wmic 兜底：老系统 / PowerShell 组策略受限的环境。
两者读的是同一个 WMI 属性 ⇒ 取值一致；顺序调整不改变派生字符串（见上）。

所有函数**绝不抛异常**：不可用就返回 `None` / `[]`，由调用方决定降级（诚实失败不在这里做）。
"""
from __future__ import annotations

import logging
import platform
import subprocess
from typing import List, Optional

logger = logging.getLogger(__name__)

_TIMEOUT = 5.0

# wmic 会打印的表头（属性名本身）。CIM 不会，统一过滤以保证两种来源同形。
_HEADERS = {"Name", "UUID", "SerialNumber", "IdentifyingNumber"}

# wmic 表头的列宽填充（实测："UUID" 后跟 34 个空格，表头总宽 38）。
# 仅 `machine_uuid_wmic_shape()` 用 —— 那是复现历史指纹用的，见该函数说明。
_WMIC_HEADER_PAD = 34


def _no_window_flags() -> int:
    if platform.system() == "Windows":
        return getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return 0


def _run(cmd: List[str]) -> Optional[str]:
    """跑一条命令并返回 stdout（失败/超时返回 None，绝不抛）。"""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=_TIMEOUT, creationflags=_no_window_flags())
    except Exception as e:
        logger.debug("[win_query] 命令失败 %s: %s", cmd[0], e)
        return None
    if getattr(r, "returncode", 1) != 0:
        return None
    return r.stdout or ""


def _clean_lines(out: str) -> List[str]:
    """按行清洗：去空白、丢空行、**丢掉 wmic 的表头行**（CIM 没有表头）。

    wmic 输出形如 ``"Name\\nIntel(R) UHD Graphics\\n\\n"``；CIM 的
    ``Select -ExpandProperty`` 只返回值行 ⇒ 统一在这里抹平差异。
    """
    lines: List[str] = []
    for raw in (out or "").split("\n"):
        s = raw.strip()
        if s and s not in _HEADERS:
            lines.append(s)
    return lines


def cim_lines(class_name: str, prop: str) -> List[str]:
    """用 PowerShell CIM 取一个属性的所有实例值（一行一个）。"""
    if platform.system() != "Windows":
        return []
    cmd = [
        "powershell", "-NoProfile", "-NonInteractive", "-Command",
        f"(Get-CimInstance -ClassName {class_name}).{prop}",
    ]
    out = _run(cmd)
    return _clean_lines(out) if out is not None else []


def wmic_lines(class_name: str, prop: str) -> List[str]:
    """用 wmic 取一个属性的所有实例值（老系统兜底路径）。"""
    if platform.system() != "Windows":
        return []
    out = _run(["wmic", "path", class_name, "get", prop])
    return _clean_lines(out) if out is not None else []


def wmi_lines(class_name: str, prop: str) -> List[str]:
    """**CIM 优先、wmic 兜底**取属性值列表（两者都不可用 ⇒ 空列表）。"""
    lines = cim_lines(class_name, prop)
    if lines:
        return lines
    lines = wmic_lines(class_name, prop)
    if lines:
        logger.debug("[win_query] CIM 不可用，已回退 wmic：%s.%s", class_name, prop)
    return lines


def machine_uuid() -> Optional[str]:
    """机器 UUID（`Win32_ComputerSystemProduct.UUID` 的值本身）。

    ⚠️ 该值参与**机器码/加密密钥派生**：返回值必须与历史实现（wmic 过滤表头后的那一行）
    逐字一致，否则用户已保存的加密配置会解不开。故这里**不做任何大小写/格式归一化**。
    """
    lines = wmi_lines("Win32_ComputerSystemProduct", "UUID")
    return lines[0] if lines else None


def machine_uuid_wmic_shape() -> Optional[str]:
    """**历史形状**的机器 UUID：``"UUID" + 34空格 + "\\n\\n" + <值>``。

    `auth._get_device_id` 当年取的是 ``wmic stdout.strip()`` —— 即**带表头、且表头被
    wmic 填充到列宽**的字符串。2026-10-05 用**等价性测试**实测出确切形状：

        repr → 'UUID                                  \\n\\n13558300-B6AE-...'
               └─ "UUID" + **34 个空格**（表头总宽 38）┘ └ 两个换行 ┘ └ 值 ┘

    为什么连空格都要复现：该字符串参与**设备指纹 sha256**，参与**授权绑定**——
    少一个空格就是另一个设备。**这不是笔误，是承重契约。**

    ⚠️ 也说明这个指纹**本来就脆**（依赖 wmic 的列宽格式）。`test_win_query.py` 里有一条
    **等价性测试**：只要有 wmic 就现场对比本函数与真实 `wmic stdout.strip()`，一旦不等立刻红灯，
    而不是让用户的设备绑定**静默失效**。
    """
    uuid = machine_uuid()
    return f"UUID{' ' * _WMIC_HEADER_PAD}\n\n{uuid}" if uuid else None
