---
name: prototype
description: Build a throwaway prototype to flesh out a design — either a runnable terminal app or UI variations.
---

# Prototype — 快速原型

When the user needs to explore a design or verify an approach, build a minimal runnable prototype.

## Rules

1. **Throwaway by design.** Don't over-engineer. Prototype code should be easy to delete.
2. **One hypothesis per prototype.** Focus on validating one thing.
3. **Run it immediately.** If it can't run, it's not a prototype — it's a draft.
4. **Label clearly.** Mark files as `PROTOTYPE` so they don't get accidentally committed.

## Types of Prototypes

### Terminal Prototype
For state machines, algorithms, data flow:
```python
# PROTOTYPE: test_timeline_merge.py
# Delete after validation
def test_merge():
    # Minimal test of the merge logic
    pass
```

### UI Prototype
For PyQt6 UI experiments, create a standalone window:
```python
# PROTOTYPE: test_new_layout.py
# Delete after validation
from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel
import sys

app = QApplication(sys.argv)
window = QWidget()
layout = QVBoxLayout(window)
layout.addWidget(QLabel("Prototype"))
window.show()
sys.exit(app.exec())
```

## PyQt6 UI Prototype Template

```python
#!/usr/bin/env python3
# PROTOTYPE: [description]
# DO NOT COMMIT — validate then implement properly

import sys
from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel, QPushButton

def main():
    app = QApplication(sys.argv)
    
    window = QWidget()
    window.setWindowTitle("Prototype")
    window.resize(400, 300)
    
    layout = QVBoxLayout(window)
    layout.addWidget(QLabel("Test your idea here"))
    
    btn = QPushButton("Click me")
    btn.clicked.connect(lambda: print("Clicked!"))
    layout.addWidget(btn)
    
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
```

## After Prototyping

1. Note what worked and what didn't.
2. If it works, implement properly in the real codebase (don't copy-paste prototype code).
3. Delete the prototype files.

## When to Use

- Exploring a new UI layout
- Testing a signal/slot pattern
- Validating a data transformation
- Comparing two approaches side-by-side
