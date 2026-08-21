# ScuffedOS Privacy Policy

**Effective date:** August 19, 2026

ScuffedOS is a personal assistant application operated by Dylan Schempp ("we," "us"). It combines tasks, calendar, habits, nutrition, notes, and connected health data behind a single AI assistant. ScuffedOS is a self-hosted application: in the current deployment, the operator and the sole user are the same person, and there are no third-party user accounts.

This policy describes what data ScuffedOS stores, how it is used, and which service providers process it. It applies to the ScuffedOS application and any data obtained through connected services such as WHOOP, Gmail, Moodle, Plaid, and macOS Contacts.

## 1. Information we collect

**Information you enter directly.** Tasks and reminders, calendar events, habit definitions and completions, nutrition logs (meals and water), notes and "second-brain" memories, file attachments, and your messages to the assistant (typed or dictated).

**Derived information.** After each assistant conversation, the app may extract short factual "memories" (for example, a stated preference or goal) and store them, along with vector embeddings of that text, so the assistant can recall relevant context later. Conversation history with the assistant is also stored so conversations can resume.

**Connected service data (with your consent).** If you connect a WHOOP account, ScuffedOS retrieves your WHOOP data via the official WHOOP API after you authorize access through WHOOP's OAuth flow. Depending on the scopes you grant, this may include basic profile information, recovery scores, sleep data, strain and workout data, and related physiological measurements such as heart rate. If you connect a Gmail account, ScuffedOS reads your inbox messages via the Gmail API after you authorize access through Google's OAuth flow (read plus the modify/send scopes); it stores email metadata (sender, subject, snippet, and an AI-derived category and summary) but never the message bodies. Beyond reading, ScuffedOS acts on your mailbox only when you take an explicit action — sending, replying, forwarding, moving a message to Trash, starring, marking read/unread, or applying a label. If you connect a Moodle (school learning-management) account, ScuffedOS reads your course information read-only via the Moodle web-services API after you paste in an access token you obtain from your school's Moodle site; it stores course names, assignment due dates, assignment and grade metadata, and short announcement and notification summaries — never assignment files or the full text of course content. If you connect a bank or Coinbase account, ScuffedOS retrieves your financial data read-only through **Plaid** after you authorize each institution through Plaid's own hosted link flow; it stores account names/masks/types, balances, transaction metadata, and investment holdings (including crypto) — plus recurring subscription and bill streams; liabilities (loan and credit-card statement balances, minimum payments, next-payment due dates, and APRs); and investment transaction history — never your bank/Coinbase credentials. If you enable **macOS Contacts**, ScuffedOS reads your local Contacts (AddressBook) database read-only after you grant the app Full Disk Access and acknowledge the storage disclosure; it stores contact names, phone numbers, email addresses, organization and job title, and contact photos. It never writes back to your Contacts, and sends Contacts to no third-party Contacts API; contact fields reach Anthropic when something you ask the assistant makes it look someone up or edit their CRM entry, and conversation text about a contact also passes through the memory pipeline described below. See Section 4 for how WHOOP, Gmail, Moodle, Plaid, and macOS Contacts data are handled.

**What we do not collect.** ScuffedOS contains no advertising, no third-party analytics, and no tracking technologies. ScuffedOS does not collect data about anyone other than the user of the app **except** the contact details you choose to import from your own macOS Contacts (names, phone numbers, email addresses, organization/title, and photos) if you enable that connector — those describe people you already have in your own Contacts, and are used only to power your CRM, to answer your own assistant requests about those people, and (in a future slice) messaging features. We do not sell, share, or otherwise use imported contact data for any purpose beyond your own use of the app.

## 2. How we use information

Data is used solely to provide the app's features:

- Displaying and managing your tasks, calendar, habits, nutrition, and health data.
- Powering the AI assistant — answering questions, taking actions you request, and personalizing responses using stored memories.
- Generating short coaching cards from deterministic fitness signals.
- Generating local reminders and notifications on your device.

We do not sell personal data, share it for advertising or marketing, or use it for any purpose beyond operating the app.

## 3. Service providers

ScuffedOS sends data to a small set of service providers, each for a specific function:

