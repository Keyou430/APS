---
name: apple-design
description: Apple's UI/UX principles distilled from WWDC talks — fluid interfaces, materials, typography, and accessibility for web development. Use when building UI that should feel native and polished, especially modals, sheets, drawers, cards, and gesture-driven interactions.
---

# Apple Design Principles for the Web

This skill encodes Apple's Human Interface design principles — chiefly from WWDC 2018's "Designing Fluid Interfaces" and WWDC 2020's "The Details of UI Typography" — into concrete, web-applicable rules for motion, materials, typography, and accessibility.

## Core Philosophy

Fluid interfaces feel like an extension of the user, not a computer. Motion must:
1. Start from the **current on-screen value**
2. Inherit the user's **velocity**
3. Project **momentum forward**
4. Be **interruptible and redirectable** at any instant

**Springs** are the tool that makes this natural — they are physics-based, interruptible, and velocity-aware by default.

---

## 1. Fluid Interfaces — The Principles

### 1.1 Response — Kill Latency

Respond on **pointer-down**, not on release. Feedback must be continuous during the interaction.

```css
.button:active {
  transform: scale(0.97);
  transition: transform 100ms ease-out;
}
```

### 1.2 Direct Manipulation — 1:1 Tracking

Touch and content move together. Use Pointer Events with `setPointerCapture`. Track velocity history via recent `pointermove` events. Respect the grab offset (`clientY - top`).

```js
el.addEventListener('pointerdown', (e) => {
  el.setPointerCapture(e.pointerId);
  const grabOffset = e.clientY - el.getBoundingClientRect().top;
  // Track position + timestamp history for velocity
});
```

### 1.3 Interruptibility (MOST IMPORTANT)

Every animation must be interruptible mid-flight. **Never lock input during a transition.**

- Always animate from the **presentation value** (current live transform), not the target
- Avoid CSS transitions and `@keyframes` for gesture-driven UI — springs handle this naturally
- Blend velocity on reversal to avoid "brick wall" discontinuities
- Decompose 2D motion into independent X/Y springs

> A closing modal the user grabs again should follow the finger — not finish closing first, then reopen.

### 1.4 Behavior over Animation — Use Springs

Springs respond to new input by changing the target. Apple's parameters:
- **Damping ratio**: 1.0 = critically damped (no bounce); < 1.0 = overshoot
- **Response**: how quickly it reaches target (seconds)

| Interaction | Damping | Response |
|---|---|---|
| Move / reposition (PiP) | 1.0 | 0.4 |
| Rotation | 0.8 | 0.4 |
| Drawer / sheet | 0.8 | 0.3 |

**Safe default**: critically damped springs everywhere; bounce only for momentum-driven interactions (flicks, throws).

```js
import { animate } from 'motion';

// Critically damped default (no overshoot)
animate(el, { y: 0 }, { type: 'spring', bounce: 0, duration: 0.4 });

// Momentum interaction — bounce only because a flick preceded it
animate(el, { y: target }, { type: 'spring', bounce: 0.2, duration: 0.4 });
```

### 1.5 Velocity Handoff

On gesture end, pass the pointer's release velocity as the spring's initial velocity — no seam between drag and animation.

```js
// Normalize velocity for spring library
const relativeVelocity = gestureVelocity / (targetValue - currentValue);
// Or pass raw px/s if the library supports it
```

### 1.6 Momentum Projection

Don't snap to nearest boundary from release. Project resting position using velocity:

```js
function project(initialVelocity, decelerationRate = 0.998) {
  return (initialVelocity / 1000) * decelerationRate / (1 - decelerationRate);
}
// Then snap to the nearest target of the projected endpoint
```

### 1.7 Spatial Consistency

Enter/exit along symmetric paths. Anchor interactions to their source:
```css
transform-origin: var(--trigger-origin); /* dynamic, from trigger element */
```

Mirror easing on reversible transitions.

### 1.8 Hint in Gesture Direction

Intermediate motion should telegraph the outcome. A partial swipe shows where the element will go.

### 1.9 Rubber-banding

Soft boundaries at edges:

