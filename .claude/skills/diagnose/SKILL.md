---
name: diagnose
description: Disciplined diagnosis loop for hard bugs and performance regressions.
---

# Diagnose — 诊断循环

## The Loop

1. **REPRODUCE** — Can you trigger the bug consistently? Write down exact steps.
2. **MINIMIZE** — What is the smallest code that triggers the bug? Strip away everything else.
3. **HYPOTHESIZE** — What do you think is causing it? Write it down.
4. **INSTRUMENT** — Add logging/assertions to test your hypothesis.
5. **FIX** — Apply the smallest possible fix.
6. **REGRESSION-TEST** — Add a test that prevents this bug from coming back.

## Rules

- **Never fix without understanding.** If you fix it but don't know why it was broken, you haven't fixed it.
- **Write down each step.** Keep a diagnosis log. This helps when you get stuck.
- **Binary search the code.** Comment out halves of the code to narrow down where the bug is.
- **Check the logs.** Always read the full error trace before guessing.

## PyQt6-Specific Debugging

- Use `QApplication.instance().exit()` to prevent app hanging
- Check signal/slot connections with `sender.signalsBlocked()`
- Verify thread safety — UI updates must happen on main thread
- Use `QTimer.singleShot(0, callback)` for deferred UI updates

## Performance Diagnosis

1. Profile first — don't guess which part is slow
2. Use `QElapsedTimer` for precise measurements
3. Check for:
   - Unnecessary widget recreation
   - Blocking the main thread
   - Memory leaks from signal/slot references
   - Unoptimized paint events
