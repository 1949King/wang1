# AI Short Drama Editor — Context

## Project Overview

A PySide6-based desktop application(**拾光剪影**)focused on short-drama **editing** and **AI canvas** (agent + digital human). Publishing/finder plugins are interface shells only.

**唯一开发文档(单一事实源)**: [`docs/现行技术文档.md`](docs/现行技术文档.md) — 后续开发只读这一份
**历史/深度细节(已归档)**: [`docs/_archive/`](docs/_archive/) — 不再作为现行依据

## Tech Stack

- **UI Framework**: PySide6 6.10.2 / Qt 6.10.2
- **Video Processing**: FFmpeg, OpenCV/PyAV, MLT (via `thirdparty/mlt/Shotcut` runtime; OpenShot was evaluated early and rejected — remnants removed 2026-09-14, NOT a fork)
- **AI Integration**: Ollama (local), various cloud APIs (DeepSeek, OpenAI, etc.)
- **Language**: Python 3.x
- **Architecture**: Layered — `app/core/` (business logic), `app/modules/lego/` (feature UI), EventBus

## Key Terminology

完整表见 [`docs/_archive/knowledge/01-glossary.md`](docs/_archive/knowledge/01-glossary.md).常用:

| Term | Meaning |
|------|---------|
| **LEGO模块** | Modular UI under `app/modules/lego/` |
| **双内核** | `EditorScheduler`: PyAV light vs FFmpeg/MLT pro |
| **时间线** | Timeline canvas; truth source = `EditorModule._clips` |
| **素材库** | Asset library |
| **短剧筛选** | Plugin shell `drama_finder_plugin` (no crawler); UI via **extensions** |
| **拓展中心** | Registry id=`extensions`(migrated from `plugins`) |
| **B0–B2** | `text_frame_map` / `edit_commands` / `filler_silence_detect` |
| **账号矩阵** | Multi-account publishing |
| **AI剪辑** | AI-assisted cutting / subtitles / strategy |
| **Ollama本地** | Local LLM at `http://localhost:11434` |
| **OpenClaw** | Multi-platform publish automation |
| **SkillEngine** | Skill orchestration |
| **墙钟播放** | Wall-clock playhead (not `+=0.033`) |
| **3D 导演台** | Canvas Three.js stage (`dummy13-v3`); front = +Z; solo/group templates |
| **数字人** | Canvas node `digitalHuman`: portrait + line + TTS; talking-head video only with a real model |
| **剪辑画布联动** | Round-trip ids between `_clips` and canvas nodes; outbox auto-creates source nodes |
| **账号运营** | Plugin shell `account_ops_plugin` via **extensions** (capabilities honest-fail) |
| **联动音频片** | Auto audio-track twin of imported video; skip in BGM sync |

## Directory Structure

```
app/
  main_qt6.py              # Entry
  core/                    # Business logic (preview, timeline, ffmpeg, AI…)
  modules/lego/            # LEGO UI modules (editor, home, settings…)
docs/
  现行技术文档.md          # ★ 唯一开发文档(单一事实源)
  _archive/                # 历史文档归档(不再作为现行依据)
scripts/
  frozen_zone_guard.py     # 冻结区机器校验
```

## Coding Conventions

- **Class names**: PascalCase
- **Methods/functions**: snake_case
- **Private members**: `_` prefix
- **Constants**: UPPER_SNAKE_CASE
- **Comments**: Required on classes and core methods
- **Never delete existing features casually** — extend; 「最小入侵、最大兼容」
- Track indices: `find_track_index_by_type`, never hardcode `track == 1`

## Rules

1. Read [`docs/现行技术文档.md`](docs/现行技术文档.md)（单一事实源）before coding；历史细节查 [`docs/_archive/knowledge/INDEX.md`](docs/_archive/knowledge/INDEX.md)（仅回溯，非现行依据）
2. Understand existing business logic before adding features
3. Make minimal changes — don't break existing functionality
4. Layer separation: UI renders, core processes data, main window dispatches
5. All dialogs must have a parent window
6. Handle exceptions: validate inputs, prevent duplicate clicks, show errors / log warnings
7. After architecture or bugfix changes, write back to `docs/现行技术文档.md`（唯一开发文档）

## Issue Tracker

- Location: GitHub Issues
- Triage labels: `bug`, `feature`, `enhancement`, `documentation`

## 冻结区校验

```bash
python scripts/frozen_zone_guard.py
```
