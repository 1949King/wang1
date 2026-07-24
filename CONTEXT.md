# AI Short Drama Editor — Context

## Project Overview

A PyQt6-based desktop application for editing and publishing short drama videos with AI assistance.

## Tech Stack

- **UI Framework**: PyQt6
- **Video Processing**: FFmpeg, OpenShot libraries
- **AI Integration**: Ollama (local), various cloud APIs (DeepSeek, OpenAI, etc.)
- **Language**: Python 3.x
- **Architecture**: Layered — `app/core/` (business logic), `app/ui/` (rendering), `app/modules/` (feature modules)

## Key Terminology

| Term | Meaning |
|------|---------|
| **LEGO模块** | Modular UI components under `app/modules/lego/` — the main feature modules |
| **双内核** | Editor scheduler system that manages both local and AI-assisted editing pipelines |
| **时间线** | Timeline — the core editing canvas where clips are arranged |
| **素材库** | Asset library — media files (video, audio, images) available for editing |
| **短剧筛选** | Drama finder — tool for discovering trending short dramas for replication |
| **账号矩阵** | Multi-account management for publishing content across platforms |
| **AI剪辑** | AI-assisted video editing — automatic cutting, transitions, subtitles |
| **Ollama本地** | Local LLM inference via Ollama service (`http://localhost:11434`) |
| **OpenClaw** | Automation engine for multi-platform content publishing |
| **SkillEngine** | Internal AI skill orchestration system |

## Directory Structure

```
app/
  main_qt6.py           # Entry point
  config.json           # Application configuration
  core/                 # Core business logic layer
    ai_central.py       # AI central engine
    editor_scheduler.py # Dual-kernel editor scheduler
    timeline_manager.py # Timeline management
    asset_manager.py    # Asset library management
  modules/
    lego/               # Main UI modules (home, editor, materials, etc.)
      modules.py        # Module registry
      model_management.py # AI model management
      settings_module.py # Application settings
    render/             # Video rendering pipeline
  ui/                   # Shared UI components
    style_manager.py    # Dark theme styling
```

## Coding Conventions

- **Class names**: PascalCase (`HelpModule`, `OllamaStatusWidget`)
- **Methods/functions**: snake_case (`_create_card`, `_check_status`)
- **Private members**: prefixed with `_` (`_current_index`, `_nav_buttons`)
- **Constants**: UPPER_SNAKE_CASE
- **Comments**: Required on classes and core methods, inline for complex logic
- **Never delete existing code** — extend only, follow "minimum invasion, maximum compatibility"

## Rules

1. Read project structure before coding
2. Understand existing business logic before adding features
3. Make minimal changes — don't break existing functionality
4. Follow layer separation: UI renders, core processes data, main window dispatches
5. All dialogs must have a parent window
6. Handle exceptions: validate inputs, prevent duplicate clicks, show error messages

## Issue Tracker

- Location: GitHub Issues
- Triage labels: `bug`, `feature`, `enhancement`, `documentation`
