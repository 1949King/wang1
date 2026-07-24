---
name: grill-with-docs
description: Enhanced grilling session that challenges your plan against CONTEXT.md, sharpens terminology, and updates shared language inline. Use for any significant feature.
---

# Grill With Docs — 深度需求对齐

This is `/grill-me` with superpowers. It combines the grilling session with the project's shared language (`CONTEXT.md`).

## The Process

1. **Read CONTEXT.md first.** Understand the project's domain language.
2. **Challenge the plan against existing concepts.** Is the user using the right terms?
3. **Ask one question at a time.** Don't overwhelm.
4. **Identify missing terms.** If the user describes something not in CONTEXT.md, ask if it should be added.
5. **Update CONTEXT.md inline.** After the session, propose updates to the context file.

## Rules

1. **Use the shared language.** If CONTEXT.md says "时间线" for timeline, use that term.
2. **Flag new concepts.** When the user introduces something new, flag it: "This sounds like a new concept. Should we add it to CONTEXT.md?"
3. **Check module boundaries.** Ask: "Which module does this belong to? `app/core/`, `app/modules/lego/`, or `app/ui/`?"
4. **Verify signal/slot contracts.** For PyQt6: "What signals does this component emit? What does it listen to?"
5. **Reference CONTEXT.md rules.** The project has 6 coding rules — check compliance.

## The Session Questions

Ask until all are answered:

- [ ] What is the user building? (in project terms)
- [ ] Which modules/layers are affected?
- [ ] What signals/slots are involved?
- [ ] Are there new domain concepts?
- [ ] What existing code will be modified?
- [ ] How do we verify it works?
- [ ] What could go wrong? (PyQt6-specific: memory leaks, thread safety, orphan windows)

## After the Session

1. Summarize the agreed plan.
2. Propose CONTEXT.md updates for any new terms.
3. Propose a PRD using `/to-prd` if the scope warrants it.
4. Break into issues using `/to-issues` if it's large.

## Example

```
User: "I want to add auto-subtitle feature"

Agent: "Great. Let me check CONTEXT.md... I see 'AI剪辑' is AI-assisted editing and '时间线' is the timeline. 

First question: Should subtitles appear on the 时间线 as a separate track, or inline with video clips?"

... (grilling continues) ...

Agent: "I notice 'subtitle track' isn't in CONTEXT.md yet. Should I add it?"
```
