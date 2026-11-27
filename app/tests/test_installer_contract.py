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

import os
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
NSI = ROOT / "scripts" / "installer.nsi"
ISS = ROOT / "scripts" / "installer.iss"
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


def test_inno_wizard_language_is_chinese():
    """Inno 向导必须显式加载简体中文，否则界面是英文（NSI 侧同款契约）。

    缺 [Languages] 段时 Inno 用内置英文 Default.isl：编译成功、装完才发现
    向导全是 Next/Cancel/Install。语言文件随仓库携带（官方 6.5.0+ 翻译），
    不依赖出包机 Inno 安装目录是否含该翻译（本机实测 Languages 目录无中文）。
    """
    txt = _text(ISS)
    assert '[Languages]' in txt, "installer.iss 缺 [Languages] 段，向导将显示英文"
    assert 'ChineseSimplified.isl' in txt, "未引用简体中文语言文件"
    isl = ROOT / "scripts" / "ChineseSimplified.isl"
    assert isl.exists(), "缺 scripts/ChineseSimplified.isl（官方简体中文翻译，需随仓库携带）"
    assert 'LanguageID=$0804' in _text(isl), "语言文件不是简体中文（LanguageID 应为 $0804）"


def test_inno_script_uses_version_truth_and_full_source():
    """Inno 必须复用版本真源并打入完整 runtime，不能再写死版本或排除内核。"""
    txt = _text(ISS)
    assert '#ifndef APP_VERSION' in txt
    assert '#error APP_VERSION' in txt
    assert 'AppVersion={#APP_VERSION}' in txt
    assert 'Source: "{#SRC_DIR}\\*"' in txt
    assert 'recursesubdirs' in txt
    assert 'Excludes:' in txt
    excluded = next(line for line in txt.splitlines() if 'Excludes:' in line)
    assert 'runtime' not in excluded.lower()


def test_inno_script_excludes_private_outputs_and_preserves_user_data():
    """不得携带本机作品；静默卸载必须保留用户数据，禁止递归删除整个安装目录。"""
    txt = _text(ISS)
    excluded = next(line for line in txt.splitlines() if 'Excludes:' in line)
    for name in ('短剧AI剪辑输出', 'output', 'logs', 'debug.log'):
        assert name in excluded
    assert 'not UninstallSilent' in txt
    assert "DelTree(ExpandConstant('{app}\\短剧AI剪辑输出')" in txt
    assert "DelTree(ExpandConstant('{app}')," not in txt


def test_inno_supports_single_file_and_disk_spanning():
    """单文件受限时必须能用同一脚本分卷，每片 1 GiB，且不删减内容。"""
    txt = _text(ISS)
    assert 'DiskSpanning={#DISK_SPANNING}' in txt
    assert 'DiskSliceSize=1073741824' in txt
    assert 'LZMAUseSeparateProcess=yes' in txt


# ── Lite 轻量版（2026-11-20：同一 iss 第二遍编译，排除 runtime 内核）──────

def test_inno_lite_branch_excludes_runtime_and_keeps_private_excludes():
    """Lite 分支必须排除 runtime\\*，且保留全量的四项私有排除。

    全量行必须仍是第一条 Excludes 行（上面两条契约取「首行」断言不含
    runtime）；Lite 行若漏掉任一私有排除，就会把本机作品/日志带进轻量包。
    """
    txt = _text(ISS)
    assert '#ifdef LITE_BUILD' in txt, "缺 LITE_BUILD 编译期开关"
    lines = [ln for ln in txt.splitlines() if 'Excludes:' in ln]
    assert len(lines) >= 2, "应有全量与 Lite 两条 Excludes 行"
    full, lite = lines[0], lines[1]
    assert 'runtime' not in full.lower(), "第一条必须是全量行（不含 runtime）"
    assert 'runtime\\*' in lite, "Lite 行必须排除 runtime\\*"
    for name in ('短剧AI剪辑输出', 'output', 'logs', 'debug.log'):
        assert name in lite, f"Lite 行漏掉私有排除项：{name}"


def test_inno_lite_output_suffix_and_full_default():
    """产物名后缀由 LITE_BUILD 决定：缺省全量无后缀，Lite 带 -Lite。

    两版 AppId 与版本号相同，唯一区分就是文件名后缀；缺省分支若带后缀，
    全量包会被误认成 Lite，两版产物还会互相覆盖。
    """
    txt = _text(ISS)
    assert 'OutputBaseFilename=拾光剪影-Setup-{#APP_VERSION}{#SG_OUTPUT_SUFFIX}' in txt
    assert '#define SG_OUTPUT_SUFFIX "-Lite"' in txt
    assert '#define SG_OUTPUT_SUFFIX ""' in txt


