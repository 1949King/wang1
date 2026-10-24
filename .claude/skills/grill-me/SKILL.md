---
name: grill-me
description: Get relentlessly interviewed about a plan or design until every branch of the decision tree is resolved. Use when starting a new feature or making a significant change.
---

# Grill Me — 需求对齐

When the user wants to build something new or make a significant change, ask questions to understand the full scope BEFORE writing any code.

## Rules

1. **One question at a time.** Don't overwhelm the user with a wall of questions.
2. **Start with the goal.** "What are you trying to achieve?" is always the first question.
3. **Dig into edge cases.** What happens when X fails? What if the user does Y?
4. **Challenge assumptions.** If something sounds too simple, ask "what could go wrong?"
5. **Confirm understanding.** After the grilling session, summarize what you learned and ask the user to confirm.

## When to Use

- Starting a new feature
- Making architectural changes
- Refactoring existing code
- Anything that touches more than 3 files

## The Session

Ask questions until you can answer these:

- [ ] What is the user trying to build?
- [ ] What are the key technical decisions?
- [ ] What are the edge cases?
- [ ] What existing code will be affected?
- [ ] How will we know it works?

Only after all checkboxes are checked, propose a plan.
