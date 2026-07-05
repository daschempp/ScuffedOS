"""Pydantic request/response models for the Scuffed OS API.

Vocabulary fields (group, prio) are Literal-constrained (review R8) so clients
and the assistant's tools can't invent values. Display strings (`due`, `late`,
`when`) are derived server-side from stored facts and are read-only.
"""
from __future__ import annotations

from datetime import date, datetime
# Two Python 3.14 deferred-annotation quirks: a field literally named `list`
# (the prototype's API contract) shadows the builtin when sibling `list[...]`
# annotations are evaluated — so task models use typing.List. Likewise the
# nutrition/habit models have a field named `date`, which shadows the date
# *type* inside their own class — those annotate with the `Day` alias.
from datetime import date as Day
from typing import Annotated, List, Literal

from pydantic import BaseModel, Field

Weekday = Annotated[int, Field(ge=0, le=6)]  # Mon=0 … Sun=6

TaskGroup = Literal["Today", "Upcoming", "Someday", "School"]  # "School" = read-time Moodle-assignment projection (M6)
TaskPriority = Literal["low", "med", "high"]
# The design palette — event colors, habit tints, meal chips all draw from it.
Tint = Literal["green", "sky", "plum", "honey", "clay", "grape"]  # "grape" = read-time Moodle-deadline projection (M6)
MealSlot = Literal["Breakfast", "Lunch", "Snack", "Dinner"]
HabitLink = Literal["water", "workout"]


# ---- Assistant ------------------------------------------------------------
# The deep-link vocabulary (review R8) — every screen the sidebar knows.
Screen = Literal["home", "tasks", "calendar", "habits", "nutrition", "fitness",
                 "finance", "people", "email", "memory", "settings"]


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    conversation_id: int | None = None


class ChatAction(BaseModel):
    """A receipt for a tool the assistant actually executed, with a deep link."""

    icon: str
    title: str
    meta: str
    cta: str
    screen: Screen


class ChatResponse(BaseModel):
    conversation_id: int
    text: str  # plain text — never HTML (review R4)
    actions: List[ChatAction] = []


class ConversationMessageOut(BaseModel):
    id: int
    role: Literal["user", "assistant"]
    content: str
    actions: List[ChatAction] | None = None
    created_at: datetime


class ConversationOut(BaseModel):
    id: int
    title: str | None
    messages: List[ConversationMessageOut]


# ---- Tasks ----------------------------------------------------------------
class Subtask(BaseModel):
    id: int | float  # client-generated (Date.now())
    label: str
    done: bool = False


class TaskFile(BaseModel):
    """File metadata; the bytes live on disk under settings.attachments_dir.

    Server-issued ids are uuid hex strings (M3 uploads); older client-generated
    Date.now() ids are still tolerated on rows that predate real uploads.
    """

    id: int | float | str
    name: str
    size: int | None = None


class TaskReminderOut(BaseModel):
    """A reminder that fires (M3). `display` is the chip text."""

    id: int
    remind_at: datetime
    label: str
    fired_at: datetime | None
    display: str


class TaskReminderCreate(BaseModel):
    remind_at: datetime
    label: str = ""


class Task(BaseModel):
    id: int | str  # int for local rows; "moodle:<source_id>" for read-time Moodle projections (M6)
    label: str
    done: bool
    group: TaskGroup
    deadline: date | None
    prio: TaskPriority
    list: str
    description: str
    subtasks: List[Subtask]
    labels: List[str]
    reminders: List[TaskReminderOut]
    files: List[TaskFile]
    recurrence: str | None
    recurrence_label: str | None  # derived: "Repeats weekly" / None
    # Derived display facts (review R6) — computed from deadline/done on read.
    due: str | None
    late: bool
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    # Read-time origin markers (M6). Real rows default to local/editable so
    # existing serializers that omit these keys validate unchanged; Moodle
    # projections set source="moodle"/editable=False (read-only in the UI).
    source: str = "local"
    editable: bool = True


class TaskCreate(BaseModel):
    label: str = Field(min_length=1)
    done: bool = False
    group: TaskGroup = "Today"
    deadline: date | None = None
    prio: TaskPriority = "med"
    list: str = "Personal"
    description: str = ""
    subtasks: List[Subtask] = []
    labels: List[str] = []
    files: List[TaskFile] = []
    recurrence: str | None = None


