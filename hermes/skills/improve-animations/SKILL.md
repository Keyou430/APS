---
name: improve-animations
description: Full codebase animation audit across 8 dimensions, generates prioritized, self-contained fix plans. Never modifies source code directly. Use when asked to improve animations broadly across a project.
disable-model-invocation: true
---

# Improve Animations

Systematically audit and prioritize animation improvements across an entire codebase. **This skill never modifies source code directly.** It produces prioritized plans that another agent (or developer) executes.

## Workflow

```
Audit → Prioritize → Generate Plans → Execute (by another agent)
```

---

## 1. Eight-Dimension Audit

Scan the **entire codebase** (not just a diff) across these 8 dimensions:

| Dimension | What to check |
|---|---|
| **Purpose & Frequency** | Does every animation have a clear purpose? Are high-frequency interactions over-animated? |
| **Easing & Duration** | Correct easing curves? Durations within bounds? UI animations under 300ms? |
| **Physicality** | Spring parameters natural? Inertia, damping appropriate? |
| **Interruptibility** | Can animations be interrupted mid-flight? CSS transitions, not keyframes for gesture-driven UI? |
| **Performance** | Animate only `transform` and `opacity`? Any layout thrashing or recalc storms? |
| **Accessibility** | `prefers-reduced-motion` honored? `hover: hover` and `pointer: fine` gates on hover animations? |
| **Cohesion** | Consistent easing variables, durations, spring configs across all components? |
| **Missed Opportunities** | What interactions should have motion feedback but don't? |

---

## 2. Prioritized Findings

Output ranked by severity:

1. **Critical** — Feel-breaking regressions, keyboard/high-frequency animation, `scale(0)`/`ease-in`, non-GPU animation
2. **High** — Wrong origin, missing interruptibility, UI > 300ms
3. **Medium** — Missed stagger opportunities, symmetric timing, cohesion issues
4. **Low** — Polish enhancements, subtle improvements

Present as a markdown table:

| Priority | File | Issue | Dimension | Fix |
|----------|------|-------|-----------|-----|
| Critical | `src/dropdown.tsx:42` | `ease-in` on dropdown entry | Easing | Replace with `cubic-bezier(0.23, 1, 0.32, 1)` |
| High | `src/modal.tsx:28` | `scale(0)` entry | Physicality | Use `scale(0.95)` + `opacity: 0` |
| Medium | `src/list.tsx:15` | No stagger on list items | Polish | Add 40ms `transition-delay` increments |

---

## 3. Generate Self-Contained Plans

For each finding the user wants to fix, write a plan file to `plans/` directory:

```markdown
# Fix: dropdown-easing-001
## Target
src/components/dropdown.tsx:42

## Current
```css
.dropdown-enter { animation: dropdownIn 200ms ease-in; }
```

## Proposed
```css
.dropdown-enter {
  animation: dropdownIn 200ms cubic-bezier(0.23, 1, 0.32, 1);
}
```

## Verification
- [ ] Dropdown opens and closes — opening should feel snappy
- [ ] Check with frame-by-frame — no initial delay
- [ ] Verify `--ease-out` CSS variable is being used (or add one)
```

Each plan must be **self-contained** — one file, one fix, all context included. Another agent should be able to execute it without additional research.

---

## 4. Execution

Plans are executed by another agent or by the developer. `improve-animations` never touches source code.

---

## Invocation Modes

| Command | Scope |
|---|---|
| `improve the animations in this codebase` | Full audit, all dimensions |
| `improve-animations quick` | Hotspots only (high-frequency/critical animations) |
| `improve-animations performance` | Performance dimension only |
| `improve-animations plan add press feedback to all buttons` | Targeted fix for a specific issue |
| `improve-animations execute plans/001-fix-dropdown-easing.md` | Execute a specific generated plan |

---

## Reference: Easing Curves

```css
:root {
  --ease-out: cubic-bezier(0.23, 1, 0.32, 1);
  --ease-in-out: cubic-bezier(0.77, 0, 0.175, 1);
  --ease-drawer: cubic-bezier(0.32, 0.72, 0, 1);
}
```

## Reference: Duration Budgets

| Element | Duration |
|---|---|
| Button press | 100–160ms |
| Tooltips, popovers | 125–200ms |
| Dropdowns, selects | 150–250ms |
| Modals, drawers | 200–500ms |

## Reference: Core Rules (quick reference)

- UI animations < 300ms
- Animate only `transform` + `opacity`
- Never `scale(0)` — use `scale(0.95)`
- Never `transition: all`
- Never `ease-in` on entry
- Popovers scale from trigger, not center
- Keyboards/high-frequency → no animation
- Always `prefers-reduced-motion`
