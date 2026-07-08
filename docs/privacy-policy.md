# ScuffedOS Privacy Policy

**Effective date:** July 7, 2026

ScuffedOS is a personal assistant application operated by Dylan Schempp ("we," "us"). It combines tasks, calendar, habits, nutrition, notes, and connected health data behind a single AI assistant. ScuffedOS is a self-hosted application: in the current deployment, the operator and the sole user are the same person, and there are no third-party user accounts.

This policy describes what data ScuffedOS stores, how it is used, and which service providers process it. It applies to the ScuffedOS application and any data obtained through connected services such as WHOOP, Gmail, Moodle, and Plaid.

## 1. Information we collect

**Information you enter directly.** Tasks and reminders, calendar events, habit definitions and completions, nutrition logs (meals and water), notes and "second-brain" memories, file attachments, and your messages to the assistant (typed or dictated).

**Derived information.** After each assistant conversation, the app may extract short factual "memories" (for example, a stated preference or goal) and store them, along with vector embeddings of that text, so the assistant can recall relevant context later. Conversation history with the assistant is also stored so conversations can resume.

**Connected service data (with your consent).** If you connect a WHOOP account, ScuffedOS retrieves your WHOOP data via the official WHOOP API after you authorize access through WHOOP's OAuth flow. Depending on the scopes you grant, this may include basic profile information, recovery scores, sleep data, strain and workout data, and related physiological measurements such as heart rate. If you connect a Gmail account, ScuffedOS reads your inbox messages via the Gmail API after you authorize access through Google's OAuth flow (read plus the modify/send scopes); it stores email metadata (sender, subject, snippet, and an AI-derived category and summary) but never the message bodies. Beyond reading, ScuffedOS acts on your mailbox only when you take an explicit action — sending, replying, forwarding, moving a message to Trash, starring, marking read/unread, or applying a label. If you connect a Moodle (school learning-management) account, ScuffedOS reads your course information read-only via the Moodle web-services API after you paste in an access token you obtain from your school's Moodle site; it stores course names, assignment due dates, assignment and grade metadata, and short announcement and notification summaries — never assignment files or the full text of course content. If you connect a bank or Coinbase account, ScuffedOS retrieves your financial data read-only through **Plaid** after you authorize each institution through Plaid's own hosted link flow; it stores account names/masks/types, balances, transaction metadata, and investment holdings (including crypto) — plus recurring subscription and bill streams; liabilities (loan and credit-card statement balances, minimum payments, next-payment due dates, and APRs); and investment transaction history — never your bank/Coinbase credentials. See Section 4 for how WHOOP, Gmail, Moodle, and Plaid data are handled.

**What we do not collect.** ScuffedOS contains no advertising, no third-party analytics, and no tracking technologies. We do not collect data about anyone other than the user of the app.

## 2. How we use information

Data is used solely to provide the app's features:

- Displaying and managing your tasks, calendar, habits, nutrition, and health data.
- Powering the AI assistant — answering questions, taking actions you request, and personalizing responses using stored memories.
- Generating local reminders and notifications on your device.

We do not sell personal data, share it for advertising or marketing, or use it for any purpose beyond operating the app.

## 3. Service providers

ScuffedOS sends data to a small set of service providers, each for a specific function:

| Provider | Purpose | What is shared |
| --- | --- | --- |
| **Anthropic** (Claude API) | Powers the AI assistant, memory extraction, and email triage | Your messages to the assistant, conversation history, and data the assistant reads from your stored domains (tasks, calendar, health data, etc.) in order to respond. When you connect Gmail, each email's sender, subject, preview snippet, and a bounded body excerpt (~2 KB) are sent to Anthropic to classify it and generate a short summary |
| **OpenAI** | Text embeddings for memory search (embeddings only — the assistant itself never calls OpenAI) | The text of stored memories |
| **Supabase** | Managed Postgres database hosting | Structured app data: tasks, events, habits, nutrition logs, conversations, memories and their embeddings, synced WHOOP data, and email metadata (sender, subject, snippet, and AI-derived category/summary — no message bodies) |
| **WHOOP** | Health data source (only if you connect it) | OAuth authorization; ScuffedOS receives data from WHOOP, not the reverse |
| **Google (Gmail)** | Email source — read and user-initiated actions (only if you connect it) | OAuth authorization; ScuffedOS reads your Gmail messages via the Gmail API. Message content is retrieved to display it and (subject + a bounded body excerpt) is sent to Anthropic for triage or, when you ask for an AI draft, to generate one — see Section 4. Actions you take (send, reply, forward, trash, star, read/unread, labels) are carried out via the Gmail API using your own account; sent mail is delivered through Gmail and appears in your Sent folder |
| **Moodle** (school LMS, e.g. NC State WolfWare) | School source, read-only (only if you connect it) | A `wstoken` you provide; ScuffedOS reads your courses, deadlines, grades, and announcements via the Moodle web-services API to display them. Course data may be included in assistant context sent to Anthropic only when you ask the assistant about school — see Section 4 |
| **Plaid** | Bank and Coinbase data source, read-only (only if you connect an institution) | OAuth-style authorization through Plaid's hosted link flow; ScuffedOS receives access to the financial account data you authorize (balances, transactions, investment holdings, recurring subscription/bill streams, liabilities such as loan/credit-card terms, and investment transaction history) via the Plaid API — Plaid never receives data from ScuffedOS beyond the link setup. Financial figures may be included in assistant context sent to Anthropic only when you ask the assistant about your money — see Section 4 |
| **USDA FoodData Central** | Food nutrition lookup | Only the food search text you enter (e.g., "chicken wrap") |