class TaskUpdate(BaseModel):
    """Partial update. Only keys the client sends are applied; an explicit
    null clears `deadline`/`recurrence` and is ignored for non-nullable
    fields (R7)."""

    label: str | None = Field(default=None, min_length=1)
    done: bool | None = None
    group: TaskGroup | None = None
    deadline: date | None = None
    prio: TaskPriority | None = None
    list: str | None = None
    description: str | None = None
    subtasks: List[Subtask] | None = None
    labels: List[str] | None = None
    files: List[TaskFile] | None = None
    recurrence: str | None = None


# ---- Memory (second brain) ------------------------------------------------
class Memory(BaseModel):
    id: int
    text: str
    src: str
    tags: list[str]
    color: str
    when: str  # derived relative time ("2 days ago")
    created_at: datetime
    updated_at: datetime


class MemoryCreate(BaseModel):
    text: str = Field(min_length=1)
    src: str = "note"
    tags: list[str] = []
    color: str = "green"


class MemoryUpdate(BaseModel):
    text: str | None = Field(default=None, min_length=1)
    src: str | None = None
    tags: list[str] | None = None
    color: str | None = None


# ---- Calendar ---------------------------------------------------------------
class EventOccurrence(BaseModel):
    """One concrete occurrence — what GET /events returns. For a recurring
    series, `id` is the series row and `start`/`end` are this instance's
    times; single-occurrence deletes key on `start`."""

    id: int | str  # int for local rows; "moodle:<source_id>" for read-time Moodle projections (M6)
    title: str
    start: datetime
    end: datetime
    tint: Tint
    location: str
    description: str
    recurring: bool
    recurrence_label: str | None
    at: str  # derived display clock, e.g. "9:00am"
    # Read-time origin markers (M6). Real rows default to local/editable so
    # existing serializers that omit these keys validate unchanged; Moodle
    # projections set source="moodle"/editable=False (read-only in the UI).
    source: str = "local"
    editable: bool = True


class EventCreate(BaseModel):
    title: str = Field(min_length=1)
    start: datetime
    end: datetime | None = None  # defaults to start + 1h
    tint: Tint = "sky"
    location: str = ""
    description: str = ""
    recurrence: str | None = None


class EventUpdate(BaseModel):
    """Partial update; edits apply to the whole series for recurring events
    (delete a single occurrence via DELETE ?occurrence_start=)."""

    title: str | None = Field(default=None, min_length=1)
    start: datetime | None = None
    end: datetime | None = None
    tint: Tint | None = None
    location: str | None = None
    description: str | None = None
    recurrence: str | None = None


class UpNextItem(BaseModel):
    id: int
    title: str
    when: str  # derived: "Now · 9:00am–10:30am" / "Tomorrow 4:00pm · Oak Street"
    tint: Tint
    start: datetime


# ---- Habits -----------------------------------------------------------------
class HabitOut(BaseModel):
    id: int
    name: str
    icon: str
    tint: Tint
    schedule: list[int]  # weekday ints, Mon=0
    link: HabitLink | None
    streak: int  # derived from the completion log
    best_streak: int
    days: list[bool]  # the requested week's completion grid, Mon-first


class HabitsWeek(BaseModel):
    week_start: date  # Monday
    today_index: int | None  # 0-6 within this week, None if another week
    habits: List[HabitOut]
    done_today: int
    week_pct: int  # completions / scheduled slots elapsed this week
    prev_week_pct: int


class HabitCreate(BaseModel):
    name: str = Field(min_length=1)
    icon: str = "check"
    tint: Tint = "green"
    schedule: list[Weekday] = [0, 1, 2, 3, 4, 5, 6]
    link: HabitLink | None = None


class HabitUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    icon: str | None = None
    tint: Tint | None = None
    schedule: list[Weekday] | None = None
    link: HabitLink | None = None


class HabitToggle(BaseModel):
    date: Day | None = None  # defaults to today


# ---- Nutrition --------------------------------------------------------------
class MealOut(BaseModel):
    id: int
    date: Day
    slot: MealSlot
    name: str
    kcal: int
    protein_g: float
    carbs_g: float
    fat_g: float
    time: str  # derived: "Breakfast · 8:10am"
    icon: str  # derived from slot (egg/sandwich/apple/utensils)
    tint: Tint
    logged_at: datetime


