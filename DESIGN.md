# Injenium Design System

## Intent

Injenium is a calm, approachable technical workspace for people exploring a
robot-skill economy without hardware. The interface should feel as clear as a
well-made instrument: direct controls, inspectable state, no speculative Web3
decoration, and no generic administration-dashboard scaffolding.

## Color

All authored colors use OKLCH.

- Background: `oklch(1 0 0)`
- Surface: `oklch(0.97 0.008 350)`
- Surface strong: `oklch(0.935 0.012 350)`
- Ink: `oklch(0.19 0.018 350)`
- Muted ink: `oklch(0.45 0.025 350)`
- Border: `oklch(0.87 0.014 350)`
- Primary: `oklch(0.58 0.19 350)`
- Primary hover: `oklch(0.52 0.20 350)`
- Accent: `oklch(0.35 0.10 195)`
- Success: `oklch(0.48 0.13 150)`
- Warning: `oklch(0.56 0.14 72)`
- Danger: `oklch(0.52 0.19 25)`

Primary color is reserved for selected state and decisive action. Accent teal
identifies verified, inspectable, or read-only chain state. Status never relies
on color alone.

## Typography

Manrope Variable carries UI copy at regular, semibold, and bold weights. IBM
Plex Mono carries addresses, hashes, chain IDs, primitive names, and aligned
numeric data. The fixed product scale is 0.75rem, 0.875rem, 1rem, 1.125rem,
1.5rem, and 2rem. Body text is never smaller than 1rem; compact metadata may use
0.75rem with strong contrast. Letter spacing is zero. Headings use balanced
wrapping and copy uses pretty wrapping.

## Layout

The spacing scale is 4, 8, 12, 16, 24, 32, 48, and 64px. Related controls use
8-12px gaps; distinct working regions use 24-32px. The desktop market is a
master-detail workspace, not a card grid. The simulator is full-width and
unframed inside its route. At 1024px the safety inspector moves below the main
workspace; below 720px all content becomes one column and navigation moves to a
bottom bar. Interactive targets are at least 44px in both dimensions.

## Components

Controls use 6-8px radii. Pills are reserved for status and segmented mode
selection. Panels use either a border or a small shadow, never both. Lists use
dividers and selected-row fills. Dialogs identify the exact network, contract,
method, amount, and consequence before any chain write. Unfamiliar icon buttons
have tooltips and accessible names.

## Motion

Micro-interactions run for 140-220ms with an ease-out-quart curve. Route content
does not depend on entrance animation for visibility. Simulation motion uses
position interpolation only; stopping is immediate between recipe steps. Under
`prefers-reduced-motion: reduce`, transforms and smooth scrolling are disabled
and state changes use an instant transition.

## Accessibility

Target WCAG 2.2 AA. Provide semantic landmarks, visible `:focus-visible`, full
keyboard operation, screen-reader labels, a logical focus order, reduced-motion
support, and text/icon reinforcement for every status. Chinese interface copy
must remain readable at browser zoom up to 200 percent without clipping.
