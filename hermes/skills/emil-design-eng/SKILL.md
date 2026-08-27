---
name: emil-design-eng
description: Design engineering principles from Emil Kowalski — animation framework, component design, spring physics, performance rules, and the philosophy of taste. Use when building UI components, adding animations, or making design decisions about motion and interaction.
---

# Design Engineering

Design engineering principles and animation framework from Emil Kowalski (creator of Sonner, Vaul, animations.dev; former design engineer at Vercel and Linear).

## Core Philosophy

Three tenets drive every decision:

1. **Taste is trained, not innate** — Good taste comes from surrounding yourself with great work, reverse-engineering animations, and practicing relentlessly. It's a skill you build.
2. **Unseen details compound** — Most details users never consciously notice. The aggregate of invisible correctness creates interfaces people love without knowing why. (Paul Graham: "like a thousand barely audible voices all singing in tune")
3. **Beauty is leverage** — People select tools based on overall experience, not just functionality. Good defaults and animations are real differentiators.

## Register Distinction

Every design task falls into one of two registers:

| | Product | Brand |
|---|---|---|
| **Examples** | App UI, dashboard, tool | Marketing site, landing page |
| **Priority** | Design SERVES the product | Design IS the product |
| **Animation** | Stricter duration limits, tactile feedback, keyboard interactions, invisible correctness | Can be looser, more expressive, longer |

**When in doubt, default to Product register.**

---

## Animation Decision Framework

Before writing any animation code, answer these four questions in order:

### 1. Should this animate at all?

| Frequency | Decision |
|---|---|
| 100+ times/day (keyboard shortcuts, command palette) | **No animation. Ever.** |
| Tens of times/day (hover effects, list navigation) | Remove or drastically reduce |
| Occasional (modals, drawers, toasts) | Standard animation |
| Rare/first-time (onboarding, celebrations) | Can add delight |

**Never animate keyboard-initiated actions** — they feel slow and disconnected. Raycast has no open/close animation, and that's optimal.

### 2. What is the purpose?

Every animation must justify itself. Valid purposes:
- **Spatial consistency** — where did this come from / go to?
- **State indication** — loading, active, disabled, expanded
- **Explanation** — causality, what just happened
- **Feedback** — confirming an action was received
- **Preventing jarring changes** — layout shifts, content swaps

If the only answer is "it looks cool" and it's seen often, **don't animate**.

### 3. What easing should it use?

| Interaction | Easing |
|---|---|
| Entering | `ease-out` (starts fast, feels responsive) |
| Exiting | `ease-in` |
| On-screen movement | `ease-in-out` |
| Hover/color change | `ease` |
| Constant motion | `linear` |

**Critical: Use custom easing curves.** Built-in CSS easings are too weak.

```css
:root {
  --ease-out: cubic-bezier(0.23, 1, 0.32, 1);
  --ease-in-out: cubic-bezier(0.77, 0, 0.175, 1);
  --ease-drawer: cubic-bezier(0.32, 0.72, 0, 1); /* iOS-like drawer */
}
```

**Never use `ease-in` for UI entry animations** — it delays the initial movement, making the interface feel sluggish.

### 4. How fast should it be?

| Element | Duration |
|---|---|
| Button press feedback | 100–160ms |
| Tooltips, small popovers | 125–200ms |
| Dropdowns, selects | 150–250ms |
| Modals, drawers | 200–500ms |
| Marketing/explanatory | Can be longer |

**Rule: UI animations under 300ms.** A 180ms dropdown feels far more responsive than 400ms.

---

## Spring Animations

### Why Springs?

Springs feel more natural than duration-based animations because they simulate real physics. They are the gold standard for gesture-driven UI — inherently interruptible and velocity-aware.

### When to Use Springs

