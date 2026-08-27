---
name: animation-vocabulary
description: Reverse-lookup glossary translating vague descriptions of web animations into precise canonical terms. Use when you know what an animation looks/feels like but don't know its professional name.
---

# Animation Vocabulary

Reverse-lookup glossary that turns vague descriptions of web animations and motion effects into their precise, canonical terms. For **naming** an effect — not designing or building one.

## How to Use

1. Read the user's description for **intent**, not keywords
2. Match to the glossary below
3. Return the canonical term
4. If multiple terms fit, list the best match first with 1–2 alternatives and a one-line explanation of differences

---

## Glossary

### Entrances & Exits

| Term | Description |
|---|---|
| **Fade in/out** | Element gradually appears/disappears via opacity change |
| **Slide in** | Element moves into view from a direction (up/down/left/right) |
| **Scale in** | Element grows from a smaller size to full size |
| **Pop in** | Quick scale-up with slight overshoot then settle — the "bouncy" entrance |
| **Reveal** | Content uncovered by a mask, clip, or expanding container |
| **Enter/Exit** | An element arriving or leaving the screen |

### Sequencing & Timing

| Term | Description |
|---|---|
| **Keyframes** | Predefined snapshots of an animation at specific points in time |
| **Interpolation / Tween** | Computing intermediate values between two known states |
| **Stagger** | Sequential delay between items in a group (typically 30–80ms) |
| **Orchestration** | Coordinating multiple animations to play in a specific order |
| **Delay** | Time before an animation starts |
| **Duration** | Total time an animation takes to complete |
| **Fill mode** | What state the element holds before/after the animation (`forwards`, `backwards`, `both`) |
| **Stepped animation** | Discrete jumps between states rather than smooth interpolation |

### Movement & Transforms

| Term | Description |
|---|---|
| **Translate** | Moving an element along X, Y, or Z axis |
| **Scale** | Changing an element's size proportionally |
| **Rotate** | Rotating an element around a point |
| **Skew** | Tilting an element along an axis |
| **3D tilt / Flip** | Rotating in 3D space with perspective |
| **Perspective** | The illusion of depth — objects farther away appear smaller |
| **Transform origin** | The anchor point from which transforms radiate |
| **Origin-aware animation** | Scaling/moving from the element's trigger point, not center |

### Transitions Between States

| Term | Description |
|---|---|
| **Crossfade** | One element fades out while another fades in — smooth, no movement |
| **Continuity transition** | An element smoothly transitions between two distinct states without disappearing |
| **Morph** | One shape or element smoothly transforms into another |
| **Shared element transition** | An element appears to move between two different containers/views |
| **Layout animation** | Automatic animation when an element's position or size changes in layout |
| **Accordion / Collapse** | Content expanding/collapsing vertically |
| **Direction-aware transition** | Animation direction adapts to user intent (e.g., swipe direction) |

### Scroll

| Term | Description |
|---|---|
| **Scroll reveal** | Elements animate into view when scrolled to |
| **Scroll-driven animation** | Animation progress tied directly to scroll position |
| **Parallax** | Different layers move at different speeds during scroll |
| **Page transition** | Full-page animation when navigating between pages |
| **View transition** | Browser API for animating between two page states |

### Feedback & Interaction

| Term | Description |
|---|---|
| **Hover effect** | Visual change when the pointer is over an element |
| **Press / Tap feedback** | Instant visual response to a click or touch (e.g., scale down) |
| **Hold to confirm** | Progressive animation that confirms an action after sustained press |
| **Drag** | Element follows the pointer/finger |
| **Drag to reorder** | Dragging to change list order |
| **Swipe to dismiss** | Swiping an item off-screen to remove it |
| **Rubber-banding** | Soft resistance when pulling past a boundary (iOS scroll bounce) |
| **Shake / Wiggle** | Rapid small oscillation — usually for error states |
| **Ripple** | Expanding circle from point of contact (Material Design) |

### Easing

| Term | Description |
|---|---|
| **Easing** | The rate of change over the course of an animation |
| **Ease-out** | Starts fast, decelerates — for entries |
| **Ease-in** | Starts slow, accelerates — for exits only |
| **Ease-in-out** | Slow start and end, fast middle |
| **Linear** | Constant speed throughout |
| **Cubic-bezier** | Custom easing curve defined by four control points |
| **Asymmetric easing** | Different timing for enter vs. exit |

### Spring Animations

| Term | Description |
|---|---|
| **Spring** | Physics-based animation that simulates a spring's motion |
| **Stiffness / Tension** | How strongly the spring pulls toward the target |
| **Damping** | Friction that reduces oscillation over time |
| **Mass** | Inertia — heavier objects move more slowly |
| **Bounce** | Overshoot past the target before settling |
| **Perceptual duration** | How long the spring *feels* like it takes (not wall-clock time) |
| **Momentum** | Velocity carried from a gesture into animation |
| **Velocity** | Speed and direction at a given instant |
| **Interruptible animation** | Animation that can be grabbed and redirected mid-flight |

### Looping & Ambient Motion

| Term | Description |
|---|---|
| **Marquee** | Continuous horizontal scroll of content |
| **Loop** | Animation that repeats indefinitely |
| **Alternate / Yoyo** | Animation that plays forward then reverses |
| **Orbit** | Element circles around a center point |
| **Pulse** | Repeated gentle scale or opacity oscillation |
| **Float** | Slow, gentle drift — ambient motion |
| **Idle animation** | Subtle motion for elements waiting for interaction |

### Polish & Effects

| Term | Description |
|---|---|
| **Blur** | Gaussian blur filter — can be animated |
| **Clip-path** | Revealing/hiding part of an element with a shape mask |
| **Mask** | Using one element's alpha channel to reveal another |
| **Line drawing** | Animating a stroke to reveal a path |
| **Text morph** | Words or characters smoothly transition to different text |
| **Skeleton / Shimmer** | Placeholder loading animation |
| **Number ticker** | Animated counting up or down to a target number |
| **Tabular numbers** | Fixed-width digits so numbers don't shift during animation |
| **Typewriter** | Characters appear one by one |

### Performance

| Term | Description |
|---|---|
| **Frame rate (FPS)** | How many frames render per second — 60fps is the target |
| **Jank** | Visible stutter from missed frames |
| **Dropped frame** | A frame that wasn't rendered in time |
| **Compositing** | GPU layer — where `transform`/`opacity` animations run |
| **will-change** | CSS hint to promote an element to its own compositor layer |
| **Layout thrashing** | Forced synchronous layout recalculations that kill performance |

---

## Examples

**User says:** "The bouncy thing when a popover opens"
→ **Pop in** (scale-up with slight overshoot then settle)

**User says:** "The iOS thing where you can't scroll past the top"
→ **Rubber-banding** (soft resistance at boundaries)

**User says:** "Elements fading in one after another"
→ **Stagger** (sequential delay between items)

**User says:** "The box grows from where I clicked"
→ **Origin-aware animation** (scaling from the trigger point, not center)

**User says:** "Smoothly changing from a card to a detail page"
→ **Shared element transition** (element appears to move between two views)
