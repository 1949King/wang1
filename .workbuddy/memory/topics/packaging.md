# 发布打包深水区（2026-11-12 实测，PyInstaller 6.x）

> 主文件 `MEMORY.md` 只留结论指针，过程与判据在这里。工具：`scripts/build_release.py` + `.workbuddy/tmp/check_module_coverage.py`。

## 一、`_internal` vs `runtime/` 分工（最容易搞反）

| 放哪 | 判据 | 例子 |
|---|---|---|
| `_internal/` | PYZ 里**已有 `__init__`** 的包 | numpy / scipy / PIL / html / `app` 全部子包 |
| `runtime/` | 平铺 `.py`，无包结构 | 独立模块 |

原因：这些包的 `__path__` 指向 `_internal/<pkg>`，残件放 `runtime/` 会 import 失败。
`runtime/` 的作用是把 exe 同级目录插到 `sys.path[0]`，绕过 PyInstaller 直取 torch 必崩的 `0xC0000005`。

## 二、`runtime/` 装载方案核心 = `app/core/runtime_pack.py`

- 曾长期 **untracked**，而 `build_release.py` 早已引用它 ⇒ 换机构建直接炸。
- 2026-11-05 入库（`2aab20f3`）。
- 内含两处 swallow-except，都已加 `# stability-gate: allow-swallow（理由）`。

## 三、三件套（缺一不可）

**① `hiddenimports` 必须自动枚举 `app/` 全量**
手写清单实测漏 **107 个模块 + 27 个插件**。spec 里改成扫目录生成。

**② `runtime/` 对 Analysis（PyInstaller 冻结态）不可见**
⇒ stdlib 与三方包会缺，且**只在启动时才炸**：
- stdlib：`timeit` / `modulefinder` / `struct`
- 三方：`markupsafe` / `safetensors` / `httpx2`
- 只能靠 selftest 抓，静态检查抓不到。

**③ 整目录拷贝必须排除 VCS 目录**
`app/skills/external/` 下 3 个 skill 是 `git clone` 来的。不排除 `.git` 的后果：
- 泄漏别人仓库的历史（98K + 649K + 1.6M）
- **git pack 默认只读**（`-r--r--r--`），`shutil.copy2` 保留属性 ⇒ 下次 PyInstaller `_rmtree(dist)` 报
  `PermissionError [WinError 5]`（实测撞到，卡住整个重建）
- 已在 `_sync_app_subpkg` 的 `skip_dirs` 加：`.git` / `.github` / `.idea` / `.vscode`

## 四、目录扫描型加载 ⇒ 必须进 `SYNC_APP_SUBPKGS`

进 PYZ 等于没进。三处 loader 都靠**真实目录**，目录缺失时**静默返回 0，不报错不警告**：

| 子包 | loader 机制 | 缺了的表现 |
|---|---|---|
| `app/plugins` | `PluginManager`：`os.listdir` + `spec_from_file_location` | 编辑器插件数 = 0 |
| `app/skills` | `SKILLS_ROOT = Path(__file__).parent` + `os.walk` 找 `SKILL.md` | 拓展中心「外部技能」空着 |
| `app/core/video_processing` | — | 进 Analysis 直接 `0xC0000005` |

```python
SYNC_APP_SUBPKGS = ["app/core/video_processing", "app/plugins", "app/skills"]
```
自检对应项：插件 **27** / 外部 skill **11** / PyAV 引擎。
对应自检函数：`_t_plugins()`、`_t_skills()`（在 `app/core/ai_runtime_selftest.py`）。

## 五、冻结进程里加载即崩的两个包

| 包 | 症状 | 处置 |
|---|---|---|
| `opentimelineio` | 段错误 | 走 `--otio-worker` 子进程；`main_qt6.py` 在 `import PyQt6` **之前**分流 |
| `mediapipe` | `1114`（DLL 初始化失败）| 姿态解析在发布版声明「不支持」 |

两者**文件都齐**、普通解释器正常 ⇒ 不是打包漏文件，是冻结态不兼容。
自检归入 `OPTIONAL_CHECKS`，记 WARN 不记 FAIL。

## 六、审计脚本自身的两个坑（`audit_assets.py`）

1. `config.json` 实际在 `_internal/config.json`（spec 的 datas 用的是 `'.'`）⇒ 路径判断要支持「包内位置」。
2. 未排除 `__pycache__` ⇒ `app/plugins` 永远报「少 41 个」（那 41 个正是有意跳过的 pyc）⇒ `count()` 必须排除。

## 七、2026-11-12 交付实测基线