def test_inno_lite_installdelete_only_runtime():
    """Lite 的 [InstallDelete] 只清 runtime 残骸，且只在 LITE_BUILD 分支内。

    全量 → Lite 是同一 AppId 原地降级：旧内核约 4.37 GB 不清掉，轻量版
    就白装了；但清理范围一旦扩到 output/素材库，就是删用户作品。
    """
    txt = _text(ISS)
    assert '[InstallDelete]' in txt, "Lite 降级安装缺 [InstallDelete] 清残骸"
    prev_lines = [ln for ln in txt[:txt.find('[InstallDelete]')].splitlines() if ln.strip()]
    assert prev_lines[-1].strip() == '#ifdef LITE_BUILD', "[InstallDelete] 必须只在 LITE_BUILD 分支内"
    body = txt.split('[InstallDelete]', 1)[1].split('\n[', 1)[0]
    entries = [ln for ln in body.splitlines() if ln.strip().startswith('Type:')]
    assert entries, "[InstallDelete] 没有清理条目"
    for ln in entries:
        assert 'filesandordirs' in ln, "清目录残骸必须用 filesandordirs"
        assert '{app}\\runtime' in ln, f"清理范围越界（只许 runtime）：{ln}"


def test_build_release_lite_wiring():
    """--lite 必须真接线：参数校验 + /DLITE_BUILD 注入 + 按 -Lite 名精确校验。

    只加参数不注入 define = 第二遍编译出的仍是全量包（静默错版）；
    产物校验不带后缀 = 拿旧全量 exe 冒充 Lite 成功。
    """
    txt = (ROOT / "scripts" / "build_release.py").read_text(encoding="utf-8")
    assert '"--lite"' in txt, "build_release.py 缺 --lite 参数"
    assert 'lite: bool = False' in txt, "build_inno_installer 缺 lite 形参"
    assert 'ap.error("--lite 只能与 --inno-installer 一起使用")' in txt
    assert 'ap.error("--lite 是单文件轻量版，不与 --disk-spanning 同用")' in txt
    assert 'args.append("/DLITE_BUILD")' in txt, "lite 模式没给 ISCC 注入 /DLITE_BUILD"
    assert 'lite=args.lite' in txt, "main 没把 --lite 传进 build_inno_installer"
    assert 'suffix = "-Lite" if lite else ""' in txt
    assert '拾光剪影-Setup-{version}{suffix}.exe' in txt


# ── VC++ 运行时随包（2026-11-19 实测：干净目标机弹「找不到 MSVCP140.dll」）──

VC_DLLS = (
    "msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll",
    "vcruntime140.dll", "vcruntime140_1.dll", "concrt140.dll",
)


def test_vc_runtime_copied_next_to_exe_and_internal(tmp_path, monkeypatch):
    """VC++ 运行时必须 app-local 放进 exe 根目录与 _internal 两处。

    实测反例（2026-11-19）：构建机装了系统级 VC++ redist，PyInstaller 不收集
    这些 CRT，自检也全过；但 dist 根与 _internal 均无 msvcp*/vcruntime*，
    干净目标机安装后启动即弹「找不到 MSVCP140.dll」。Windows loader 优先搜
    exe 所在目录：根目录一份修 exe 自身加载，_internal 一份覆盖各 .pyd 加载。
    """
    import sys

    sys.path.insert(0, str(ROOT / "scripts"))
    import build_release as B

    monkeypatch.setattr(B, "DIST", str(tmp_path / "app"))
    monkeypatch.setattr(B, "INTERNAL", str(tmp_path / "app" / "_internal"))
    B.ensure_vc_runtime()
    system32 = Path(os.environ["SystemRoot"]) / "System32"
    for base in (B.DIST, B.INTERNAL):
        for name in VC_DLLS:
            dst = Path(base) / name
            assert dst.exists(), f"{name} 未随包放入 {base}"
            assert dst.stat().st_size == (system32 / name).stat().st_size, (
                f"{base} 下的 {name} 与 System32 源大小不一致"
            )


def test_vc_runtime_wired_after_complete_internal():
    """ensure_vc_runtime 必须接进主流程：补包之后、自检之前。

    函数存在但不接线 = 出包时不执行，产物依旧缺 CRT（静默坏掉）。
    """
    txt = (ROOT / "scripts" / "build_release.py").read_text(encoding="utf-8")
    assert "def ensure_vc_runtime" in txt, "build_release.py 缺 ensure_vc_runtime 实现"
    main_body = txt.split("def main(")[1]
    i_complete = main_body.find("complete_internal()")
    i_vc = main_body.find("ensure_vc_runtime()")
    i_selftest = main_body.find("report = selftest()")
    assert i_complete != -1 and i_vc != -1, "main 流程缺 complete_internal/ensure_vc_runtime 调用"
    assert i_complete < i_vc < i_selftest, "补 CRT 必须在补包之后、自检之前"
