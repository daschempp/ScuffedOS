---
name: scuffed-os-design
description: Use this skill to generate well-branded interfaces and assets for Scuffed OS, either for production or throwaway prototypes/mocks/etc. Contains essential design guidelines, colors, type, fonts, assets, and UI kit components for prototyping.
user-invocable: true
---

Read the `readme.md` file within this skill, and explore the other available files.

Scuffed OS is a warm, calm AI personal-assistant dashboard (a "second brain" with
Calendar, Tasks, Finance and Nutrition trackers, plus a Telegram voice-note inbox).
The aesthetic is journal-like and cozy: warm paper surfaces, one deep-forest-green
accent, floaty borderless cards, soft warm shadows, neutral grotesk type, and occasional
hand-drawn doodle accents. No emoji.

Key files:
- `styles.css` — link this; use the semantic CSS custom properties (`--surface-raised`,
  `--text-strong`, `--accent`, `--radius-lg`, `--shadow-md`, etc.).
- `tokens/` — colors, typography, spacing, radius, shadows, motion.
- `assets/` — sprout logomark + doodle SVGs (copy these in; don't redraw).
- `components/` — React primitives (Button, IconButton, Input, Switch, Checkbox, Card,
  Badge, Avatar, Stat, ProgressBar, ProgressRing).
- `ui_kits/scuffed-os/` — a full interactive dashboard recreation to learn the patterns
  (sidebar, top bar, the four trackers, the second-brain/voice-note views). `kit.css`
  shows the component CSS and screen layouts; `ui.jsx` shows React-safe Lucide icons.

If creating visual artifacts (slides, mocks, throwaway prototypes, etc), copy assets out
and create static HTML files for the user to view. If working on production code, you can
copy assets and read the rules here to become an expert in designing with this brand.

If the user invokes this skill without any other guidance, ask them what they want to
build or design, ask some questions, and act as an expert designer who outputs HTML
artifacts _or_ production code, depending on the need.
