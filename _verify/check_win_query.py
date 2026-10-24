# -*- coding: utf-8 -*-
"""WMI 查询统一守卫（刀 A5 / A-14，2026-10-05）。

钉死三件事 —— 每件都以「悄悄坏」的方式害人：

  ① **三处查询统一走 `app/core/win_query.py`**，不得再有文件**直接 spawn `wmic`**
     （wmic 在 Win11 已弃用；分散实现必然各自漂移）。
  ② **指纹形状是承重契约**：`_WMIC_HEADER_PAD = 34` 与 `machine_uuid_wmic_shape()`
     的 `"UUID"+填充+"\\n\\n"+值` 布局不能改 —— 它参与设备指纹 sha256，
     少一个空格就是「另一台设备」（已绑定设备会静默失效）。
  ③ **等价性测试必须存在**（`test_win_query.py` 里对真机 wmic 的逐字对比）——
     这是唯一能在 wmic 格式变化时**替用户喊停**的东西。

零依赖：只读源码。
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WIN_QUERY = os.path.join("app", "core", "win_query.py")
TEST_FILE = os.path.join("app", "tests", "test_win_query.py")
# 允许出现 wmic 字面量的地方：统一助手里（兜底路径）与它自己的测试
ALLOW_WMIC = {WIN_QUERY, TEST_FILE}

_fails = []


def _fail(msg: str) -> None:
    _fails.append(msg)


def _read(rel: str) -> str:
    p = os.path.join(ROOT, rel)
    if not os.path.isfile(p):
        _fail(f"文件缺失：{rel}")
        return ""
    return open(p, encoding="utf-8").read()


def check_no_scattered_wmic() -> None:
    """① 除统一助手与其测试外，任何 .py 都不得直接调 wmic。"""
    offenders = []
    for sub in ("app",):
        for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT, sub)):
            dirnames[:] = [d for d in dirnames if d not in ("__pycache__", "temp")]
            for fn in filenames:
                if not fn.endswith(".py"):
                    continue
                rel = os.path.relpath(os.path.join(dirpath, fn), ROOT)
                if rel in ALLOW_WMIC:
                    continue
                txt = open(os.path.join(dirpath, fn), encoding="utf-8", errors="ignore").read()
                # 只看「真的把它当命令跑」的写法，避免误报注释里的说明
                if re.search(r"""["']wmic["']""", txt) and "subprocess" in txt:
                    offenders.append(rel)
    if offenders:
        for o in sorted(set(offenders)):
            _fail(f"① {o} 仍直接 spawn wmic —— 应改走 app/core/win_query.py（CIM 优先 + wmic 兜底）")


def check_fingerprint_contract() -> None:
    """② 指纹形状常量与布局不得改。"""
    src = _read(WIN_QUERY)
    if not src:
        return
    if "_WMIC_HEADER_PAD = 34" not in src:
        _fail("② 指纹表头填充常量被改（wmic 表头实测 34 空格；改它 = 换指纹 = 老用户设备失效）")
    if 'f"UUID{\' \' * _WMIC_HEADER_PAD}\\n\\n{uuid}"' not in src:
        _fail("② machine_uuid_wmic_shape() 的布局被改（必须是 UUID+填充+两换行+值）")
    for fn in ("def machine_uuid(", "def machine_uuid_wmic_shape("):
        if fn not in src:
            _fail(f"② 缺 {fn}）—— 指纹取值的唯一来源")


def check_equivalence_tests_present() -> None:
    """③ 与真机 wmic 的逐字等价测试必须存在（防静默漂移的看门人）。"""
    src = _read(TEST_FILE)
    if not src:
        return
    for probe in ("test_equivalence_with_live_wmic_config_manager",
                  "test_equivalence_with_live_wmic_auth_shape"):
        if probe not in src:
            _fail(f"③ 缺等价性测试 {probe} —— 指纹漂移将无人发现")
    if "r.stdout.strip() == wq.machine_uuid_wmic_shape()" not in src:
        _fail("③ auth 形状的等价断言被弱化（必须是逐字相等）")


def check_call_sites_use_helper() -> None:
    """① 三个原调用点必须已改为 import win_query。"""
    for rel in (os.path.join("app", "core", "config_manager.py"),
                os.path.join("app", "modules", "lego", "auth.py"),
                os.path.join("app", "core", "gpu_acceleration.py")):
        src = _read(rel)
        if "win_query" not in src:
            _fail(f"① {rel} 未走统一 WMI 助手")


def main() -> int:
    print("=" * 62)
    print("WMI 查询统一守卫（刀 A5 / A-14）")
    print("=" * 62)
    for fn in (check_no_scattered_wmic, check_fingerprint_contract,
               check_equivalence_tests_present, check_call_sites_use_helper):
        try:
            fn()
        except Exception as e:
            _fail(f"{fn.__name__} 抛异常: {type(e).__name__}: {e}")
    if _fails:
        print("✗ 失败项：")
        for p in _fails:
            print(f"  - {p}")
        return 1
    print("OK wmic 已统一（CIM 优先 + 兜底）· 指纹形状锁定 · 等价性测试在位")
    return 0


if __name__ == "__main__":
    sys.exit(main())
