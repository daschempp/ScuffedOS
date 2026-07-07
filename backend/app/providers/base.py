"""Vendor-neutral provider seam: normalized dataclasses + Protocols + AuthError.

M5 split the single FitnessProvider Protocol into a shared OAuthProvider base
(the connect/callback/disconnect plumbing the shared router drives) plus two
domain protocols: FitnessProvider (WHOOP-style pull data) and EmailProvider
(Gmail-style message reads). No provider field names leak past the provider
module — every provider maps its payloads into these dataclasses. ``AuthError``
is the typed auth/refresh failure the sync engines catch to flip a provider to
``needs_reauth`` (the real providers raise WhoopAuthError / GoogleAuthError).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Protocol, runtime_checkable


class AuthError(Exception):
    """Auth/refresh failure raised by a provider. The sync engines catch
    ``except AuthError`` and flip the provider to ``status='needs_reauth'``.
    The real providers' WhoopAuthError / GoogleAuthError subclass this."""


@dataclass
class Tokens:
    access_token: str
    refresh_token: str | None
    expires_at: datetime | None          # aware UTC
    scopes: str = ""                      # space-delimited, as granted
    provider_user_id: str | None = None
    meta: dict = field(default_factory=dict)


@dataclass
class NormalizedSnapshot:
    source: str                          # 'whoop'
    day: date
    recovery_pct: int | None = None
    day_strain: float | None = None
    sleep_quality_pct: int | None = None
    hrv_ms: float | None = None
    resting_hr: int | None = None
    respiratory_rate: float | None = None
    sleep_hours: float | None = None
    metrics_json: dict = field(default_factory=dict)


@dataclass
class NormalizedWorkout:
    source: str                          # 'whoop'
    source_id: str | None
    name: str
    sport: str | None
    started_at: datetime                 # aware UTC
    duration_min: int
    strain: float | None = None
    calories: int | None = None          # kcal (already kJ->kcal converted)
    avg_hr: int | None = None
    max_hr: int | None = None


@dataclass
class NormalizedEmail:
    source: str                          # 'google'
    source_id: str                       # gmail message id
    thread_id: str
    from_name: str
    from_email: str
    subject: str
    snippet: str                         # gmail preview
    received_at: datetime                # aware UTC, sort key
    unread: bool = False
    body_excerpt: str = ""               # bounded ~2 KB plain-text, triage-only, NOT persisted
    starred: bool = False                # 'STARRED' in Gmail labelIds
    label_ids: list = field(default_factory=list)   # Gmail labelIds, sync-authoritative


@dataclass
class NormalizedCourse:
    source: str                          # 'moodle'
    source_id: str                       # course id
    shortname: str
    fullname: str
    progress: float | None = None        # 0..100 or None
    start_at: datetime | None = None
    end_at: datetime | None = None
    last_access_at: datetime | None = None
    hidden: bool = False


@dataclass
class NormalizedDeadline:                # the Timeline (core_calendar_get_action_events_by_timesort)
    source: str
    source_id: str                       # calendar event id
    course_id: str
    name: str                            # e.g. "Summative assignment is due"
    module_name: str                     # 'assign' | 'quiz' | 'lesson' | ...
    event_type: str                      # 'due' | 'close' | ...
    due_at: datetime                     # from timesort (epoch -> aware UTC)
    overdue: bool = False
    url: str = ""                        # viewurl


@dataclass
class NormalizedAssignment:
    source: str
    source_id: str                       # assign id
    course_id: str
    cmid: str
    name: str
    due_at: datetime | None = None
    cutoff_at: datetime | None = None
    grade_max: float | None = None
    submission_status: str = "none"      # 'new'|'draft'|'submitted'|'reopened'|'none'
    grading_status: str = ""             # 'graded'|'notgraded'|...
    graded: bool = False


@dataclass
class NormalizedGrade:
    source: str
    source_id: str                       # grade item id
    course_id: str
    item_name: str
    item_type: str                       # 'mod'|'course'|'category'
    grade_formatted: str = "-"           # display string (may contain HTML entities)
    grade_raw: float | None = None
    grade_min: float | None = None
    grade_max: float | None = None
    graded_at: datetime | None = None


@dataclass
class NormalizedAnnouncement:
    source: str
    source_id: str                       # discussion id
    course_id: str
    forum_id: str
    subject: str
    author: str
    created_at: datetime
    summary_html: str = ""               # short; stripped for display
    url: str = ""