class MealCreate(BaseModel):
    name: str = Field(min_length=1)
    slot: MealSlot = "Snack"
    kcal: int = Field(default=0, ge=0)
    protein_g: float = Field(default=0, ge=0)
    carbs_g: float = Field(default=0, ge=0)
    fat_g: float = Field(default=0, ge=0)
    date: Day | None = None  # defaults to today
    logged_at: datetime | None = None


class MealUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    slot: MealSlot | None = None
    kcal: int | None = Field(default=None, ge=0)
    protein_g: float | None = Field(default=None, ge=0)
    carbs_g: float | None = Field(default=None, ge=0)
    fat_g: float | None = Field(default=None, ge=0)


class NutritionTargetsOut(BaseModel):
    calories: int
    protein_g: int
    carbs_g: int
    fat_g: int
    water_cups: int


class NutritionTargetsUpdate(BaseModel):
    calories: int | None = Field(default=None, gt=0)
    protein_g: int | None = Field(default=None, gt=0)
    carbs_g: int | None = Field(default=None, gt=0)
    fat_g: int | None = Field(default=None, gt=0)
    water_cups: int | None = Field(default=None, gt=0)


class WaterOut(BaseModel):
    date: Day
    cups: int
    goal: int


class WaterUpdate(BaseModel):
    """Increment by `delta` cups (default +1) or set `cups` outright."""

    delta: int | None = None
    cups: int | None = Field(default=None, ge=0)
    date: Day | None = None


class NutritionDay(BaseModel):
    date: Day
    meals: List[MealOut]
    totals: dict  # {kcal, protein_g, carbs_g, fat_g} summed on read
    targets: NutritionTargetsOut
    water: WaterOut


class NutritionWeekDay(BaseModel):
    date: Day
    dow: str  # "M" / "T" / ... Mon-first
    kcal: int
    frac: float  # kcal / target, capped at 1.0 for the bar chart


class NutritionWeek(BaseModel):
    days: List[NutritionWeekDay]
    avg_kcal: int
    days_met: int  # days within the kcal goal (of days with any logging)
    goal: int


class FoodHit(BaseModel):
    """A food-database match (USDA FoodData Central), per ~serving."""

    fdc_id: int
    description: str
    brand: str | None = None
    serving: str
    kcal: int
    protein_g: float
    carbs_g: float
    fat_g: float


# ---- Fitness OAuth schemas (M4) — defined at the head of the OAuth phase ----
# (Task 19; the read/write schemas land in Task 23, which skips these three.)
class ProviderStatus(BaseModel):
    provider: str
    status: Literal["connected", "needs_reauth"]
    connected_at: datetime
    last_sync_at: datetime | None
    provider_user_id: str | None = None
    can_write_email: bool = False


class FitnessStatus(BaseModel):
    connected: bool  # any provider connected
    providers: List[ProviderStatus]


# M5: generic OAuth status returned by the shared /api/oauth/status endpoint.
# Structurally identical to FitnessStatus (domain-agnostic) so the moved M4
# status test passes unchanged. FitnessStatus stays for the assistant tool shape.
class OAuthStatus(BaseModel):
    connected: bool  # any provider connected
    providers: List[ProviderStatus]


class ConnectUrl(BaseModel):
    authorize_url: str


# ---- Fitness read/write schemas (M4) ----------------------------------------
# ProviderStatus / FitnessStatus / ConnectUrl already defined in Task 19.
FitnessSource = Literal["whoop", "oura", "apple_health", "manual"]


class FitnessVital(BaseModel):
    key: str  # 'hrv' | 'resting_hr' | 'respiratory_rate' | 'sleep_hours'
    label: str
    value: float | None
    unit: str
    delta: float | None  # vs prior day; None if no prior
    icon: str
    tint: Tint


class FitnessToday(BaseModel):
    date: Day
    source: str | None  # which provider produced today's snapshot; None if no data
    recovery_pct: int | None
    day_strain: float | None
    sleep_quality_pct: int | None
    vitals: List[FitnessVital]
    has_data: bool


class WorkoutOut(BaseModel):
    id: int
    source: FitnessSource
    source_id: str | None
    name: str
    sport: str | None
    started_at: datetime
    duration_min: int
    strain: float | None
    calories: int | None
    avg_hr: int | None
    max_hr: int | None
    when: str  # derived display, e.g. "Today · 6:10am" (mirrors event_when style)
    icon: str  # derived from sport
    tint: Tint  # derived from sport