```js
function rubberband(overshoot, dimension, constant = 0.55) {
  return (overshoot * dimension * constant) / (dimension + constant * Math.abs(overshoot));
}
```

### 1.10 Gesture Design Details

- **Tap**: highlight on touch-down, commit on touch-up, ~10px hysteresis
- **Drag/swipe**: ~10px threshold before committing direction
- Detect all gestures in parallel, cancel losers once intent is clear

### 1.11 Frame-level Smoothness

- Keep per-frame positional change below perception threshold
- Animate only compositor-friendly properties (`transform`, `opacity`)
- Use `will-change` sparingly (add before animation, remove after)
- Use `requestAnimationFrame` for custom animation loops

### 1.12 Materials & Depth — Translucency

Use `backdrop-filter: blur()` + semi-transparent backgrounds for nav/toolbars/sheets.

```css
.toolbar {
  background: rgba(255, 255, 255, 0.6);
  backdrop-filter: blur(20px) saturate(180%);
  border-top: 1px solid rgba(255, 255, 255, 0.4); /* light catching the material */
}
```

Rules:
- Darker materials = heavier hierarchy
- Bigger surfaces = stronger blur + deeper shadow
- Vibrancy for text legibility on translucent surfaces
- Scroll edge effects instead of hard dividers
- Animate blur radius and scale together on enter/exit

Accessibility fallback:
```css
@media (prefers-reduced-transparency: reduce) {
  .toolbar { background: white; backdrop-filter: none; }
}
```

### 1.13 Multimodal Feedback

Motion + sound + haptics must fire on the **same frame**. Causality, harmony, utility.

### 1.14 Reduced Motion & Accessibility

Always respond to these media queries:
```css
@media (prefers-reduced-motion: reduce) {
  /* Replace slides/springs with opacity cross-fades */
  /* Drop elastic/overshoot entirely */
  .animated { animation: none; transition: opacity 200ms ease-out; }
}
```

Also respect: `prefers-reduced-transparency: reduce`, `prefers-contrast: more`.

### 1.15 Typography

Apple designs type to change shape with size (WWDC 2020):

- **Tracking (letter-spacing)**: negative for large display text, slightly positive for small text
- **Leading (line-height)**: tight on large headings, looser on body copy
- **Build hierarchy from weight + size + leading as a set**, not size alone
- **Respect the user's text-size setting** (Dynamic Type). Scale layout in `rem`/`em`, not fixed `px`
- **Default to the system font** — it already ships optical sizing, tracking tables, and legibility tuning

```css
:root { font: 100%/1.5 system-ui, sans-serif; }

.display {
  font-size: clamp(2rem, 5vw, 4rem);
  line-height: 1.05;
  letter-spacing: -0.02em;
  font-optical-sizing: auto;
}

.caption {
  font-size: 0.75rem;
  letter-spacing: 0.01em;
  line-height: 1.4;
}
```

### 1.16 Design Foundations (8 Principles)

1. **Purpose** — every element must earn its place
2. **Agency** — put the user in control; animations follow their lead
3. **Responsibility** — protect privacy and data
4. **Familiarity** — build on what users already know
5. **Flexibility** — adapt to device, context, and input method
6. **Simplicity** — remove until only the essential remains
7. **Safety** — prevent destructive actions from being too easy
8. **Accessibility** — design for everyone from the start

### 1.17 Understanding & Joy

Beyond function, design should help users **understand** what's happening and feel **joy** in the interaction. Subtle spring bounces on success states, smooth transitions between modes — these small moments compound into a premium feel.

---

## When to Use This Skill

Invoke when:
- Building modals, sheets, drawers, or bottom sheets
- Creating drag-to-dismiss or swipe interactions
- Designing toolbars, navigation bars, or floating elements
- Setting up typography scale for a project
- Building cards or surfaces with depth/hierarchy
- Adding gesture-based interactions
- Auditing existing UI for polish

## When NOT to Use

- Keyboard-driven interfaces (no animations on keyboard shortcuts)
- High-frequency interactions (100+/day — reduce or remove animation)
- Data-heavy dashboards (prioritize responsiveness over motion)
- When the tech stack doesn't support the required CSS properties
