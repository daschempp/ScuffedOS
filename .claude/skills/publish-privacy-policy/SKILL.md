---
name: publish-privacy-policy
description: Use when the ScuffedOS canonical privacy policy (docs/privacy-policy.md) has changed and its two public copies are now stale and need syncing — the public GitHub gist and the scuffed-corporation website privacy page. Triggers: "publish/sync/mirror the privacy policy", "update the privacy gist", "privacy wave", a new connected-integration disclosure, or a bumped effective date that must go live.
---

# Publish Privacy Policy

## Overview

The canonical privacy policy is `docs/privacy-policy.md` (in the ScuffedOS repo). Two **public** copies must be kept byte-/content-identical to it:

1. **GitHub gist** — raw markdown, a direct copy of the canonical.
2. **Corp-site privacy page** — `scuffed-corporation/privacy/index.html`, a hand-authored HTML rendering.

This skill **propagates an already-edited canonical** to both. It does **not** author policy text — the canonical is edited as part of each feature's privacy work (a "wave"); this skill only publishes it.

Both targets are PUBLIC and outward-facing. **Show the diff and get the user's go-ahead before the gist PATCH and before the corp `git push`.**

## The one trap that wastes an hour

**`gh gist edit` (every form) exits 0 but SILENTLY does not change the gist content.** Never use it. Update the gist **only** via `gh api -X PATCH`.

## Targets (constants)

| Target | Location | How |
|---|---|---|
| Gist | id `439cee7cba3ac9077da6a5b81f83527c`, file `privacy-policy.md` (owner `daschempp`, desc "ScuffedOS Privacy Policy") | scripted (`gh api PATCH`) |
| Corp site | `/Users/dylanschempp/PycharmProjects/scuffed-corporation/privacy/index.html`, branch `main` (sibling of the ScuffedOS repo — adjust if moved) | hand-mirror |

Preconditions: `docs/privacy-policy.md` already reflects the intended changes; `gh` authenticated as `daschempp`; corp repo present and clean.

## Step 1 — Diff (know exactly what changed)

Run from the ScuffedOS repo root:

```bash
gh api /gists/439cee7cba3ac9077da6a5b81f83527c --jq '.files["privacy-policy.md"].content' \
  | diff - docs/privacy-policy.md
```

Read the diff — effective date, new/changed provider disclosures, new sections. **Summarize it to the user and confirm before publishing.**

## Step 2 — Gist (scripted, verify byte-identical)

`jq --rawfile` safely encodes the whole file as a JSON string (handles all escaping):

```bash
cd <ScuffedOS repo root>
jq -n --rawfile body docs/privacy-policy.md \
  '{files: {"privacy-policy.md": {content: $body}}}' > /tmp/gist-patch.json
gh api -X PATCH /gists/439cee7cba3ac9077da6a5b81f83527c --input /tmp/gist-patch.json \
  --jq '.html_url, .updated_at'
```

Verify:

```bash
gh api /gists/439cee7cba3ac9077da6a5b81f83527c --jq '.files["privacy-policy.md"].content' > /tmp/gist-after.md
diff docs/privacy-policy.md /tmp/gist-after.md   # empty = in sync
```

(A lone trailing-`\ No newline at end of file` note is benign — the stored content is exact.) The public raw URL (`https://gist.githubusercontent.com/daschempp/439cee7cba3ac9077da6a5b81f83527c/raw/privacy-policy.md`) is CDN-cached and may lag a few seconds.

## Step 3 — Corp site (hand-mirror — NOT auto-convert)

`privacy/index.html` is hand-authored semantic HTML with its own design system (numbered `<section class="sec">` blocks, `sec-label` spans, a `facts` provider `<table>`, `id` anchors, entity-encoded punctuation). **Do not regenerate it from the markdown.** Read the Step-1 diff and apply the *equivalent* edits to the matching HTML, preserving these anchor points:

- **TWO effective-date locations** — bump **both**: the intro `<p class="sec-label">…<span>effective july D, 2026</span></p>` **and** `<p><strong>Effective date:</strong> Month D, 2026</p>`.
- **§1 intro** — the connected-services list ("…WHOOP, Gmail, and Moodle") and the "Connected service data" paragraph + its trailing "See Section 4…" cross-references.
- **§3 provider `<table>`** — add a `<tr>` for a new provider, mirroring an existing row's markup, linking to `#<name>-data`.
- **§4 per-integration block** — add a `<section class="sec" aria-labelledby="<name>-data">` numbered with the next sub-letter (Gmail = `4a`, Moodle = `4b` → new = `4c`), with a `sec-label`, `<h2 id="<name>-data">`, and the canonical subsection's bullets as `<li>`s.
- **§6 retention** — add the clause if the canonical added one.
- **Entity-encode** punctuation to match the file: `&ldquo;`/`&rdquo;`/`&rsquo;`/`&mdash;`/`&amp;` — never raw quotes or dashes.

Commit **direct to `main`** (established convention — every prior privacy wave went straight to main, no PR). Message style: `privacy: wave N — <topic> (sync with app policy)`, where **N is the next number in the corp repo's own privacy history** (`git log --oneline -- privacy/index.html`) — this sequence is independent of the app's "Wave N".

```bash
cd /Users/dylanschempp/PycharmProjects/scuffed-corporation
git add privacy/index.html
git commit -m "privacy: wave N — <topic> (sync with app policy)"
git push origin main
```

## Verify & report

- Gist: Step-2 `diff` is empty; report the `html_url`.
- Corp: `git log -1` is pushed to `origin/main`; the new effective date + provider appear in `privacy/index.html`; report the commit. If the site is served via GitHub Pages, the change is live once Pages rebuilds.

## Common mistakes

| Mistake | Fix |
|---|---|
| `gh gist edit …` | Silent no-op (exits 0, no change). Use `gh api -X PATCH --input`. |
| Auto-converting the markdown into the corp HTML | It's hand-authored with its own conventions. Hand-mirror only the changed sections. |
| Bumping only one effective date | `index.html` has **two** (the `sec-label` span and the `<strong>Effective date:</strong>` line). |
| Raw quotes/dashes in the HTML | Entity-encode (`&ldquo;`/`&mdash;`/`&rsquo;`) to match the file. |
| Opening a PR for the corp change | Convention is a direct commit to `main`. |
| Reusing the app's "Wave N" in the corp commit | The corp repo has its **own** wave sequence — use the next number from its git log. |
| Publishing before showing the diff | Both copies are PUBLIC. Summarize the diff and confirm with the user first. |