| Provider | Purpose | What is shared |
| --- | --- | --- |
| **Anthropic** (Claude API) | Powers the AI assistant, memory extraction, email triage, and fitness-card phrasing | Your messages to the assistant, conversation history, and data the assistant reads from your stored domains (tasks, calendar, health data, contacts, etc.) in order to respond. When you connect Gmail, each email's sender, subject, preview snippet, and a bounded body excerpt (~2 KB) are sent to Anthropic to classify it and generate a short summary. After a scored recovery sync, deterministic facts for any fired fitness rules (for example, recovery percentage, sleep duration, strain, or a computed delta) are sent to Anthropic to phrase coaching cards; raw snapshot rows are not sent as a bulk dataset. If you enable macOS Contacts, a request that makes the assistant use its People tools sends the matching contacts' names, nicknames, organization/job title, your relationship notes (truncated) and last-contacted dates, and — whenever it works with a single person, whether reading them, adding them, editing their CRM entry, or logging that you spoke — that person's phone numbers and email addresses; contact photos are never sent, only a has-photo flag |
| **OpenAI** | Text embeddings for memory search and memory capture (embeddings only — the assistant itself never calls OpenAI) | The text of each message you send the assistant (embedded to search your memories before it replies), the text of the exchange that follows (your message plus the assistant's reply, embedded during memory capture), and the text of stored memories. Whatever you or the assistant happen to write about a stored domain — contacts included — is embedded along with it; the assistant's tool results are not sent |
| **PostgreSQL database** (the configured server) | Structured app data storage | Tasks, events, habits, nutrition logs, conversations, memories and embeddings, synced WHOOP/finance/Moodle data, email metadata, and imported contact fields (names, phone numbers, emails, organization/title). The database may run locally or on a remote/self-hosted server; when remote, this data is transmitted to that server over TLS. Contact photos are NOT stored here — they stay on the backend host |
| **WHOOP** | Health data source (only if you connect it) | OAuth authorization plus the access token and request parameters needed for API sync; ScuffedOS receives the health data you authorize, while unrelated ScuffedOS domain data is not sent to WHOOP |
| **Google (Gmail)** | Email source — read and user-initiated actions (only if you connect it) | OAuth authorization; ScuffedOS reads your Gmail messages via the Gmail API. Message content is retrieved to display it and (subject + a bounded body excerpt) is sent to Anthropic for triage or, when you ask for an AI draft, to generate one — see Section 4. Actions you take (send, reply, forward, trash, star, read/unread, labels) are carried out via the Gmail API using your own account; sent mail is delivered through Gmail and appears in your Sent folder |
| **Moodle** (school LMS, e.g. NC State WolfWare) | School source, read-only (only if you connect it) | A `wstoken` you provide; ScuffedOS reads your courses, deadlines, grades, and announcements via the Moodle web-services API to display them. Course data may be included in assistant context sent to Anthropic only when you ask the assistant about school — see Section 4 |
| **Plaid** | Bank and Coinbase data source, read-only (only if you connect an institution) | OAuth-style authorization through Plaid's hosted link flow; ScuffedOS sends the access token, cursor, and request parameters needed to retrieve the financial account data you authorize (balances, transactions, investment holdings, recurring subscription/bill streams, liabilities such as loan/credit-card terms, and investment transaction history). Local budget limits and unrelated ScuffedOS data are not sent to Plaid. Financial figures may be included in assistant context sent to Anthropic only when you ask the assistant about your money — see Section 4 |
| **USDA FoodData Central** | Food nutrition lookup | Only the food search text you enter (e.g., "chicken wrap") |
| **Google Fonts** | Loads the app's display typefaces | Ordinary connection metadata such as IP address and user agent; no ScuffedOS content or stored domain data |

Anthropic and OpenAI process API data under their published API data-usage policies, which (as of the effective date) state that API inputs and outputs are not used to train their models.

If you use voice dictation, audio is processed by your browser's built-in speech recognition, which may involve the browser vendor's speech service under that vendor's privacy policy. Only the resulting text transcript reaches ScuffedOS.

File attachments and the memory change-history database are stored locally on the machine running the app, not with any cloud provider. Notifications are generated locally on the backend host.

## 4. WHOOP, Gmail, Moodle, Plaid, and macOS Contacts data

If you choose to connect WHOOP:

- Data is retrieved only after you explicitly authorize ScuffedOS through WHOOP's OAuth consent flow, and only for the scopes you grant.
- WHOOP data is used solely to display your health metrics within ScuffedOS and to let the assistant answer your questions about them. It is never sold, never shared with third parties for their own purposes, and never used for advertising.
- WHOOP data may be included in assistant context sent to Anthropic when you ask the assistant about your health data. Separately, after a scored recovery sync, ScuffedOS may send the deterministic facts for fired fitness rules (for example, recovery percentage, sleep duration, strain, or a computed delta) to Anthropic to phrase short coaching cards. Raw snapshot rows are not sent as a bulk dataset, and local template wording is used if the model is unavailable. WHOOP data is not sent to any other provider.
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
- ScuffedOS does **not** request or store course files or the full body text of assignments or course pages. Links back to Moodle let you open source material there.
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
  and other investment activity). Budgets you set are stored only in the
  configured ScuffedOS database and are never sent to Plaid, your bank, or
  Coinbase; net worth is computed by ScuffedOS.