Anthropic and OpenAI process API data under their published API data-usage policies, which (as of the effective date) state that API inputs and outputs are not used to train their models.

If you use voice dictation, audio is processed by your browser's built-in speech recognition, which may involve the browser vendor's speech service under that vendor's privacy policy. Only the resulting text transcript reaches ScuffedOS.

File attachments and the memory change-history database are stored locally on the machine running the app, not with any cloud provider. Notifications are generated locally on-device.

## 4. WHOOP, Gmail, Moodle, and Plaid data

If you choose to connect WHOOP:

- Data is retrieved only after you explicitly authorize ScuffedOS through WHOOP's OAuth consent flow, and only for the scopes you grant.
- WHOOP data is used solely to display your health metrics within ScuffedOS and to let the assistant answer your questions about them. It is never sold, never shared with third parties for their own purposes, and never used for advertising.
- WHOOP data may be included in assistant context sent to Anthropic when you ask the assistant about your health data (Section 3); it is not sent to any other provider.
- You can revoke ScuffedOS's access at any time from your WHOOP account settings or by disconnecting WHOOP within ScuffedOS. Upon disconnection or request, stored WHOOP data and access tokens are deleted within 30 days.

ScuffedOS is an independent application and is not affiliated with, endorsed by, or sponsored by WHOOP.

If you choose to connect Gmail:

- Access is granted only after you explicitly authorize ScuffedOS through Google's OAuth consent flow, and covers **read plus the modify/send scopes** (`gmail.readonly`, `gmail.modify`, `gmail.send`). You can review and revoke this access at any time from your Google Account's security settings.
- ScuffedOS reads your inbox messages to display them and to triage them. For each message, the sender, subject, preview snippet, and a bounded plain-text body excerpt (~2 KB) are sent to **Anthropic** to classify the message (needs-reply vs. FYI) and generate a short summary. Only the derived category and summary — never the message body — are stored.
- **Message bodies are not stored.** The inbox list and AI summaries live in the database; the full body of a message is fetched live from the Gmail API only when you open that message, and is never written to disk.
- Beyond reading, ScuffedOS **acts on your mailbox only on your explicit action.** You can send a new message, reply, or forward; move a message to Trash; star or unstar it; mark it read or unread; and apply or remove labels. Every one of these actions happens only when you click the corresponding control — nothing is automated.
- **AI-drafted replies are generated only when you ask for one**, using the instructions and any notes you type into the compose box at that moment. A draft is never generated automatically (not on opening a message, not on sync). Draft text is **never stored server-side** — it exists only in your compose box until you send it or discard it.
- **Outbound mail is sent through Gmail itself.** When you send, reply, or forward, ScuffedOS submits the message to the Gmail API using your own authorized account; Gmail delivers it, and it appears in your Gmail Sent folder exactly as if you had sent it from Gmail directly.
- Gmail data is never sold, never shared with third parties for their own purposes, and never used for advertising.
- You can disconnect Gmail within ScuffedOS at any time. On disconnect, stored email metadata and your Google OAuth tokens are deleted, and ScuffedOS revokes its Google access token. As with all deletions, this is honored within 30 days.

ScuffedOS is an independent application and is not affiliated with, endorsed by, or sponsored by Google.

If you choose to connect Moodle:

