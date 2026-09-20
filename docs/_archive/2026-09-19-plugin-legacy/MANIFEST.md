# 归档 MANIFEST · 2026-09-19 · 插件体系旧残留

> **归档原因**：项目存在四套并存的插件体系，其中「第二套」为历史残留，全库零引用。
> 归档（**移动**，非删除）以消除「四套并存」的技术债，同时保留恢复路径。
> **核实日期**：2026-09-19 ｜ **核实方法**：全库 Grep + AST 静态分析 + 实机 subprocess 导入测试
> **归档后守卫**：`OK frozen zones intact (85 locks)` ｜ 全库 551 个 py 语法错误 **0**

---

## 一、背景：为什么是「四套并存」

项目历史上先后/并行出现过四套插件机制：

| # | 体系 | 位置 | 状态 |
|---|------|------|------|
| 1 | **ExtensionsRegistry**（统一注册表） | `app/core/extension_base.py` | ✅ **现行**（Plugin/Skill/MCP 统一接口） |
| 2 | **PluginManager**（传统插件注册中心） | `app/core/plugin_manager.py` | ✅ **现行**（`editor_module.py:868` 真实实例化） |
| 3 | plugin_loader / hotloader / authentication / sandbox | `app/core/plugin_*.py`（5 文件） | ⚠️ **保留**（B3 收敛标记 2026-05-31：「5 个文件职责不重叠，不需要合并，仅作系统级归档」） |
| 4 | **`app/modules/plugins/`**（本批归档） | 已移至本目录 | ❌ **归档** |

第 3 套的 5 个文件**全部存在且内部依赖完整**（已核实：`plugin_loader.py` 40,178 B /
`plugin_hotloader.py` 26,499 B / `plugin_authentication.py` 24,285 B /
`plugin_sandbox.py` 21,592 B / `plugin_manager.py` 14,925 B）。
其中 `plugin_hotloader.py` 目前仅 `tests/legacy/*` 引用，属「备用」状态。**本批不动**，属独立议题。

---

## 二、归档清单（8 文件 / 29.4 KB）

### 2.1 `plugin_shim/`（原 `D:\拾光剪影\plugin\`，2 文件 / 806 B）

| 归档后 | 原路径 | 大小 |
|---|---|---|
| `plugin_shim/__init__.py` | `plugin/__init__.py` | 403 B |
| `plugin_shim/plugin_system.py` | `plugin/plugin_system.py` | 403 B |

**性质**：纯转发壳。两文件**逐字节完全相同**（403 B × 2），内容均为：

```python
from app.modules.plugins.plugin_system import (
    PluginManager, plugins, plugin_versions,
    plugin_categories, plugin_configs, loaded_plugins,
    default_plugin_categories, BasePlugin, register_plugin
)
__all__ = [...]
```

**零引用证据**：全库 `from plugin import` / `import plugin` 正则扫描 → **0 命中**。

### 2.2 `modules_plugins/`（原 `D:\拾光剪影\app\modules\plugins\`，3 文件 / 27.5 KB）

| 归档后 | 原路径 | 大小 |
|---|---|---|
| `modules_plugins/plugin_sandbox.py` | `app/modules/plugins/plugin_sandbox.py` | 3,465 B |
| `modules_plugins/plugin_system.py` | `app/modules/plugins/plugin_system.py` | 14,002 B |
| `modules_plugins/pyqt_plugin_manager.py` | `app/modules/plugins/pyqt_plugin_manager.py` | 10,078 B |

**归档理由（逐条实测）**：

1. **零外部引用**：全库 `app.modules.plugins` / `modules.plugins` 扫描 → 命中项仅
   `plugin/` 转发壳（本批一并归档）与三个坏测试（本批一并归档）。**无活代码依赖**。
2. **缺 `__init__.py`**：目录内无 `__init__.py`，仅靠 Python 3 隐式命名空间包才可导入 —— 说明从未被当作正式包使用。
3. **`plugin_sandbox.py` 含真实缺陷（必崩）**：
   - 第 7–10 行仅 `import builtins`... 实为 `import builtins` **缺失**（只导入了 `os` / `logging` / `typing`）
   - 第 93 行却使用 `original_print = builtins.print`
   - 实机验证：`create_sandbox_globals()` 返回的 `__builtins__` 中 **无 `builtins` 键**（61 个白名单项）
   - 结论：`PluginManager.install_plugin()` 调用 `create_sandbox_globals()` 时**必抛 `NameError`**，该安装流程从未跑通。