- 源码模块 **512** / 包内文件 **3844** / 被引用 **399**，**缺失 0**
- 插件 27、外部 skill 11 与源码**逐文件一致**
- 自检 **26 项：24 过 / 2 降级**（mediapipe、OTIO，均有降级路径）
- 产物 **6.35 GB**（runtime 4.37 + _internal 1.96），真机启动正常

## 八、NSIS 安装包（2026-11-15 实测，六条血泪）

### 8.1 结论先给：这个体积**装不进 NSIS**

makensis 是 32 位程序，安装包数据块要 mmap 进 2 GB 用户态地址空间。
逐档实测（NSIS 3.13 / Win11）：

| 数据量 | 结果 |
|---|---|
| 900 MB / 1.4 GB / 1.6 GB / 1.8 GB | ✅ 全成功（1.8 GB 耗时 1 分 12 秒） |
| 1.96 GB（真实 `_internal`） | ❌ `Internal compiler error #12345: error mmapping file (1992247082, 33554432) is out of range` |
| 6.35 GB（含 runtime） | ❌ 同上；zlib 换 lzma 一样 |

失败发生在**开始后几秒的预分配阶段**，与压缩率无关 ⇒ 是地址空间上限，不是配置问题。
`NSIS_DATABLOCK_LIMIT = 2 GiB` 已写进 `build_release.py` 按体积自动决策。

⚠️ **别再「装个 NSIS 就能出包」**——工具装了、脚本对了，照样失败。要先量体积。

### 8.2 `.nsi` 与 license 文本**必须 UTF-8 with BOM**

NSIS 3 + `Unicode true` 靠 BOM 判编码。**无 BOM** 会被按 ANSI(GBK) 解释字节流
⇒ 安装包界面中文全乱码，而 **makensis 退出码是 0**（编译期零提示）。
反例实测：同脚本删掉前 3 字节 BOM，`/PPO` 输出中文全乱；加回 BOM 全正常。
编译时看 `Processing script file: "...nsi" (UTF8)` 有 `(UTF8)` 才算对。

### 8.3 `/D` 与脚本 `!define` 同名 = 硬错误

`makensis /DAPP_VERSION=1.0` 撞上脚本里的 `!define APP_VERSION` ⇒
`!define: "APP_VERSION" already defined!` 然后 **abort**。
要留命令行覆盖能力，生成的头文件里每个 define 都用 `!ifndef` 包住。

### 8.4 卸载器**不需要**自删处理（纠正一个反向判断）

NSIS 卸载器启动时会**自动复制到 `$TEMP` 再从那里运行**
（只有显式传 `_?=` 才关闭该行为）⇒ `RMDir /r "$INSTDIR"` 不会卡在「删不掉正在运行的自己」。
真正要处理的是 **CWD**：CWD 还在 `$INSTDIR` 时目录被占用，先 `SetOutPath $TEMP`。

⚠️ **真正危险的是反过来：删得太干净**。本程序把作品写在自己目录下
（`短剧AI剪辑输出/`、`output/`、`素材库/`），无条件 `RMDir /r "$INSTDIR"`
= **卸载即删光用户作品**，且无任何提示。必须问一句，「保留」分支只删程序本体，
末尾用**不带 `/r`** 的 `RMDir`（目录非空自动失败 ⇒ 数据保住）。

### 8.5 版本号只认 `app/version.py`

曾写死 `4.10.3` 而代码已 4.47.0（脱节 37 个次版本）⇒ 文件名错 + 注册表
`DisplayVersion` 错 ⇒ 用户看到的版本是假的。
链路：`app/version.py` → `build_release.read_app_version()`（**正则读，别 import**
——`import app` 会拖起 PyQt6/torch）→ `dist/build_info.nsh` → `!include`。
出包后按版本号**精确校验**产物，别「取 dist 里最新一个 Setup」（会拿到旧包）。
已加 16 个契约测试（`app/tests/test_installer_contract.py`），含 BOM/写死版本两个反例。

### 8.6 打包要排除运行时产物

`dist\拾光剪影\` 里会躺着 `短剧AI剪辑输出\`（本机测试作品）和 `debug.log`。
`File /r` 不排除就等于每发一次包带一份本机产物。
`/x "runtime" /x "短剧AI剪辑输出" /x "output" /x "logs" /x "debug.log"`。

### 8.7 `File /r` 是**编译期**指令

源目录不存在时 makensis 直接报错 ⇒「有没有 runtime」必须在编译期由
`HAS_RUNTIME` 决定，不能在脚本里用运行时 `IfFileExists` 判断（拦不住编译失败）。

