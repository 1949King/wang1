---
name: pyqt6-ui-review
description: Review PyQt6 UI code for best practices: memory management, signal/slot patterns, layer separation, and styling.
---

# PyQt6 UI Review — UI 代码审查

When the user has written PyQt6 UI code, review it for common pitfalls and best practices.

## Review Checklist

### 1. Memory Management
- [ ] All widgets have proper parent-child relationships
- [ ] No orphan windows (every dialog has `parent=self`)
- [ ] `deleteLater()` used for dynamically created widgets
- [ ] No circular references in signal/slot connections
- [ ] `QTimer` instances are stored as instance attributes (not local vars)

### 2. Signal/Slot Patterns
- [ ] Signals are declared with proper types: `pyqtSignal(str, int)`
- [ ] Slot methods use `@pyqtSlot()` decorator where appropriate
- [ ] No lambda in `connect()` that captures loop variables incorrectly
- [ ] Signals are disconnected when widgets are destroyed (if needed)
- [ ] Thread safety: UI updates only happen on main thread

### 3. Layer Separation
- [ ] UI code (`app/modules/lego/`) does NOT contain business logic
- [ ] Core code (`app/core/`) does NOT import PyQt6 widgets
- [ ] Data flows: Core → Module → UI (one direction)
- [ ] State is managed in core layer, not in UI widgets

### 4. Styling
- [ ] QSS styles are in `style_manager.py` or centralized
- [ ] No hardcoded colors — use theme variables
- [ ] Styles don't override widget functionality
- [ ] Dark theme is fully supported

### 5. Error Handling
- [ ] No unhandled exceptions that crash the app
- [ ] User-facing errors show QMessageBox dialogs
- [ ] Background errors are logged, not silently swallowed
- [ ] Button click handlers have debounce/duplicate prevention

## Common PyQt6 Bugs to Watch For

```python
# ❌ BAD: Lambda captures loop variable by reference
for i in range(5):
    btn.clicked.connect(lambda: print(i))  # Always prints 4

# ✅ GOOD: Use default argument
for i in range(5):
    btn.clicked.connect(lambda checked, i=i: print(i))

# ❌ BAD: QTimer as local variable (gets garbage collected)
def start_timer(self):
    timer = QTimer()  # Will be GC'd!
    timer.timeout.connect(self.update)
    timer.start(1000)

# ✅ GOOD: Store as instance attribute
def start_timer(self):
    self._timer = QTimer()
    self._timer.timeout.connect(self.update)
    self._timer.start(1000)

# ❌ BAD: Dialog without parent (orphan window)
dialog = QDialog()  # No parent!

# ✅ GOOD: Always set parent
dialog = QDialog(self)  # self is the parent widget
```

## Review Output Format

```markdown
## PyQt6 UI Review: {file_path}

### ✅ Passed
- Parent-child relationships: OK
- Layer separation: OK

### ️ Warnings
- Line 45: QTimer stored as local variable — will be garbage collected
- Line 78: Lambda in signal connection captures loop variable

###  Errors
- Line 120: Business logic in UI layer — move to `app/core/`

### Suggested Fixes
```python
# Before
...
# After
...
```
```