4. **`plugin_system.py:360` 断链**：
   ```python
   try:
       from .full_video_editor import FullVideoEditorPlugin
   except ImportError:
       logger.warning('警告: 无法导入FullVideoEditorPlugin')
   ```
   `full_video_editor.py` **不存在**，靠 `except` 吞掉 → 每次导入该模块都会向 stderr 打一行警告（实机已复现）。
5. **`pyqt_plugin_manager.py` 副作用**：
   - 第 4 行 `from PyQt6.QtWidgets import *`（星号导入，破坏静态作用域分析）
   - 第 10 行 **模块导入时执行** `os.makedirs("plugins", exist_ok=True)` —— 在 CWD 静默建目录
   - 第 12 行注释写「PyQt5 插件管理器」、类名/窗口标题也都是 PyQt5，但代码 `import PyQt6`（注释与实现矛盾）
   - 第 79 行 `Qt.AlignCenter`、第 78 行 `QFont.Bold` 在 PyQt6 中已变更
6. **与现行体系重名冲突**：本目录的 `PluginManager` 与现行 `app/core/plugin_manager.py:13` 的 `PluginManager`
   **同名不同实现**；`plugin_sandbox.py` 与现行 `app/core/plugin_sandbox.py`（587 行，功能完整）也是同名不同实现。

> 该残留此前已被两份体检报告点出：
> - `docs/_reports/2026-09-14-代码实测体检与产品定位.md:331-335`：「另一套，无人引用」/「重复实现」
> - `docs/_reports/2026-09-15-项目定位与迭代方向分析.md:53`：「零引用的第二套插件体系（与正文档 §9 冲突）」

### 2.3 `broken_tests/`（原 `D:\拾光剪影\tests\unit\`，3 文件 / 3.8 KB）

| 归档后 | 原路径 | 大小 |
|---|---|---|
| `broken_tests/test_plugin_import.py` | `tests/unit/test_plugin_import.py` | 1,383 B |
| `broken_tests/test_full_video_editor.py` | `tests/unit/test_full_video_editor.py` | 1,039 B |
| `broken_tests/test_all_imports.py` | `tests/unit/test_all_imports.py` | 1,405 B |

**性质**：三者均为 **`print()` 探针脚本**，无 `assert`、无 `def test_*`（pytest 收集即失败），
引用的全是 `modules.py` 单文件时代的旧路径：

| 文件 | 断链点 |
|---|---|
| `test_plugin_import.py` | `:14` `from modules.plugins.plugin_system import PluginManager`、`:22/:39` `modules.plugins.full_video_editor`（文件不存在） |
| `test_full_video_editor.py` | `:10` `from modules.plugins.full_video_editor import ...` —— **裸导入，不在 try 内**，收集阶段直接 ImportError |
| `test_all_imports.py` | `:18` `from moviepy.editor import`（moviepy 2.x 已移除 `.editor`）、`:32` `modules.utils.logger`、`:38` `config.settings`、`:44` `modules.plugins.plugin_system` —— 四处全是旧路径 |

> 注：这三个正是历史上「6 failed」的常客（`from core.*` 陈旧路径测试同源问题）。

---

## 三、同步变更（非归档，但属同一件事）

### 3.1 `plugin_config.json` —— 移除死目录项

```diff
- "plugin_dirs": ["app/plugins", "app/modules/plugins"]
+ "plugin_dirs": ["app/plugins"]
```

**依据**：`app/core/plugin_hotloader.py:66-78` 读取 `plugin_config.json` 的 `plugin_dirs`
并逐个 `add_plugin_dir()`；`app/modules/plugins` 归档后该项指向不存在路径。
其余键（`enabled_plugins` / `plugin_registry`）**原样保留**。

**编码验证**（归档后）：511 字节 / 严格 UTF-8 解码通过 / 无 U+FFFD / `name == "AI特效制作"` 吻合原值。

### 3.2 修复 3 处 `modules.utils.logger` 断链

