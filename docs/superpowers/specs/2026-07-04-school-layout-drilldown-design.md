# M6 School — layout redesign: course drill-down

**Status:** user-approved design (brainstormed 2026-07-04). Frontend-only refinement of the slice-1 School screen.
**Branch:** `m6-school-moodle-slice1` (adds to the open PR #4, pre-merge).
**Owner:** Dylan Schempp.
**Scope:** replaces the *connected main view* of `frontend/src/screens/SchoolScreen.jsx`. Connect / reconnect / syncing states and the read-only Moodle markers in Calendar/Tasks/Home are **unchanged**. No backend, API, schema, or migration changes.

## 1. Why

The current connected layout clones EmailScreen — a two-pane `kit-grid` with a left course list that only drives the Grades pane, and a right column stacking Deadlines → Grades → Announcements → Notifications. Verified against real WolfWare data, three problems:

- The left Courses column is nearly empty (4 courses in a tall pane) and feels disconnected from the right column, since selecting a course only changes Grades.
- Grades dumps every line item, so an ungraded course renders as a wall of "–".
- Deadlines — the highest-value info — are buried at the top of a scrolling column rather than being a headline.

## 2. New layout (course drill-down)

Top **course tabs** + a per-course **detail column** + a persistent **Upcoming rail**.

- **Course tabs** (horizontal, above the content): one chip per enrolled course (`shortname`), the selected one highlighted. The Sync button and the "synced · <time>" eyebrow sit at the right end of the tab row. Default selection on load = the **first** course.
- **Detail column** (main, wider) — everything for the *selected* course, in order:
  1. Course header: `shortname` + `fullname` + progress %.
  2. **Due in this course**: that course's upcoming deadlines (compact rows; overdue tinted).
  3. **Grade**: the course-total grade item (`item_type == "course"`) as a headline stat (e.g. "Course total · 91.2%"); if no course total or it's ungraded, show "Not yet graded" rather than a dash. Individual graded items list below (items with no grade still allowed but the total leads).
  4. **Announcements**: that course's announcements (subject · author · stripped summary).
- **Upcoming rail** (slim, right, always visible) — cross-course, so "what's due everywhere" is never lost:
  1. **Upcoming · all courses**: every upcoming deadline across all courses, soonest first, overdue tinted, each labeled with its course shortname + date. The selected course's items are visually emphasized (accent tint).
  2. **Notifications**: account-wide notifications (global, not per-course), compact, beneath Upcoming.

Empty states per region ("No courses yet — sync to pull your enrollment", "Nothing due in the next 60 days", "No announcements", etc.). On mobile widths the rail stacks below the detail (single column).

## 3. Data

Uses the existing five reads unchanged — `api.moodleCourses / moodleDeadlines / moodleGrades / moodleAnnouncements / moodleNotifications`. No new endpoints, no store/schema change. Derivations, all client-side:

- Per-course filtering: deadlines/grades/announcements filtered by `course_id === selectedCourse.source_id`.
- Course total: the grade row with `item_type === "course"` for the selected course; its `grade_formatted` is the headline; `graded_at`/`grade_raw` absence → "Not yet graded".
- Rail ordering: all deadlines sorted by due date ascending (the API already returns `due_at` asc); overdue flagged via the existing `overdue` field; each row shows `courseName(course_id)`.

## 4. Components / structure

Single file: `frontend/src/screens/SchoolScreen.jsx` — the `!syncing && !needsReauth` main-layout block (lines ~154–235 today) is rewritten; the connect-card, reauth, and syncing branches are kept verbatim. Reuse `ui.jsx` primitives (`Card`, `Button`, `Badge`) and design tokens. A small set of new `kit-*`/`sa-*` CSS rules (in `frontend/src/styles/kit.css`) for the tab row and the rail — no hardcoded colors, tokens only. The selected-course state replaces the current `selCourse` (already present, currently only used for grades — now drives the whole detail).

## 5. Testing / validation

- Frontend gate: `cd frontend && npm run build` clean (no frontend test harness).
- Browser-verify against the live-gate app (real WolfWare data already synced): tabs switch the detail; grades lead with the course total; the rail lists all deadlines with the selected course emphasized; announcements/notifications render as plain text; empty states behave; mobile width stacks the rail.

## 6. Out of scope

Backend/API/schema/migration changes; the connect/reauth/syncing states; Calendar/Tasks/Home markers; assignment submission and course-content browsing (slices 2/3). No new dependencies.
