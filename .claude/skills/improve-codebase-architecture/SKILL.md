---
name: improve-codebase-architecture
description: Find architecture improvement opportunities using the domain language in CONTEXT.md and decisions in docs/adr/.
---

# Improve Codebase Architecture — 架构改进

Periodically analyze the codebase to find deepening opportunities — places where modules can be simplified, responsibilities clarified, or coupling reduced.

## The Process

1. **Read CONTEXT.md** — understand the domain language and current architecture.
2. **Scan module boundaries** — check `app/core/` vs `app/modules/` vs `app/ui/`.
3. **Identify violations:**
   - UI layer containing business logic
   - Core layer containing UI code
   - Circular imports between modules
   - God classes with too many responsibilities
4. **Check signal/slot patterns:**
   - Are signals crossing too many module boundaries?
   - Are there implicit couplings through shared state?
5. **Propose improvements** — one at a time, with clear rationale.

## Architecture Principles (PyQt6)

```
─────────────────────────────────────┐
│        main_qt6.py                  │  ← Entry point, lifecycle
├─────────────────────────────────────┤
│  app/modules/lego/                  │  ← UI modules (rendering only)
│    ├── main_window.py               │    Dispatches to core
│    ├── help_module.py               │
│    └── model_management.py          │
├─────────────────────────────────────┤
│  app/core/                          │  ← Business logic & state
│    ├── ai_central.py                │
│    ├── editor_scheduler.py          │
│    └── timeline_manager.py          │
─────────────────────────────────────┤
│  app/modules/render/                │  ← Rendering pipeline
│  app/modules/utils/                 │  ← Shared utilities
└─────────────────────────────────────┘
```

## Red Flags

- 🚩 A module in `app/modules/lego/` imports from `app/core/` AND `app/ui/`
- 🚩 A core file has `QWidget`, `QLabel`, `QButton` imports
-  Global variables defined in module files
-  Dialogs without parent windows
-  Files with 500+ lines doing multiple things

## Improvement Suggestions

For each finding, provide:
1. **What** — the specific issue
2. **Where** — file and line reference
3. **Why** — why it's a problem
4. **How** — suggested fix with before/after code

## When to Run

- Every few days during active development
- Before adding a new major feature
- When the codebase feels "hard to change"
