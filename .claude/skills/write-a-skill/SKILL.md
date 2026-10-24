---
name: write-a-skill
description: Create new skills with proper structure, progressive disclosure, and bundled resources.
---

# Write a Skill — 创建技能

When the user wants to create a new agent skill, guide them through the process.

## Skill Structure

```
.claude/skills/{skill-name}/
├── SKILL.md          # Required: The skill definition
├── metadata.json     # Optional: Display name, description
└── resources/        # Optional: Supporting files
```

## SKILL.md Template

```markdown
---
name: {skill-name}
description: {One sentence: what it does and when to use it}
---

# {Skill Title}

## When to Use
- Scenario 1
- Scenario 2

## Rules
1. Rule 1
2. Rule 2

## The Process
Step-by-step instructions.

## Output Format
What the agent should produce.

## Examples
Concrete examples of usage.
```

## Rules for Writing Skills

1. **One skill, one responsibility.** Don't combine unrelated behaviors.
2. **Progressive disclosure.** Start with the basics, add advanced options later.
3. **Use markdown headers for structure.** Agents parse these for context.
4. **Include concrete examples.** Abstract instructions are harder to follow.
5. **Test the skill.** After creating it, run `/setup-matt-pocock-skills` and try it.

## Naming Conventions

- Use kebab-case: `grill-me`, `to-prd`, `improve-codebase-architecture`
- Start with a verb when it's an action: `triage`, `diagnose`, `prototype`
- Prefix with `to-` when it transforms input: `to-prd`, `to-issues`

## metadata.json

```json
{
  "name": "Skill Display Name",
  "description": "Short description for the skill picker",
  "version": "1.0.0"
}
```

## PyQt6-Specific Skills

When creating skills for this project, always include:
- PyQt6-specific patterns where relevant
- References to `CONTEXT.md` for project terminology
- Layer separation rules (core vs modules vs ui)
