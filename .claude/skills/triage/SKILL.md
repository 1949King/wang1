---
name: triage
description: Triage issues through a state machine of triage roles. Use when processing a backlog of issues.
---

# Triage — 问题分类

When the user has a backlog of issues (GitHub, Linear, or local), triage them systematically.

## The State Machine

```
NEW → NEEDS_INFO → READY → IN_PROGRESS → DONE
              ↓
           CLOSED (won't fix, duplicate)
```

## Triage Roles

For each issue, assign one of these roles:

| Role | Action |
|------|--------|
| `bug` | Reproduce → minimize → fix |
| `feature` | Align requirements → design → implement |
| `enhancement` | Low-priority improvement, batch with related work |
| `documentation` | Update docs, examples, or comments |
| `wontfix` | Close with explanation |
| `duplicate` | Link to existing issue, close |

## Process

1. **Read the issue.** Don't skip any details.
2. **Classify.** Pick the role above.
3. **Add labels.** Apply the appropriate label.
4. **Estimate effort.** High / Medium / Low.
5. **Link related issues.** "Related to #X", "Blocks #Y".
6. **Assign priority.** P0 (critical), P1 (important), P2 (nice-to-have).

## PyQt6-Specific Triage

- **Crash/flash issues** → P0 `bug` — always highest priority
- **UI rendering issues** → P1 `bug` — check QSS and widget hierarchy
- **Signal/slot memory leaks** → P1 `bug` — use `weakref` or explicit disconnect
- **Performance issues** → P1 `enhancement` — profile before optimizing
- **Feature requests** → P2 `feature` — align with product roadmap

## Output Format

```
## Triage Report

| # | Title | Role | Priority | Effort | Notes |
|---|-------|------|----------|--------|-------|
| 1 | App crashes on startup | bug | P0 | High | Reproducible, see logs |
| 2 | Add dark mode toggle | feature | P2 | Medium | See design spec |
```
