"""app/tests/test_win_query.py — Windows WMI 查询助手（刀 A5 / A-14，2026-10-05）。

**为什么这组测试值得写**：这三处查询里有两处的结果参与 **sha256 指纹派生** ——
`config_manager` 用它派生的密钥**加密过用户已保存的配置**，`auth` 用它做**设备绑定**。
换查询机制时只要取值形状变一个字符，用户就会「已存的 API Key 解不开 / 设备突然未授权」，
**而且不会报错**（只是默默换了指纹）。所以这里既测解析，也测**与真机旧实现逐字等价**。
"""
import platform
import subprocess

import pytest

from app.core import win_query as wq

IS_WIN = platform.system() == "Windows"


# ─────────────────────── ① 解析：两种来源同形 ───────────────────────

def test_wmic_header_is_stripped():
    """wmic 会打印属性名表头；CIM 不会 ⇒ 统一过滤，保证两种来源同形。"""
    wmic_out = "Name\nIntel(R) UHD Graphics\n\n"
    assert wq._clean_lines(wmic_out) == ["Intel(R) UHD Graphics"]


def test_cim_output_kept_as_is():
    assert wq._clean_lines("Intel(R) UHD Graphics\r\n") == ["Intel(R) UHD Graphics"]


def test_blank_and_padded_lines_dropped():
    """wmic 的表头会被填充到列宽（空格）—— 空白必须丢掉，不能当成"一个值"。"""
    out = "UUID                                  \n\n13558300-B6AE-11EE-89A0-92E22C596500\n\n"
    assert wq._clean_lines(out) == ["13558300-B6AE-11EE-89A0-92E22C596500"]


def test_multi_value_order_preserved():
    assert wq._clean_lines("A\nB\nC\n") == ["A", "B", "C"]


def test_empty_output():
    assert wq._clean_lines("") == []
    assert wq._clean_lines("\n\n") == []


# ─────────────────────── ② 不抛异常（诚实降级）───────────────────────

def test_missing_command_is_safe(monkeypatch):
    """命令不存在/超时 ⇒ 返回空，绝不抛（调用方各自降级）。"""
    def boom(*a, **k):
        raise FileNotFoundError("no such command")
    monkeypatch.setattr(subprocess, "run", boom)
    assert wq.cim_lines("X", "Y") == [] or not IS_WIN
    assert wq.wmic_lines("X", "Y") == [] or not IS_WIN
    assert wq.wmi_lines("X", "Y") == []
    assert wq.machine_uuid() is None


def test_non_windows_returns_empty(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    assert wq.cim_lines("X", "Y") == []
    assert wq.wmic_lines("X", "Y") == []
    assert wq.machine_uuid() is None


def test_cim_failure_falls_back_to_wmic(monkeypatch):
    """CIM 拿不到 ⇒ 回退 wmic（老系统 / PowerShell 受限环境）。"""
    monkeypatch.setattr(wq, "cim_lines", lambda c, p: [])
    monkeypatch.setattr(wq, "wmic_lines", lambda c, p: ["FALLBACK"])
    assert wq.wmi_lines("X", "Y") == ["FALLBACK"]


def test_cim_success_does_not_call_wmic(monkeypatch):
    called = {"n": 0}

    def _wmic(c, p):
        called["n"] += 1
        return ["SHOULD-NOT-BE-USED"]

    monkeypatch.setattr(wq, "cim_lines", lambda c, p: ["CIM-VALUE"])
    monkeypatch.setattr(wq, "wmic_lines", _wmic)
    assert wq.wmi_lines("X", "Y") == ["CIM-VALUE"]
    assert called["n"] == 0


# ─────────────────────── ③ 历史形状（承重契约）───────────────────────

def test_wmic_shape_layout(monkeypatch):
    """`"UUID" + 34空格 + "\\n\\n" + 值` —— 少一个空格就是"另一台设备"。"""
    monkeypatch.setattr(wq, "machine_uuid", lambda: "AAA-BBB")
    assert wq.machine_uuid_wmic_shape() == "UUID" + " " * 34 + "\n\nAAA-BBB"


def test_wmic_shape_none_when_unavailable(monkeypatch):
    monkeypatch.setattr(wq, "machine_uuid", lambda: None)
    assert wq.machine_uuid_wmic_shape() is None


# ─────────────────────── ④ ★ 与真机旧实现逐字等价（最重要）───────────────────────

@pytest.mark.skipif(not IS_WIN, reason="仅 Windows")
def test_equivalence_with_live_wmic_config_manager():
    """config_manager 旧公式（过滤表头取首个非空行）== `machine_uuid()`。

    这条测试就是**防指纹静默漂移**的看门人：不等 ⇒ 已保存的加密配置会解不开。
    """
    try:
        r = subprocess.run(["wmic", "csproduct", "get", "UUID"],
                           capture_output=True, text=True, timeout=10)
    except Exception:
        pytest.skip("本机无 wmic（Win11 移除后属预期）")
    if getattr(r, "returncode", 1) != 0 or not (r.stdout or "").strip():
        pytest.skip("wmic 不可用")
    old = [l.strip() for l in r.stdout.split("\n") if l.strip() and l.strip() != "UUID"]
    if not old:
        pytest.skip("wmic 无输出")
    assert old[0] == wq.machine_uuid(), "机器码取值变了 ⇒ 已保存的加密配置会解不开！"


@pytest.mark.skipif(not IS_WIN, reason="仅 Windows")
def test_equivalence_with_live_wmic_auth_shape():
    """auth 旧公式（`wmic stdout.strip()`）== `machine_uuid_wmic_shape()`。

    旧形状含 wmic 表头的**列宽填充 + 两个换行**；这条测试把那个"怪形状"钉住。
    """
    try:
        r = subprocess.run(["wmic", "csproduct", "get", "UUID"],
                           capture_output=True, text=True, timeout=10)
    except Exception:
        pytest.skip("本机无 wmic（Win11 移除后属预期）")
    if getattr(r, "returncode", 1) != 0 or not (r.stdout or "").strip():
        pytest.skip("wmic 不可用")
    assert r.stdout.strip() == wq.machine_uuid_wmic_shape(), \
        "设备指纹形状变了 ⇒ 已绑定设备会失效！"


@pytest.mark.skipif(not IS_WIN, reason="仅 Windows")
def test_cim_and_wmic_agree_on_uuid():
    """两种来源读同一个 WMI 属性 ⇒ 取值必须一致（否则换源就换了指纹）。"""
    cim = wq.cim_lines("Win32_ComputerSystemProduct", "UUID")
    wmic = wq.wmic_lines("Win32_ComputerSystemProduct", "UUID")
    if not cim or not wmic:
        pytest.skip("本机某一来源不可用")
    assert cim[0] == wmic[0]
