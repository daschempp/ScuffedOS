# Scuffed OS — Design System

**Scuffed OS** is a warm, calm AI personal-assistant dashboard — a "second brain" that
organizes and optimizes your life. It ships as **two products from one design language**:
a **desktop app** (web dashboard) and an **iPhone app**. Both pair with a Telegram bot for
sending voice notes from anywhere, an AI memory database that learns from your data,
and four life trackers: **Calendar, Tasks, Finance, and Nutrition**.

The product feel is **calm & cozy** — journal-like and human, never clinical. Warm
"paper" surfaces, a single deep-forest-green accent, soft floaty cards, and hand-drawn
doodle accents.

> **Sources.** This is a greenfield brand. There was no existing codebase or Figma
> file — the entire visual language was designed from a brief (warm + lighter palette,
> green accent, calm/cozy, neutral grotesk type, 16px radius, floaty shadows). If a
> real product codebase or Figma later exists, link it here so the system can be
> reconciled against it.

---

## Content fundamentals

How Scuffed OS talks. The assistant is a quietly competent companion, not a hype bot.

- **Voice.** Warm, plain, and concise. Speaks *to* the user ("you", "your day"),
  refers to the assistant in first person when it acts ("I'll set a reminder",
  "I noticed…"). Calm and supportive, never bossy or salesy.
- **Casing.** Sentence case everywhere — headings, buttons, nav. The only all-caps is
  the small letter-spaced **eyebrow/overline** label (`TUESDAY · JUNE 8`, `142 STORED`).
- **Tone examples.**
  - Greeting: *"Good morning, Sam"* · *"Here's your day at a glance"*
  - Nudge: *"You've skipped logging lunch twice this week. Want me to set a gentle 1pm reminder?"*
  - Reassurance: *"You're $120 under your dining budget. Roll it into savings?"*
  - Empty/placeholder: *"Ask anything — 'what did I say about the Lighthouse deadline?'"*
- **Numbers & data** are set in the mono face (Spline Sans Mono): amounts, macros,
  timestamps, counts. This keeps figures tidy and scannable. Currency keeps cents in a
  fainter color (`$4,820`**`.50`**).
- **Emoji:** none. Warmth comes from type, color, doodles, and copy — not emoji.
- **Buttons** are verbs: *Add task*, *Log meal*, *Add a cup*, *Voice note*, *Ask*.
- **Microcopy vibe:** gentle accountability. Suggests, then offers to act
  ("Yes, do it" / "Not now"). Short. Human. A little encouraging.

---

## Visual foundations

**Color.** A warm paper canvas (`--paper-100` `#FAF6EF`) carries raised white cards.
Text is **warm ink**, not pure black (`--ink-900` `#2A2620`). The single brand accent is
**deep forest green** (`--green-600` `#3A6B4E`) used for primary actions, active nav,
rings and positive figures. A small family of warm category hues — **clay** (spend/danger),
**honey** (goals/warning), **sky** (water/sleep/info), **plum** (notes) — tags finance and
nutrition data. Each status/category has a solid + a soft tint. No blue-purple gradients.

**Type.** Three families: **Schibsted Grotesk** (display/headings, tight tracking, 700–800),
**Hanken Grotesk** (UI + body, 400–600), **Spline Sans Mono** (numbers, amounts, timestamps).
Headings are confident and tight; body is calm and legible at 15px.

**Spacing & layout.** 4px base grid. Generous but balanced density. Fixed 248px sidebar
(forest green), scrolling main column, sticky translucent top bar with a fading paper
gradient. Content sits on a 24px gutter grid.

**Backgrounds.** Solid warm paper — never photos behind content. Surfaces stay clean and
flat. Optional **hand-drawn doodle** accents (underline,
squiggle, circle, arrow, sparkle) for emphasis — used sparingly.

**Corners & cards.** Soft, rounded. Default card radius **16px** (`--radius-lg`); inputs
10px; pills 999px. Cards are **floaty**: white surface, **soft warm-tinted shadow**
(`--shadow-md`), **no border**. Sunken cards use the paper-200 fill with no shadow. Hairline
borders (`--border-hairline`) appear only as list-row dividers and input outlines.

**Shadows.** Warm-tinted and diffuse (brown-grey, never pure black). A 5-step elevation
ramp plus a green-tinted `--shadow-accent` glow under primary buttons and an inset shadow
for sunken tracks/inputs.

**Motion.** Gentle and quiet. Fades + soft eases (`--ease-out`), a whisper of overshoot on
toggles/checks (`--ease-soft`) — never bouncy. Durations 120/200/320ms. The only looping
animation is the live voice-note waveform while recording. Respect reduced-motion.

**States.**
- *Hover:* primary darkens (600→700); secondary warms its fill + border; ghost picks up a
  sunken tint; cards marked `interactive` lift 2px with a larger shadow.
- *Press:* buttons nudge down + scale to 0.985; icon buttons scale to 0.92.
- *Focus:* 3px soft green focus ring (`--focus-ring`), no hard outline.
- *Active nav:* solid green pill with white text + soft shadow.

