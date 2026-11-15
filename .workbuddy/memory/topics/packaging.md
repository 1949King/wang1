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
