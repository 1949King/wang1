---
name: zoom-out
description: Explain code in the context of the whole system. Use when working in unfamiliar code.
---

# Zoom Out — 全局视角

## When to Use

- Before modifying code you didn't write
- Before making architectural decisions
- When you're unsure about a dependency

## The Process

1. **Find the entry point.** Where does execution start?
2. **Trace the flow.** Follow the signal/slot chain or method calls.
3. **Identify the layer.** Is this UI, business logic, or data layer?
4. **Find related code.** What else touches this same data or signal?
5. **Check for side effects.** What else will break if you change this?

## PyQt6 Architecture Layers

```
main_qt6.py          → 入口，应用生命周期
modules/lego/        → 模块层，功能组件
  ├── login_window   → 登录窗口
  ├── main_window    → 主窗口，导航调度
  ├── help_module    → 帮助模块
  └── model_management → 模型管理模块
core/                → 核心业务逻辑层
  ├── editor_interface → 编辑器接口
  ├── timeline_manager → 时间线管理
  └── asset_manager    → 素材管理
modules/render/      → 渲染模块
modules/utils/       → 工具模块
```

## Rules

- **Don't assume.** Verify by reading the code, not guessing.
- **Check signal connections.** In PyQt6, signals can connect across modules — trace them.
- **Look for inheritance.** Check parent classes for inherited behavior.
- **Check QSS files.** UI styling may be in separate style files.