@dataclass
class NormalizedNotification:
    source: str
    source_id: str                       # notification id
    subject: str
    full_message: str = ""               # stripped for display
    context_url: str = ""
    created_at: datetime | None = None
    read: bool = False


@dataclass
class MoodleSnapshot:                    # the bundle fetch_school_snapshot returns
    courses: list[NormalizedCourse] = field(default_factory=list)
    deadlines: list[NormalizedDeadline] = field(default_factory=list)
    assignments: list[NormalizedAssignment] = field(default_factory=list)
    grades: list[NormalizedGrade] = field(default_factory=list)
    announcements: list[NormalizedAnnouncement] = field(default_factory=list)
    notifications: list[NormalizedNotification] = field(default_factory=list)


@runtime_checkable
class OAuthProvider(Protocol):
    """The connect/callback/disconnect plumbing the shared oauth router drives.
    Both FitnessProvider and EmailProvider extend it."""
    name: str                            # 'whoop' | 'google'

    def authorize_url(self, state: str) -> str: ...
    def exchange_code(self, code: str) -> Tokens: ...
    def refresh(self, tokens: Tokens) -> Tokens: ...
    def revoke(self, tokens: Tokens) -> None: ...
    def set_tokens(self, tokens: Tokens | None) -> None: ...
    def success_redirect(self) -> str: ...      # screen to land on after connect
    def on_connected(self) -> None: ...          # post-connect hook (kick a sync)
    def on_disconnect(self) -> None: ...         # delete this provider's domain data


@runtime_checkable
class FitnessProvider(OAuthProvider, Protocol):
    kind: Literal["pull", "push"]        # whoop/oura='pull'; apple_health='push'

    def fetch_recovery(self, since: datetime | None) -> list[NormalizedSnapshot]: ...
    def fetch_sleep(self, since: datetime | None) -> list[NormalizedSnapshot]: ...
    def fetch_workouts(self, since: datetime | None) -> list[NormalizedWorkout]: ...


@runtime_checkable
class EmailProvider(OAuthProvider, Protocol):
    # The sync drives list + gated per-id get so it can skip messages.get for
    # already-triaged ids; fetch_messages stays as a batch convenience.
    def list_message_ids(self, since: datetime | None) -> list[str]: ...
    def fetch_message(self, source_id: str) -> NormalizedEmail: ...
    def fetch_messages(self, since: datetime | None) -> list[NormalizedEmail]: ...
    def get_message(self, source_id: str) -> str: ...   # full plain-text body, on demand
    def send_message(self, raw_rfc822: bytes, thread_id: str | None = None) -> str: ...
    def trash_message(self, source_id: str) -> None: ...
    def modify_labels(self, source_id: str, add: list[str] = (), remove: list[str] = ()) -> None: ...
    def list_labels(self) -> list[dict]: ...
    def get_message_meta(self, source_id: str) -> dict: ...


@runtime_checkable
class MoodleProvider(OAuthProvider, Protocol):
    """Read-only Moodle web-services adapter. Distinguishing method
    fetch_school_snapshot — moodle_sync selects providers by hasattr on it
    (mirrors email_sync's hasattr(p,'fetch_messages'))."""
    def get_site_info(self, token: str) -> dict: ...                 # connect-time validation
    def fetch_school_snapshot(self, since: datetime | None) -> MoodleSnapshot: ...


# ---- Finance / Plaid (M7) ------------------------------------------------
@dataclass
class NormalizedItem:
    item_id: str                          # Plaid item_id
    institution_id: str
    institution_name: str
    products: list[str] = field(default_factory=list)   # ['transactions'] / ['investments']


@dataclass
class NormalizedAccount:
    source: str                           # 'plaid'
    source_id: str                        # Plaid account_id
    item_id: str
    name: str
    official_name: str | None
    mask: str | None
    type: str                             # depository | investment | credit | loan
    subtype: str | None                   # checking | savings | ira | 401k | brokerage | ...
    current_balance: Decimal | None = None
    available_balance: Decimal | None = None
    iso_currency: str = "USD"


@dataclass
class NormalizedTransaction:
    source: str                           # 'plaid'
    source_id: str                        # Plaid transaction_id
    account_id: str
    item_id: str
    name: str
    merchant_name: str | None
    amount: Decimal                       # Plaid sign: + = outflow (money leaving)
    iso_currency: str
    date: date                            # posted date
    authorized_date: date | None = None
    pending: bool = False
    category_primary: str = ""            # personal_finance_category.primary
    category_detailed: str = ""
    payment_channel: str = ""