class WorkoutCreate(BaseModel):
    name: str = Field(min_length=1)
    sport: str | None = None
    started_at: datetime
    duration_min: int = Field(ge=0)
    strain: float | None = Field(default=None, ge=0)
    calories: int | None = Field(default=None, ge=0)
    avg_hr: int | None = Field(default=None, ge=0)
    max_hr: int | None = Field(default=None, ge=0)


class FitnessWeekDay(BaseModel):
    date: Day
    dow: str  # "M" / "T" / ... Mon-first
    strain: float | None
    frac: float  # day_strain / 21, capped at 1.0


class FitnessWeek(BaseModel):
    days: List[FitnessWeekDay]
    avg_strain: float
    peak_day: Day | None


# ---- Email schemas (M5) -----------------------------------------------------
# EmailOut is the inbox list item and carries NO body (privacy: bodies are
# never persisted and never travel in the list). EmailDetail adds the live,
# on-demand body fetched from Gmail in the reading pane.
# (OAuthStatus lives above, added by the Phase-1 spine / Task 4 — not re-added
# here.)
EmailCategory = Literal["needs_reply", "fyi"]


class EmailOut(BaseModel):
    id: int
    source: str
    from_name: str
    from_email: str
    subject: str
    snippet: str
    received_at: datetime
    unread: bool
    starred: bool = False
    label_ids: List[str] = []
    category: EmailCategory | None  # None = untriaged (retry next sync)
    summary: List[str]              # [] when untriaged
    when: str                       # derived display, e.g. "8:24am" / "Yesterday"


class EmailDetail(EmailOut):
    thread_id: str
    body: str  # on-demand Gmail fetch (or a graceful fallback string)


class FlagsPatch(BaseModel):
    """None field = unchanged. unread=True adds Gmail's UNREAD label (marks
    unread); unread=False removes it (marks read). starred=True adds
    STARRED; starred=False removes it. See routers/email.py's add/remove
    computation."""

    unread: bool | None = None
    starred: bool | None = None


class LabelsPatch(BaseModel):
    add: List[str] = []
    remove: List[str] = []


class LabelOut(BaseModel):
    id: str
    name: str
    type: str


class SendEmail(BaseModel):
    to: str
    cc: str | None = None
    subject: str
    body: str


class ReplyEmail(BaseModel):
    body: str


class ForwardEmail(BaseModel):
    to: str
    body: str


class Inbox(BaseModel):
    needs_reply: List[EmailOut]
    fyi: List[EmailOut]
    untriaged: List[EmailOut]
    needs_reply_count: int
    unread_count: int


class DraftRequest(BaseModel):
    instructions: str
    notes: str = ""
    mode: Literal["new", "reply", "forward"] = "new"
    email_id: int | None = None


# ---- Moodle schemas (M6 School) ----------------------------------------------
# Read models for the /api/moodle/* GET endpoints. Every field is served from
# the moodle_* tables (never a live Moodle call). Tokens/scopes are NEVER in
# any of these shapes — connection state travels via /api/oauth/status only.
class CourseOut(BaseModel):
    id: int
    source_id: str
    shortname: str
    fullname: str
    progress: float | None
    start_at: datetime | None
    end_at: datetime | None
    last_access_at: datetime | None
    hidden: bool


class DeadlineOut(BaseModel):
    id: int
    source_id: str
    course_id: str
    name: str
    module_name: str
    event_type: str
    due_at: datetime
    overdue: bool
    url: str
    when: str  # derived display, e.g. "Fri 3:00pm" / "Tomorrow"


class GradeOut(BaseModel):
    id: int
    source_id: str
    course_id: str
    item_name: str
    item_type: str
    grade_formatted: str
    grade_raw: float | None
    grade_min: float | None
    grade_max: float | None
    graded_at: datetime | None


class AnnouncementOut(BaseModel):
    id: int
    source_id: str
    course_id: str
    forum_id: str
    subject: str
    author: str
    created_at: datetime | None
    summary_html: str
    url: str


class NotificationOut(BaseModel):
    id: int
    source_id: str
    subject: str
    full_message: str
    context_url: str
    created_at: datetime | None
    read: bool


# POST /api/moodle/connect body — the pasted wstoken (bare 32-hex or a
# launch-redirect URL) plus the optional passport used to verify the launch
# redirect's md5 prefix (see parse_pasted_token, contract §D).
class MoodleConnect(BaseModel):
    token: str
    passport: str | None = None