- Drag interactions with momentum
- Elements that should feel "alive" (like Apple's Dynamic Island)
- Gestures that can be interrupted mid-animation
- Decorative mouse-tracking interactions

### Spring Configuration

**Apple's approach (recommended):**
```js
import { animate } from 'motion';

animate(el, { y: 0 }, {
  type: 'spring',
  bounce: 0,      // 0.1–0.3 for momentum-driven
  duration: 0.4,  // perceptual duration
});
```

**Traditional physics (more control):**
```js
animate(el, { y: 0 }, {
  type: 'spring',
  stiffness: 100,  // spring tension
  damping: 10,     // friction/resistance
  mass: 1,         // inertia
});
```

Keep bounce **subtle (0.1–0.3)**. Avoid bounce in most UI contexts. Use it for drag-to-dismiss and playful interactions.

### Mouse-Tracking with Springs

Tying changes directly to mouse position feels artificial. Use springs to interpolate:

```jsx
import { useSpring } from 'framer-motion';

// Without spring: instant, artificial
const rotation = mouseX * 0.1;

// With spring: natural, has momentum
const springRotation = useSpring(mouseX * 0.1, {
  stiffness: 100,
  damping: 10,
});
```

This works because the animation is **decorative**. For functional graphs, no animation is better.

---

## Component Building Principles

### Popovers, Dropdowns, Tooltips

- **Must be origin-aware** — scale from their trigger, not center
- Use `--radix-popover-content-transform-origin` for Radix UI components
- `transform-origin` must be set dynamically based on trigger position

### Modals & Drawers

- Modals are **exempt from origin rules** (they stay centered)
- Drawers slide from the edge they're attached to
- Use the `--ease-drawer` curve for sheet/drawer animations

### Buttons

```css
.button:active {
  transform: scale(0.97);
  transition: transform 160ms ease-out;
}
```

### Tooltips

- Show instantly on **subsequent** hovers (skip delay after first open)
- First open: ~300ms delay is acceptable
- Exit: instant (no delay)

### Never Do These

- **Never animate from `scale(0)`** — start from `scale(0.95)` with `opacity: 0`
- **Never use `transition: all`** — specify the exact properties being animated
- **Never animate `width`/`height`** — use `transform: scale()` instead
- **Never use `ease-in` on UI entry** — it delays the moment users watch most

---

## CSS Transform Mastery

### Transform Properties

- Use `translateY` with percentages (libraries like Sonner/Vaul animate relative to element height)
- Prefer `scale()` over width/height to prevent layout shifts
- Use `preserve-3d` for depth effects and stacking card animations
- Dynamically set `transform-origin` so elements scale from their trigger point

### clip-path Animations

```css
.morph-enter {
  clip-path: inset(0 0 100% 0);
  animation: reveal 400ms ease-out forwards;
}

@keyframes reveal {
  to { clip-path: inset(0 0 0 0); }
}
```

`clip-path: inset()` allows sophisticated reveal animations without affecting document flow. Hardware-accelerated on modern browsers.

---

## Entry, Exit, and Stagger Patterns

### Asymmetric Timing

Fast entry for responsiveness, slower exit for spatial awareness:
```css
.enter { transition: opacity 200ms ease-out, transform 250ms var(--ease-out); }
.exit  { transition: opacity 150ms ease-in,  transform 150ms ease-in; }
```

### `@starting-style` (Modern CSS)

Animate DOM additions without React state:
```css
.popover {
  transition: opacity 200ms ease-out, transform 250ms var(--ease-out);
}
.popover:not([open]) {
  opacity: 0;
  transform: scale(0.95);
}
```

### Staggering

30–80ms delays between list items:
```css
.list-item:nth-child(1) { transition-delay: 0ms; }
.list-item:nth-child(2) { transition-delay: 40ms; }
.list-item:nth-child(3) { transition-delay: 80ms; }
/* etc. */
```

### Blur Bridge

Temporary blur filter to mask low-resolution states or imperfect crossfades:
```css
.loading { filter: blur(4px); transition: filter 300ms ease-out; }
.loaded  { filter: blur(0); }
```

---

## Performance Rules

### GPU-Composited Properties Only

Only these properties animate without triggering layout/paint:
- `transform` (translate, scale, rotate, skew)
- `opacity`
- `filter` (when composited)

### Hard Rules

```css
/* ✅ CORRECT */
transition: transform 200ms ease-out, opacity 200ms ease-out;
will-change: transform;

/* ❌ WRONG */
transition: all 300ms;       /* animates everything */
transition: width 300ms;     /* triggers layout */
transition: top 300ms;       /* triggers layout */
transition: margin 300ms;    /* triggers layout */
```

### will-change

Add before animation, remove after:
```css
.animating {
  will-change: transform;
}
/* Remove in JS after animation completes */
```

### Framer Motion Caution

Framer Motion `x`/`y`/`scale` props use CSS transforms under the hood, but complex animations can still cause jank. For performance-critical motion, use raw CSS transforms with WAAPI.

---

## When to Use This Skill

Invoke when:
- Building new UI components that need animation
- Deciding on easing curves and durations
- Setting up animation infrastructure for a project
- Reviewing component designs before implementation
- Choosing between CSS transitions, WAAPI, or springs
- Designing interaction patterns (drag, swipe, tap, hover)
