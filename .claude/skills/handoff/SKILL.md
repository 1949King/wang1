---
name: handoff
description: Compact the current conversation into a handoff document so another agent can continue the work.
---

# Handoff — 交接文档

When switching agents or ending a session, create a compact handoff document so the next agent can pick up exactly where we left off.

## The Format

```markdown
# Handoff: [Feature/Task Name]

## Current State
What has been done so far. Be specific.

## What's Next
The very next action item. Should be completable in one session.

## Context
- Files modified: [list]
- Key decisions: [list]
- Open questions: [list]

## Constraints
- Technical constraints discovered
- Patterns to follow
- Gotchas to avoid
```

## Rules

1. **Be specific, not verbose.** The next agent needs facts, not narratives.
2. **Include file paths.** Always use absolute paths from project root.
3. **List decisions made.** Why we chose approach A over B.
4. **Note what NOT to do.** "Don't touch X because Y" is often more valuable than "Do Z".

## PyQt6-Specific Handoff Fields

Always include:
- **Signal/slot connections made** — list all new connections
- **QSS styles added/modified** — reference the stylesheet file
- **Widget parent relationships** — note any new parent-child hierarchies
- **Thread considerations** — any background work or QTimer usage

## Example

```markdown
# Handoff: Help Module Redesign

## Current State
- Redesigned `app/modules/lego/help_module.py` with Feishu-style UI
- Left nav tree (220px) + right content area implemented
- 30 documents across 5 categories defined

## What's Next
- Add chapter-level navigation in the tree (3rd level nodes)
- Implement auto-scroll to chapter when clicked

## Context
- Files modified: `app/modules/lego/help_module.py`
- Key decisions: Used QTreeWidget instead of QListView for hierarchy
- Open questions: Should chapter nodes be collapsed by default?

## Constraints
- Don't modify `app/modules/lego/modules.py` — it's the module registry
- All dialogs need parent=`self` to avoid orphan windows
```