@dataclass
class NormalizedSecurity:
    source: str                           # 'plaid'
    source_id: str                        # Plaid security_id
    name: str
    ticker_symbol: str | None
    type: str                             # equity | etf | mutual fund | cryptocurrency | ...
    close_price: Decimal | None = None
    iso_currency: str = "USD"
    is_cash_equivalent: bool = False


@dataclass
class NormalizedHolding:
    source: str                           # 'plaid'
    item_id: str
    account_id: str
    security_id: str
    quantity: Decimal
    cost_basis: Decimal | None = None
    institution_value: Decimal = Decimal("0")
    institution_price: Decimal | None = None
    iso_currency: str = "USD"


@dataclass
class TransactionsDelta:                   # one /transactions/sync page
    added: list[NormalizedTransaction] = field(default_factory=list)
    modified: list[NormalizedTransaction] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)   # transaction_ids
    next_cursor: str = ""
    has_more: bool = False


@dataclass
class NormalizedRecurringStream:           # /transactions/recurring/get
    source: str                            # 'plaid'
    source_id: str                         # Plaid stream_id
    item_id: str
    account_id: str
    stream_type: str                       # 'inflow' | 'outflow'
    description: str
    merchant_name: str | None
    category_primary: str = ""
    category_detailed: str = ""
    average_amount: Decimal = Decimal("0")
    last_amount: Decimal = Decimal("0")
    frequency: str = ""                    # WEEKLY|BIWEEKLY|SEMI_MONTHLY|MONTHLY|ANNUALLY|UNKNOWN
    first_date: date | None = None
    last_date: date | None = None
    predicted_next_date: date | None = None
    is_active: bool = True
    status: str = ""
    iso_currency: str = "USD"


@dataclass
class NormalizedLiability:                  # /liabilities/get
    source: str                            # 'plaid'
    source_id: str                         # = account_id it describes
    item_id: str
    account_id: str
    liability_type: str                    # 'credit' | 'mortgage' | 'student'
    last_statement_balance: Decimal | None = None
    minimum_payment: Decimal | None = None
    next_payment_due_date: date | None = None
    last_payment_amount: Decimal | None = None
    last_payment_date: date | None = None
    apr_percentage: Decimal | None = None
    iso_currency: str = "USD"


@dataclass
class NormalizedInvestmentTransaction:      # /investments/transactions/get
    source: str                            # 'plaid'
    source_id: str                         # investment_transaction_id
    item_id: str
    account_id: str
    security_id: str
    type: str                              # buy|sell|cash|fee|transfer|...
    subtype: str = ""
    name: str = ""
    quantity: Decimal = Decimal("0")
    amount: Decimal = Decimal("0")
    price: Decimal | None = None
    fees: Decimal | None = None
    date: date | None = None
    iso_currency: str = "USD"


@runtime_checkable
class PlaidProvider(Protocol):
    """Read-only Plaid REST adapter. NOT an OAuthProvider (Hosted Link is a
    token exchange, not a redirect code flow). Distinguishing method
    get_accounts. Multi-Item: every data method takes an item's access_token."""
    name: str                             # 'plaid'

    def create_link_token(self, kind: str, access_token: str | None = None) -> dict: ...          # {'link_token','hosted_link_url',...}
    def get_link_public_token(self, link_token: str) -> str | None: ...
    def exchange_public_token(self, public_token: str) -> tuple[str, str]: ...  # (access_token, item_id)
    def get_item(self, access_token: str) -> NormalizedItem: ...
    def get_accounts(self, access_token: str) -> list[NormalizedAccount]: ...
    def sync_transactions(self, access_token: str, cursor: str | None) -> TransactionsDelta: ...
    def get_holdings(self, access_token: str) -> tuple[list[NormalizedAccount],
                                                       list[NormalizedSecurity],
                                                       list[NormalizedHolding]]: ...
    def get_recurring(self, access_token: str) -> list["NormalizedRecurringStream"]: ...
    def get_liabilities(self, access_token: str) -> list["NormalizedLiability"]: ...
    def get_investment_transactions(self, access_token: str, start: "date", end: "date") -> tuple[
        list["NormalizedAccount"], list["NormalizedSecurity"],
        list["NormalizedInvestmentTransaction"]]: ...
    def remove_item(self, access_token: str) -> None: ...
