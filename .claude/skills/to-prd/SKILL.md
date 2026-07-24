---
name: to-prd
description: Turn the current conversation context into a PRD. No interview — just synthesizes what you've already discussed.
---

# To-PRD — 生成需求文档

When the user has discussed a feature or change and wants a formal PRD, synthesize the conversation into a structured document.

## Rules

1. **No new interviews.** Use only what has been discussed.
2. **Ask about module scope.** Before creating the PRD, confirm which modules/layers are affected.
3. **Structure matters.** Use the template below exactly.
4. **Save as an issue.** Output the PRD as a GitHub issue or markdown file.

## PRD Template

```markdown
# PRD: [Feature Name]

## Summary
One paragraph describing what we're building and why.

## Acceptance Criteria
- [ ] Criterion 1
- [ ] Criterion 2

## Technical Design

### Modules Affected
- `app/modules/lego/xxx.py` — [what changes]
- `app/core/xxx.py` — [what changes]

### Architecture Decisions
- Decision 1: [rationale]
- Decision 2: [rationale]

### Data Flow
Describe how data moves through the system.

### UI Changes
Describe new screens, dialogs, or layout changes.

## Testing Plan
- [ ] Test case 1
- [ ] Test case 2

## Risks
- Risk 1: [mitigation]
```

## PyQt6-Specific PRD Fields

Always include:
- **Signal/Slot Changes** — new signals, modified connections
- **Thread Safety** — any background work needs main-thread UI updates
- **QSS/Styling** — new styles or theme considerations
- **Memory Management** — parent-child widget relationships

## When to Use

- After a `/grill-me` session
- Before starting any feature larger than a single file
- When multiple developers need to understand the plan
