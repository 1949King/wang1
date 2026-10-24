# 根目录 update_manager.py 归档 — 2026-09-20

> 归档原因：AST 作用域全库扫描（`_verify/scan_undefined_names.py`）发现该文件存在
> 3 处「调用到即崩」的缺陷，且经三重核实为**零引用死代码**，已被 `app/core/update_manager.py` 取代。
> 保留归档而非直接删：与 `2026-09-19-root-cleanup` 保持一致，恢复成本为零。

| 文件 | 大小 | 核实结论 |
|------|------|----------|
| `update_manager.py` | 19,417 B / 512 行 | 零引用（静态 import + 字符串引用 + 动态导入三重核实） |

## 一、为什么判定为「死代码」

| 证据 | 结果 |
|------|------|
| 静态 import | 全库唯一引用是 `app/core/editing_capabilities.py:29` → `from app.core.update_manager import ...`（指 **app/core** 版，非本文件） |
| 字符串引用 | 无 |
| 动态导入 | 无 |
| git 历史 | 仅出现在首次 `feat: 完整项目代码上传`（b83897f），此后**从未被改动** |
| API 对比 | 本文件导出 `UpdateChannel / UpdateInfo / UpdateManager / UpdateDialog / main`；`app/core` 版只有 `UpdateInfo / UpdateManager / asdict` —— **两套完全不同的实现** |
| 代码相似度 | 与 `app/core/update_manager.py` 仅 **2.2%**（difflib），非互为副本 |
| 硬编码证据 | `self._update_server = "https://api.shortplayai.com/updates"`（占位域名）+ 全程用 `print()` 而非 logger |

结论：这是**重构前的早期草稿**，已被 `app/core/update_manager.py` 完整取代。

## 二、本文件自身的 3 个真实缺陷（扫描器命中 14 处）

### 缺陷 1 — `time` 从未导入（2 处）

- `L118` `int(time.time())` 于 `check_for_updates()`
- `L343` `time.sleep(...)` 于 `check_worker()`

模块级 import 只有 `os / sys / json / hashlib / requests / shutil / threading / subprocess`
—— **无 `time`**。两处调用命中即 `NameError`。
（对照：`app/core` 版有 `import time`，正是重构时补上的。）

### 缺陷 2 — `UpdateDialog` 未继承 `QDialog`（结构性致命）

```python
class UpdateDialog:                        # L350 基类列表为空！
    def __init__(self, update_info, parent=None):
        from PyQt6.QtWidgets import (...)  # L354 函数内局部导入
        super().__init__(parent)           # L360 → object.__init__(parent) → TypeError
```

`bases = []` 经 AST 核实。`super()` 落到 `object`，传 `parent` 必抛
`TypeError: object.__init__() takes exactly one argument` ⇒ **该类无法实例化**。

### 缺陷 3 — 14 个 PyQt6 名在 `_setup_ui()` 中不可见

`from PyQt6.QtWidgets import (...)` 写在 `__init__` 里（L354），
而控件全部在**另一个方法** `_setup_ui()`（L365+）中使用：

`QVBoxLayout` `QHBoxLayout` `QLabel` ×4 `QTextEdit` `QProgressBar`
`QHBoxLayout` `QPushButton` ×3 ⇒ 共 14 处 `NameError`。

> 缺陷 2 与缺陷 3 互相掩护：因为类根本构造不出来，缺陷 3 永远不会被执行到，
> 所以这个文件即使被误用，也只在「构造时」报一个错、永远暴露不出后面 14 个。

## 三、恢复方式

```powershell
# 在项目根目录执行
Move-Item "docs\_archive\2026-09-20-update-manager-dup\update_manager.py" .
```

> ⚠️ 恢复前请先确认：若确实需要「更新管理」能力，请直接用
> `from app.core.update_manager import UpdateManager, UpdateInfo`
> —— 本文件不应复活，除非先修掉上述 3 处缺陷。