- **What is not stored:** your bank/Coinbase credentials (Plaid holds those),
  and full statements/documents.
- **Anthropic.** No financial data is sent to Anthropic **except** when you ask
  the assistant about your money — then the relevant figures transit to generate
  the reply and are not stored beyond it. The assistant can edit **local budget
  limits** on your instruction; it can **never** move money.
- **Disconnect.** Disconnecting an institution removes it at Plaid and deletes
  all of its data from Scuffed OS within 30 days.

Scuffed OS is not affiliated with Plaid, Coinbase, or your bank.

### If you enable macOS Contacts

ScuffedOS can import your local macOS Contacts so the People (CRM) screen shows
your real contacts instead of sample data.

- **Consent, gated twice.** Nothing is read until you explicitly enable this
  connector **and** grant ScuffedOS Full Disk Access in macOS System Settings —
  both are required. Enabling also requires acknowledging a storage
  disclosure that explains where the data goes (below) before the first sync
  runs.
- **How it's read.** Your local Contacts (AddressBook) database is read
  **read-only** and **one-way** — ScuffedOS never writes back to Apple
  Contacts. Only fields you already have in Contacts are read: names, phone
  numbers, email addresses, organization and job title, and photos.
- **Where it's stored.** Contact names, phone numbers, email addresses, and
  organization/title are written to the configured PostgreSQL database (which
  may be remote — see Section 5; transmitted over TLS when it is). Contact
  **photos are not put in the database** — they are stored as files on the
  backend host running the app.
- **No third-party Contacts API. The assistant, when you ask.** Contacts
  data is sent to **no third-party Contacts API**, and nothing about your
  contacts is uploaded in the background — syncing writes to your own database
  and stops there. Contact data reaches **Anthropic** when a request you
  make to the assistant causes it to use one of its People tools: searching
  your contacts, opening one, adding someone by hand, editing what you know
  about them, or logging that you were in touch. What can transit then: the
  person's name, nickname, organization and job title; how you know them, your
  strength rating, whether they're pinned, when you last spoke, and your notes
  (capped at 200 characters in a search result); plus the row's ScuffedOS id
  and whether the entry came from your macOS Contacts or was added by hand.
  Whenever a tool touches **one specific person** — opening them, or any of
  the three writes (adding someone, editing what you know about them, logging
  that you were in touch) — the result also carries that person's **phone
  numbers and email addresses** and up to 1,000 characters of your notes. So
  "I called mom today" sends back mom's full numbers, addresses and notes, not
  just her name; only a search across many people stays on the shorter row. A
  search also reports how many contacts you have in total. Contact **photos
  are never sent** — the assistant sees only a yes/no has-photo flag — and
  neither are the normalized matching forms of phone
  numbers and email addresses or the identifiers linking a row back to Apple
  Contacts. **There is no separate opt-in for this**: enabling the Contacts
  connector is the only choice you make, and from then on the assistant's
  People tools are always available to your requests. What the assistant can
  **change** is narrower than what it can read: your own CRM fields
  (relationship, strength, notes, pinned, last-contacted) plus adding a person
  by hand — it cannot edit the name, phone numbers, emails or organization on
  an imported contact, and it has no tool to delete anyone.