扫描中发现 3 处**真断链**（非本批归档产物，属存量缺陷），已就地修复：

| 文件:行 | 修改前 | 修改后 |
|---|---|---|
| `app/core/ai_tools.py:4` | `from modules.utils.logger import logger` | `from app.modules.utils.logger import logger` |
| `app/core/preview_manager.py:2` | 同上 | 同上 |
| `app/core/gl_filter_widget.py:29` | 同上 | 同上 |

**依据**：`modules/` 顶层目录不存在；正确路径 `app/modules/utils/logger.py` 存在（1,035 B）。
对照参考：同目录 `app/core/thread_safety.py:14` 早已用正确路径 `app.modules.utils.logger`。
此 3 处只要被 import 即 `ModuleNotFoundError`（`preview_manager.py` / `gl_filter_widget.py` 是 UI 侧文件，风险实在）。

---

## 四、恢复命令

```powershell
$root = "D:\拾光剪影"
$arch = "$root\docs\_archive\2026-09-19-plugin-legacy"

# 1) 恢复 plugin/ 转发壳（注意：其指向的 app/modules/plugins 需先恢复）
New-Item -ItemType Directory -Force "$root\plugin" | Out-Null
Move-Item "$arch\plugin_shim\__init__.py"       "$root\plugin\__init__.py"
Move-Item "$arch\plugin_shim\plugin_system.py"  "$root\plugin\plugin_system.py"

# 2) 恢复 app/modules/plugins/
New-Item -ItemType Directory -Force "$root\app\modules\plugins" | Out-Null
Move-Item "$arch\modules_plugins\*" "$root\app\modules\plugins\"

# 3) 恢复三个探针测试
Move-Item "$arch\broken_tests\*" "$root\tests\unit\"

# 4) 还原 plugin_config.json 的 plugin_dirs（追加回死目录项）
```

---

## 五、归档后核实结果

| 检查项 | 结果 |
|---|---|
| 全库 `from plugin import` / `import plugin` | **0 命中** |
| 全库 `modules.plugins` | **0 命中**（代码区；仅 `app/version.py` 描述字符串内含） |
| 全库 `full_video_editor` | **0 命中**（代码区；同上） |
| 全库 py 语法错误 | **0**（551 文件） |
| 冻结区守卫 | `OK frozen zones intact (85 locks)` |
| 现行插件体系文件存在性 | 10/10 全部 OK |
| 已移除项状态 | 8/8 全部 GONE |
| `app/version.py` | `compile + exec` 通过、`VERSION_INFO` keys 精确匹配、无重复赋值、无旧 codename 残留 |

---

## 六、未纳入本批（待决）

| 项 | 说明 | 建议 |
|---|---|---|
| `app/core/plugin_*.py`（5 文件 / 127.5 KB） | 第 3 套体系，**B3 收敛标记（2026-05-31）明确「5 个文件职责不重叠，不需要合并」**。5 文件全部存在：`plugin_loader.py`(40,178) / `plugin_hotloader.py`(26,499) / `plugin_authentication.py`(24,285) / `plugin_sandbox.py`(21,592) / `plugin_manager.py`(14,925)。**内部依赖链完整，无断链** | **建议保留**：属有意设计的「系统级归档」，且 `plugin_manager.py` 为现行体系 ②（被 `editor_module.py:868` 真实使用） |
| `plugin_hotloader.py` 的活跃度 | 该模块仅被 `tests/legacy/*`（4 文件，非活跃测试）引用；活跃代码走 `plugin_manager.py` | 独立议题：评估 `plugin_hotloader` 是否降级为「备用」 |
| `tests/legacy/*`（44 文件） | 旧测试布局，含 `test_week5_plugin_loader.py` 等引用第 3 套体系 | 独立议题：`legacy` 目录整体是否归档 |
| `plugin_config.json` 的 `plugin_registry` 键 | 仅 `plugin_hotloader` 消费；`plugin_hotloader` 目前无活跃调用方 | 待 `plugin_hotloader` 去留定后一并决策 |
| `docs/_reports` 中提及 `app/modules/plugins` 的段落 | 两份 `_reports` 已属历史快照，保留原样（历史记录不应篡改） | 无需处理 |
