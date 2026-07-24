---
name: tdd
description: Test-driven development with a red-green-refactor loop. Use for any feature or bugfix.
---

# TDD — 测试驱动开发

## Core Rule

**Always write a failing test first, then write the minimum code to pass it, then refactor.**

## The Loop

1. **RED** — Write a test that fails. Run it. Confirm it fails for the right reason.
2. **GREEN** — Write the minimum code to make it pass. No cleverness. No abstraction.
3. **REFACTOR** — Clean up both test and code. Improve names, extract functions, remove duplication.
4. Repeat.

## Rules

- **One test at a time.** Do not batch multiple tests. Write one, make it pass, move on.
- **Test behavior, not implementation.** Tests should verify what the code does, not how it does it.
- **Test the unhappy path.** Always test edge cases and error conditions.
- **Name tests descriptively.** `it_should_return_empty_array_when_no_items_exist` not `test_1`.

## PyQt6-Specific TDD

For UI components:
1. Test data logic first (the model layer)
2. Test signal/slot connections
3. Test UI state changes (enable/disable, visibility)
4. Use `qtbot` for interaction testing

## When to Skip TDD

- UI pixel-perfect styling changes
- Documentation updates
- Configuration file changes
- Quick exploratory prototypes (but convert to tests before shipping)