**Transparency & blur.** Used lightly: the sticky top bar fades the paper to transparent;
sidebar active/hover states use low-opacity white overlays on the green. No heavy glass/blur.

**Imagery vibe.** Warm, soft, low-contrast if photos are ever added. Avatars fall back to
initials on a warm tint. (No stock photography ships with this system — see Caveats.)

---

## Iconography

- **System:** [Lucide](https://lucide.dev) — clean 2px-stroke, rounded-cap line icons.
  Their friendly-but-tidy line style matches the calm-grotesk personality perfectly.
- **Delivery:** loaded from CDN (`unpkg.com/lucide@0.460.0`). In React surfaces, icons are
  rendered **into a React-owned `<span>` via `lucide.createElement`** (see
  `ui_kits/scuffed-os/ui.jsx` → `Icon`) rather than `createIcons()` DOM replacement — this
  avoids React reconciliation fighting lucide's DOM mutation. In static `@dsCard` demos,
  plain `<i data-lucide>` + `lucide.createIcons()` is fine.
- **Common glyphs:** `mic`, `audio-lines`, `brain`, `sparkles`, `lightbulb`,
  `layout-dashboard`, `calendar`, `circle-check-big`, `wallet`, `apple`, `utensils`,
  `search`, `bell`, `settings`, `arrow-up-right`, `check-check`, `trending-up`.
- **Brand marks (SVG, in `assets/`):** the sprout **logomark** (`logo-mark.svg`,
  `logo-mark-mono.svg`) and the **doodle accents** (`assets/doodles/`: underline, squiggle,
  circle, arrow, sparkle). These are real brand SVGs — copy them in, don't redraw.
- **No emoji, no unicode icon characters.** Numbers/symbols come from the mono font.

---

## Index / manifest

**Root**
- `styles.css` — the entry point consumers link. `@import` manifest only.
- `readme.md` — this guide.
- `SKILL.md` — Agent-Skills wrapper for use in Claude Code.

**`tokens/`** (all reachable from `styles.css`)
- `fonts.css` · `colors.css` · `typography.css` · `spacing.css` · `radius.css`
  · `shadows.css` · `motion.css`

**`assets/`**
- `logo-mark.svg`, `logo-mark-mono.svg` — sprout logomark (on-green / standalone)
- `doodles/` — `underline.svg`, `squiggle.svg`, `circle.svg`, `arrow.svg`, `sparkle.svg`

**`components/`** (React primitives — `window.ScuffedOSDesignSystem_c8c4c3.<Name>`)
- `buttons/` — **Button**, **IconButton**
- `forms/` — **Input**, **Switch**, **Checkbox**
- `display/` — **Card**, **Badge**, **Avatar**, **Stat**, **ProgressBar**, **ProgressRing**

**`ui_kits/scuffed-os/`** — interactive **desktop** dashboard recreation
- `index.html` (start here) · `app.jsx` · `ui.jsx` (kit primitives) · `Sidebar.jsx`
  · `TopBar.jsx` · `DashboardScreen.jsx` · `CalendarScreen.jsx` · `TasksScreen.jsx`
  · `TaskDetail.jsx` · `NutritionScreen.jsx` · `FinanceScreen.jsx` · `MemoryScreen.jsx`
  · `ChatPanel.jsx` (AI assistant) · `assistant-logic.js` (shared intent engine) · `kit.css`

**`ui_kits/scuffed-os-ios/`** — interactive **iPhone** app recreation
- `index.html` (start here) · `mobileapp.jsx` (shell + bottom tab bar) · `screens.jsx`
  (Home / Tasks / Money / Food) · `MobileAssistant.jsx` (full-screen chat)
  · `VoiceSheet.jsx` (voice capture) · `ios-frame.jsx` (device bezel) · `mobile.css`.
  Reuses the same tokens, `ui.jsx` primitives, and `assistant-logic.js` as desktop.

**`guidelines/`** — foundation specimen cards (the Design System tab):
Colors (green, neutrals, status, categories), Type (display, body, mono, weights),
Spacing (scale, radius, shadows), Brand (logo, doodles).

---

## Using the system

- **Global CSS:** link `styles.css`, then use the semantic tokens (`--surface-raised`,
  `--text-strong`, `--accent`, `--radius-lg`, `--shadow-md`, …).
- **Components:** in `@dsCard` HTML, load `_ds_bundle.js` (auto-generated) and read
  `const { Button, Card } = window.ScuffedOSDesignSystem_c8c4c3`.
- **Throwaway artifacts (slides, mocks):** copy `assets/` + the tokens you need and build
  static HTML with the kit's CSS approach (see `ui_kits/scuffed-os/kit.css`).

## Caveats
- **Fonts** load from the Google Fonts CDN, not self-hosted binaries. Send `.woff2` files
  to vendor them locally.
- **No photography** ships with the system. Avatars use initials; surfaces use solid warm
  paper. Add real imagery (warm, soft, low-contrast) if a product needs it.
- The **logomark and doodles** are original starter marks — happy to refine or replace
  with a designed identity.
