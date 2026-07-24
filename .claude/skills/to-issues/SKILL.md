---
name: to-issues
description: Break a plan, spec, or PRD into independently-grabbable GitHub issues using vertical slices.
---

# To-Issues — 拆分为任务

When the user has a PRD or plan, break it into vertical slices — each issue should be a narrow path through the system (schema → API → UI → tests).

## Rules

1. **Vertical slices, not horizontal layers.** Don't create "do all backend" then "do all frontend" issues.
2. **Each issue should be independently completable.** Someone should be able to pick up any issue and finish it without waiting for others.
3. **Include acceptance criteria in each issue.** No vague descriptions.
4. **Order by dependency.** If Issue B depends on Issue A, say so.

## The Process

1. Read the PRD/plan carefully.
2. Identify the natural vertical slices.
3. For each slice, write an issue with:
   - **Title**: Clear, action-oriented
   - **Description**: What needs to be built
   - **Acceptance criteria**: Checkbox list
   - **Technical notes**: Relevant files, patterns, constraints
   - **Dependencies**: Links to blocking issues
4. Output as a table or numbered list.

## Example Vertical Slices

For "Add AI subtitle generation":

| # | Title | Files | Priority |
|---|-------|-------|----------|
| 1 | Core subtitle engine with Ollama | `app/core/subtitle_engine.py` | P0 |
| 2 | Subtitle track in timeline | `app/core/timeline_manager.py` | P1 |
| 3 | Subtitle editor UI | `app/modules/lego/subtitle_editor.py` | P1 |
| 4 | Subtitle export in render pipeline | `app/modules/render/export.py` | P2 |

## PyQt6-Specific Slicing

- UI modules (`app/modules/lego/`) should be separate from core logic
- Each module can be developed independently if the interface is defined
- Signal/slot contracts should be defined in the first issue