- Access is **read-only** and is granted only after you explicitly provide an access token (a `wstoken`) that you obtain from your school's Moodle site (for NC State WolfWare, from the Security-keys page after signing in). ScuffedOS never sees your school username or password; only the token you paste is stored, server-side, and it is never exposed to the client.
- ScuffedOS reads your course data to display it in the School section. It **stores** your course names, assignment due dates, assignment and grade metadata (title, status, points), and short announcement and notification summaries.
- ScuffedOS does **not** store the contents of course files or the full body text of assignments or course pages. Those are **fetched live** from Moodle only when you open them, and are never written to disk.
- Assignment deadlines from Moodle are **projected into your Calendar and Tasks locally** so they appear alongside your own events and to-dos. These projected entries are read-only markers derived from Moodle data — they are not copied into your calendar or task tables and cannot be edited or deleted through ScuffedOS; changing them happens in Moodle.
- Moodle data is **never sent to Anthropic except when you ask the assistant about your school** (for example, "what's due this week?"); it is never sent to any other provider, never sold, never shared with third parties for their own purposes, and never used for advertising.
- You can disconnect Moodle within ScuffedOS at any time. On disconnect, all stored Moodle data and your access token are deleted. As with all deletions, this is honored within 30 days.

ScuffedOS is an independent application and is not affiliated with, endorsed by, or sponsored by Moodle, Moodle Pty Ltd, or North Carolina State University.

### If you choose to connect a bank or Coinbase (Plaid)

Scuffed OS can link your financial institutions through **Plaid** so the Finance
screen shows real balances, transactions, net worth, and investment holdings
(including Coinbase crypto). This is **read-only**: the app **never moves money,
initiates a transfer, or writes anything back to your bank or Coinbase.**

- **How it connects.** You link an institution through Plaid's own hosted flow.
  **Plaid handles your bank/Coinbase login — Scuffed OS never sees your
  credentials.** Plaid returns an access token that lets us read your data; that
  token is stored **server-side only** and never sent to the browser.
- **What is stored:** institution and account names/masks/types, balances,
  transaction metadata (date, amount, merchant, Plaid category), and investment
  holdings + securities (including crypto). Also stored: **recurring
  subscription and bill streams** (merchant, cadence, amount); **liabilities**
  — loan and credit-card statement balances, minimum payments, next-payment
  due dates, and APRs; and **investment transaction history** (buys, sells,
  and other investment activity). Budgets you set are **local** and
  never leave the app; net worth is computed locally.
- **What is not stored:** your bank/Coinbase credentials (Plaid holds those),
  and full statements/documents.
- **Anthropic.** No financial data is sent to Anthropic **except** when you ask
  the assistant about your money — then the relevant figures transit to generate
  the reply and are not stored beyond it. The assistant can edit **local budget
  limits** on your instruction; it can **never** move money.
- **Disconnect.** Disconnecting an institution removes it at Plaid and deletes
  all of its data from Scuffed OS within 30 days.

Scuffed OS is not affiliated with Plaid, Coinbase, or your bank.

## 5. Data storage and security

- App data is stored in a Postgres database hosted by Supabase; attachments and the memory history file are stored on the operator's machine.
- Data is encrypted in transit (TLS) between the app, the database, and all service providers.
- API credentials and OAuth tokens are stored server-side, never in the client. Static API keys come from server-side configuration; OAuth tokens obtained when you connect a service (such as WHOOP) are stored in the server-side database and are never exposed to the client.
- In the packaged desktop app, API keys and OAuth tokens are stored on your Mac in a machine-bound, AES-256-GCM encrypted vault (`secrets.enc`) rather than in a database; the encryption key is derived from your machine's hardware identifier and wrapped in the macOS Keychain. These secrets never leave your machine.
- Access to the database and the machine running the app is limited to the operator.

No system is perfectly secure, but as a single-user, self-hosted application, ScuffedOS's exposure surface is intentionally small.

## 6. Data retention and deletion

Data is retained until you delete it. ScuffedOS provides in-app deletion for every domain (tasks, events, habits, logs, memories, conversations), and the operator can delete any record — or all data — directly from the database at any time. Disconnecting WHOOP triggers deletion of synced WHOOP data and tokens as described in Section 4; disconnecting Gmail likewise deletes stored email metadata and Google OAuth tokens; disconnecting Moodle likewise deletes all stored Moodle data (courses, deadlines, assignments, grades, announcements, notifications) and your Moodle access token. Connected-institution data is deleted within 30 days of disconnecting a bank or Coinbase account linked through Plaid. For any deletion request, contact us at the address below and it will be honored within 30 days.

## 7. Your rights and choices

You can access, correct, export, or delete your data at any time — in-app, via the assistant, or by direct database access. You can decline to connect WHOOP or Gmail (the rest of the app works without either), disable voice dictation by simply not using the microphone, and disconnect any integration at any time.

## 8. Children

ScuffedOS is not directed at children and is not intended for use by anyone under 13 (or the minimum age required in your jurisdiction).

## 9. Changes to this policy

If the app's data practices change — for example, when new integrations are added — this policy will be updated and the effective date revised. The current version is always available at the URL where you are reading it.

## 10. Contact

Questions, or a data access/deletion request? Email **contact@scuffedcorporation.com**.
