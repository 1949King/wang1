# AI Short Drama Editor — Context

## Project Overview

A PyQt6-based desktop application(**拾光剪影**)focused on short-drama **editing** and **AI canvas** (agent + digital human). Publishing/finder plugins are interface shells only.

**现行技术文档(单一事实源·优先阅读)**: [`docs/现行技术文档.md`](docs/现行技术文档.md)
**完整知识库(分页)**: [`docs/knowledge/INDEX.md`](docs/knowledge/INDEX.md)

## Tech Stack

- **UI Framework**: PyQt6
- **Video Processing**: FFmpeg, OpenCV/PyAV, OpenShot/MLT libraries
- **AI Integration**: Ollama (local), various cloud APIs (DeepSeek, OpenAI, etc.)
- **Language**: Python 3.x
- **Architecture**: Layered — `app/core/` (business logic), `app/modules/lego/` (feature UI), EventBus

## Key Terminology

完整表见 [`docs/knowledge/01-glossary.md`](docs/knowledge/01-glossary.md).常用:

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
  knowledge/               # ★ 项目知识库(INDEX + 00–07 + catalog)
  P0_CAPCUT_ALIGN.md       # 剪映对齐分期
scripts/
  sync_knowledge.py        # 刷新知识库清单
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

1. Read [`docs/现行技术文档.md`](docs/现行技术文档.md)（单一事实源）before coding；细节查 [`docs/knowledge/INDEX.md`](docs/knowledge/INDEX.md)
2. Understand existing business logic before adding features
3. Make minimal changes — don't break existing functionality
4. Layer separation: UI renders, core processes data, main window dispatches
5. All dialogs must have a parent window
6. Handle exceptions: validate inputs, prevent duplicate clicks, show errors / log warnings
7. After architecture or bugfix changes, update `docs/knowledge/05-known-issues.md` (and related pages)

## Issue Tracker

- Location: GitHub Issues
- Triage labels: `bug`, `feature`, `enhancement`, `documentation`

## Sync

```bash
python scripts/sync_knowledge.py
```