- **Memory, and the one other provider.** A conversation about a contact does
  not end with that turn. Every assistant turn runs through the memory
  pipeline described in Sections 1 and 3: before the reply, the text of your
  message is embedded by **OpenAI** to search your stored memories; after it,
  your message together with the assistant's reply is embedded by OpenAI again
  and passed to **Anthropic** for fact extraction, and each fact extracted is
  embedded once more and stored. Tool results are not part of this — the
  contact rows the assistant read are never handed to the memory pipeline —
  but anything about a contact that appears in what you typed or in what the
  assistant wrote back does reach OpenAI as text to embed, and can be
  extracted into a stored memory. And because stored memories are searched and
  pasted into the assistant's context on **every** turn, a fact learned from a
  People conversation can be sent to Anthropic again later, on an unrelated
  turn. Apart from Anthropic, OpenAI, and the database itself, contacts go to
  no other provider; they are never sold, never shared with third parties for
  their own purposes, and never used for advertising.
- **Revocation.** You can revoke access by turning off Full Disk Access for
  ScuffedOS in System Settings, and/or by **Disconnecting** the connector
  in-app (stops future syncing but keeps your existing CRM data — relationship
  notes, pinned contacts, etc. — intact, and the assistant's People tools can
  still read what is kept), or by using **Forget imported data**
  (deletes the imported contacts, their handle index, and their photos; a
  contact carrying any CRM-native data — a relationship, a strength, notes, a
  pin, or a last-contacted date — is converted into a manually-owned entry
  that keeps their name and that history rather than losing it).
- **Retention.** Imported contact data persists until you Forget it or delete
  an individual manually-owned entry. If access is revoked (Full Disk Access
  turned off) without disconnecting or forgetting, ScuffedOS shows the
  connector as **stale** and preserves your existing rows rather than
  deleting them.

## 5. Data storage and security

- App data is stored in the configured PostgreSQL database, which may run locally or on a remote/self-hosted server; attachments, the memory history file, and imported contact photos are stored on the backend host running the app.
- Traffic to external service providers uses TLS. A non-loopback (remote) database connection requires TLS (`sslmode=require` or stronger); the packaged app's managed local database instead uses a user-local Unix socket and is not exposed on the network. Connection strings and credentials are never written to logs.
- API credentials and OAuth tokens are stored server-side, never in the client. Static API keys come from server-side configuration; OAuth tokens obtained when you connect a service (such as WHOOP) are stored in the server-side database and are never exposed to the client.
- In the packaged desktop app, API keys and provider client credentials are stored on your Mac in a machine-bound, AES-256-GCM encrypted vault (`secrets.enc`); the encryption key is derived from your machine's hardware identifier and wrapped in the macOS Keychain. Provider access/refresh tokens remain in the app-managed local PostgreSQL database and are never exposed to the client. These credentials do not leave your machine except when sent to the service they authenticate with.
- Access to the database and the machine running the app is limited to the operator.

No system is perfectly secure, but as a single-user, self-hosted application, ScuffedOS's exposure surface is intentionally small.

## 6. Data retention and deletion

Data is retained until it is deleted. ScuffedOS provides in-app deletion controls for many local records plus integration-specific Disconnect and Forget actions; the operator can also delete any record — or all data — directly from the database. Disconnecting WHOOP triggers deletion of synced WHOOP data and tokens as described in Section 4; disconnecting Gmail likewise deletes stored email metadata and Google OAuth tokens; disconnecting Moodle likewise deletes all stored Moodle data (courses, deadlines, assignments, grades, announcements, notifications) and your Moodle access token. Connected-institution data is deleted within 30 days of disconnecting a bank or Coinbase account linked through Plaid. **Disconnecting macOS Contacts is not deletion** — it stops future syncing but keeps your already-imported contacts and CRM data; use **Forget imported data** within ScuffedOS to delete the imported contacts, handle index, and photos (see Section 4). For any deletion request, contact us at the address below and it will be honored within 30 days.

## 7. Your rights and choices

You can access, correct, or delete data through the in-app controls and assistant tools available for each domain; the operator can also export or delete records directly from the database. You can decline to connect WHOOP, Gmail, Moodle, Plaid, or macOS Contacts (the rest of the app works without any of them), disable voice dictation by simply not using the microphone, and disconnect any integration at any time. For macOS Contacts specifically, use **Forget imported data** (Section 4) to delete previously-imported contact data, not just Disconnect.

## 8. Children

ScuffedOS is not directed at children and is not intended for use by anyone under 13 (or the minimum age required in your jurisdiction).

## 9. Changes to this policy

If the app's data practices change — for example, when new integrations are added — this policy will be updated and the effective date revised. The current version is always available at the URL where you are reading it.

## 10. Contact

Questions, or a data access/deletion request? Email **contact@scuffedcorporation.com**.
