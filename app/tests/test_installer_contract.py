# -*- coding: utf-8 -*-
"""安装包脚本的契约守卫。

为什么需要这组测试
==================
`scripts/installer.nsi` 出过两个**不报错就坏掉**的问题，都属于「编译成功、
装完才发现」的类型：

  1. **版本号写死**：`!define APP_VERSION "4.10.3"` 与 `app/version.py` 的
     4.47.0 脱节 37 个次版本。文件名错只是表面，注册表 DisplayVersion 也写错，
     用户在「应用和功能」里看到假版本,排查时按版本对不上号。
  2. **无 BOM**：NSIS 3 在 `Unicode true` 下靠 BOM 判编码，无 BOM 会被按
     ANSI(GBK) 解释 ⇒ 安装包界面中文全乱码，而 makensis **退出码是 0**。

这两条都不是「读代码能看出来」的：脚本本身语法正确、编译通过。
所以钉成断言，改坏立刻红。

不测什么
--------
不跑 makensis（CI 不该依赖 NSIS 安装）、不读产物 exe。
只测「脚本源码里不该出现的东西」和「编码前缀」。
真编译验证由 `build_release.py --installer` 负责。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
NSI = ROOT / "scripts" / "installer.nsi"
LICENSE = ROOT / "LICENSE.txt"


def _raw(p: Path) -> bytes:
    assert p.exists(), f"缺文件：{p}"
    return p.read_bytes()


def _text(p: Path) -> str:
    """按 UTF-8 解码并去掉 BOM。"""
    raw = _raw(p)
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    return raw.decode("utf-8")


# ── 编码 ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("path", [NSI, LICENSE], ids=["installer.nsi", "LICENSE.txt"])
def test_utf8_bom_present(path: Path):
    """必须带 UTF-8 BOM。

    无 BOM 时 makensis 按 GBK 解释字节流，编译不报错、产出的安装包中文全乱码。
    实测反例：同一份脚本只删掉这 3 个字节，预处理输出里的中文全部变成乱码。
    """
    assert _raw(path).startswith(b"\xef\xbb\xbf"), (
        f"{path.name} 缺 UTF-8 BOM —— NSIS 会按 ANSI/GBK 读，安装包界面中文将全部乱码"
        f"（且 makensis 退出码仍为 0，不会报错）"
    )


# ── 版本号单一真源 ────────────────────────────────────────────────────

def test_no_hardcoded_app_version():
    """脚本里不许出现**看起来像真版本号**的 APP_VERSION 字面量。

    允许的唯一写法是 `!include "..\\dist\\build_info.nsh"`（版本由
    build_release.py 从 app/version.py 读出后注入）。

    特例：`0.0.0` 是缺 build_info.nsh 时的显式兜底，配合 !warning 使用。
    它不可能被误认成真版本，所以放行 —— 判据是「像不像真版本」，不是「有没有 define」。
    （第一版判据写成「只要出现 !define APP_VERSION 就红」，
     结果被这个合法兜底绊倒 —— 说明判据要比症状更精确。）
    """
    txt = _text(NSI)
    found = re.findall(r'^\s*!define\s+APP_VERSION\s+"([^"]*)"', txt, flags=re.MULTILINE)
    hard = [v for v in found if re.match(r"^\d+\.\d+", v) and v != "0.0.0"]
    assert not hard, (
        f"installer.nsi 里出现了写死的版本号 {hard}。"
        "版本号必须由 scripts/build_release.py 生成 dist/build_info.nsh 注入，"
        "否则会和 app/version.py 脱钩（历史上脱节过 37 个次版本）"
    )


def test_build_info_is_included():
    """必须真的 include 那个生成的版本文件，否则版本会回退到 0.0.0。"""
    assert '!include "..\\dist\\build_info.nsh"' in _text(NSI).replace("/", "\\")


def test_fallback_version_is_loud():
    """缺 build_info.nsh 时必须**报警告**，不能静默装成 0.0.0。"""
    txt = _text(NSI)
    assert "!warning" in txt, "缺版本来源时必须 !warning，否则产物会带着假版本号发出去"


def test_read_app_version_matches_source_of_truth():
    """读版本号的实现必须和 app/version.py 的真实值一致。"""
    import sys

    sys.path.insert(0, str(ROOT / "scripts"))
    import build_release as B

    vt = (ROOT / "app" / "version.py").read_text(encoding="utf-8")
    m = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', vt, re.MULTILINE)
    assert m, "app/version.py 里找不到 __version__"
    assert B.read_app_version() == m.group(1)


def test_build_info_defines_are_overridable():
    """build_info.nsh 的 define 必须被 !ifndef 包住。

    不包的话，makensis 的 `/DAPP_VERSION=...` 和脚本里的 !define 同名会直接
    硬错误（`already defined!` 然后 abort）—— 冒烟测试就靠 /D 覆盖版本和源目录。
    """
    import sys

    sys.path.insert(0, str(ROOT / "scripts"))
    import build_release as B

    content = Path(B.write_build_info(B.read_app_version())).read_text(encoding="utf-8-sig")
    for name in ("APP_VERSION", "EST_SIZE_KB"):
        assert f"!ifndef {name}" in content, f"build_info.nsh 里的 {name} 没有 !ifndef 保护"


# ── 安装体验的硬性要求 ────────────────────────────────────────────────

def test_wizard_has_core_pages():
    """向导六页齐全：欢迎 / 许可 / 组件 / 目录 / 进度 / 完成。"""
    txt = _text(NSI)
    for page in ("MUI_PAGE_WELCOME", "MUI_PAGE_LICENSE", "MUI_PAGE_COMPONENTS",
                 "MUI_PAGE_DIRECTORY", "MUI_PAGE_INSTFILES", "MUI_PAGE_FINISH"):
        assert page in txt, f"安装向导缺页面：{page}"


def test_chinese_language_pack_loaded():
    """必须显式加载简体中文语言包，否则界面是英文。"""
    assert 'MUI_LANGUAGE "SimpChinese"' in _text(NSI)


def test_kills_running_instance_before_overwrite():
    """安装/卸载前必须结束运行中的实例。

    否则 `_internal` 下的 dll/pyd 被占用，NSIS 覆盖失败**不中断安装**，
    用户拿到的是「装完打不开」的残废产物且没有任何报错。
    """
    txt = _text(NSI)
    assert txt.count("taskkill") >= 2, "安装与卸载都该先 taskkill（各一处）"


def test_uninstall_asks_before_deleting_user_data():
    """卸载不许无条件 RMDir /r 整个安装目录。

    这个程序把作品写在自己目录下（短剧AI剪辑输出/、output/、素材库/），
    整目录删 = 卸载即删光用户作品。原脚本就是这么写的，且无任何提示。
    """
    txt = _text(NSI)
    assert "是否同时删除安装目录下的用户数据" in txt, "卸载必须询问是否保留用户数据"
    assert "sg_keep_data" in txt, "卸载缺少「保留数据」分支"


def test_uninstall_moves_cwd_out_of_installdir():
    """卸载时先把 CWD 移出安装目录，否则目录被占用、RMDir 失败。"""
    assert 'SetOutPath "$TEMP"' in _text(NSI)


def test_registers_quiet_uninstall_and_size():
    """注册表要能支持静默卸载并显示真实占用。"""
    txt = _text(NSI)
    assert "QuietUninstallString" in txt, "缺 QuietUninstallString（/S 静默卸载）"
    assert "EstimatedSize" in txt, "缺 EstimatedSize（控制面板显示占用为 0）"


def test_runtime_is_optional_component():
    """本地 AI 内核必须是可选组件，且编译期就能判定有无。"""
    txt = _text(NSI)
    assert "!ifdef HAS_RUNTIME" in txt, "runtime 组件没用 HAS_RUNTIME 做编译期开关"
    assert "SectionIn RO" in txt, "程序本体应声明为必装（SectionIn RO）"


def test_installer_excludes_runtime_user_data():
    """安装包不许把运行时产生的用户数据/日志打进去。

    实测 `dist\\拾光剪影\\` 里就躺着 `短剧AI剪辑输出\\`（本机测试作品）和
    `debug.log`。不排除的话，每发一次安装包就等于给别人带一份本机测试产物 ——
    体积涨、还泄露本机信息。这条不会报错，只能靠断言钉住。
    """
    txt = _text(NSI)
    line = next((ln for ln in txt.splitlines() if "File /r" in ln and "SRC_DIR" in ln), "")
    assert line, "找不到主程序的 File /r 行"
    for name in ("短剧AI剪辑输出", "output", "logs", "debug.log"):
        assert f'/x "{name}"' in line, f"安装包没有排除运行时目录/文件：{name}"


def test_license_text_is_real():
    """许可页要有真内容 —— 空文件会让许可页变成一片空白。"""
    txt = _text(LICENSE)
    assert len(txt) > 500, "LICENSE.txt 内容过短，不像真实的许可文本"
    assert "安装或使用本软件" in txt, "LICENSE.txt 不像许可协议"
