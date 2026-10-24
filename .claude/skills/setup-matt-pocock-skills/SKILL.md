---
name: setup-matt-pocock-skills
description: Verify CONTEXT.md is loaded and confirm which skills are available for this project.
---

# Setup Matt Pocock Skills

This skill verifies the project context is loaded and lists available skills.

## What's Available

| Skill | Purpose |
|-------|---------|
| `/grill-me` | Ask questions to align on requirements |
| `/grill-with-docs` | Same as grill-me + uses CONTEXT.md shared language |
| `/tdd` | Test-driven development (RED → GREEN → REFACTOR) |
| `/diagnose` | Systematic bug diagnosis loop |
| `/zoom-out` | Get big-picture context of unfamiliar code |
| `/caveman` | Ultra-compressed communication mode |
| `/triage` | Classify and prioritize issues |
| `/to-prd` | Generate a PRD from conversation |
| `/to-issues` | Break a plan into vertical-slice issues |
| `/improve-codebase-architecture` | Find architecture improvement opportunities |
| `/handoff` | Create a handoff document for the next agent |
| `/prototype` | Build a throwaway prototype |
| `/write-a-skill` | Create a new skill |
| `/pyqt6-ui-review` | Review PyQt6 UI code for best practices |

## Project Context

The project context file is at `CONTEXT.md` in the project root.

It contains:
- Project overview and tech stack
- Key terminology (shared language)
- Directory structure
- Coding conventions
- 6 core rules

## Workflow Recommendation

1. **Start with** `/grill-with-docs` for any new feature
2. **Generate** `/to-prd` once aligned
3. **Break into** `/to-issues` if large
4. **Implement** each issue with `/tdd`
5. **Review** UI code with `/pyqt6-ui-review`
6. **Periodically run** `/improve-codebase-architecture`
7. **Before handoff** use `/handoff`

## PyQt6-Specific Workflow

For this project, the recommended order is:

1. `/grill-with-docs` → Understand what module and layer to modify
2. `/zoom-out` → Trace signal/slot chains and dependencies
3. `/tdd` → Write tests for core logic first
4. Implement → Follow layer separation rules
5. `/pyqt6-ui-review` → Check memory, signals, styling
6. `/handoff` → Document what was done

## Context.md Check

Before starting any work:
1. Read `CONTEXT.md` — it has the shared language
2. Check which modules are affected
3. Verify layer separation (core vs modules vs ui)
4. Follow the 6 rules listed in CONTEXT.md
