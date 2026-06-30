# ScuffedOS Privacy Policy

**Effective date:** June 10, 2026

ScuffedOS is a personal assistant application operated by Dylan Schempp ("we," "us"). It combines tasks, calendar, habits, nutrition, notes, and connected health data behind a single AI assistant. ScuffedOS is a self-hosted application: in the current deployment, the operator and the sole user are the same person, and there are no third-party user accounts.

This policy describes what data ScuffedOS stores, how it is used, and which service providers process it. It applies to the ScuffedOS application and any data obtained through connected services such as WHOOP.

## 1. Information we collect

**Information you enter directly.** Tasks and reminders, calendar events, habit definitions and completions, nutrition logs (meals and water), notes and "second-brain" memories, file attachments, and your messages to the assistant (typed or dictated).

**Derived information.** After each assistant conversation, the app may extract short factual "memories" (for example, a stated preference or goal) and store them, along with vector embeddings of that text, so the assistant can recall relevant context later. Conversation history with the assistant is also stored so conversations can resume.

**Connected service data (with your consent).** If you connect a WHOOP account, ScuffedOS retrieves your WHOOP data via the official WHOOP API after you authorize access through WHOOP's OAuth flow. Depending on the scopes you grant, this may include basic profile information, recovery scores, sleep data, strain and workout data, and related physiological measurements such as heart rate. See Section 4 for how WHOOP data is handled.

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
| **Anthropic** (Claude API) | Powers the AI assistant and memory extraction | Your messages to the assistant, conversation history, and data the assistant reads from your stored domains (tasks, calendar, health data, etc.) in order to respond |
| **OpenAI** | Text embeddings for memory search (embeddings only — the assistant itself never calls OpenAI) | The text of stored memories |
| **Supabase** | Managed Postgres database hosting | Structured app data: tasks, events, habits, nutrition logs, conversations, memories and their embeddings, and synced WHOOP data |
| **WHOOP** | Health data source (only if you connect it) | OAuth authorization; ScuffedOS receives data from WHOOP, not the reverse |
| **USDA FoodData Central** | Food nutrition lookup | Only the food search text you enter (e.g., "chicken wrap") |

Anthropic and OpenAI process API data under their published API data-usage policies, which (as of the effective date) state that API inputs and outputs are not used to train their models.

If you use voice dictation, audio is processed by your browser's built-in speech recognition, which may involve the browser vendor's speech service under that vendor's privacy policy. Only the resulting text transcript reaches ScuffedOS.

File attachments and the memory change-history database are stored locally on the machine running the app, not with any cloud provider. Notifications are generated locally on-device.

## 4. WHOOP data

If you choose to connect WHOOP:

- Data is retrieved only after you explicitly authorize ScuffedOS through WHOOP's OAuth consent flow, and only for the scopes you grant.
- WHOOP data is used solely to display your health metrics within ScuffedOS and to let the assistant answer your questions about them. It is never sold, never shared with third parties for their own purposes, and never used for advertising.
- WHOOP data may be included in assistant context sent to Anthropic when you ask the assistant about your health data (Section 3); it is not sent to any other provider.
- You can revoke ScuffedOS's access at any time from your WHOOP account settings or by disconnecting WHOOP within ScuffedOS. Upon disconnection or request, stored WHOOP data and access tokens are deleted within 30 days.

ScuffedOS is an independent application and is not affiliated with, endorsed by, or sponsored by WHOOP.

## 5. Data storage and security

- App data is stored in a Postgres database hosted by Supabase; attachments and the memory history file are stored on the operator's machine.
- Data is encrypted in transit (TLS) between the app, the database, and all service providers.
- API credentials and OAuth tokens are stored server-side, never in the client. Static API keys come from server-side configuration; OAuth tokens obtained when you connect a service (such as WHOOP) are stored in the server-side database and are never exposed to the client.
- Access to the database and the machine running the app is limited to the operator.

No system is perfectly secure, but as a single-user, self-hosted application, ScuffedOS's exposure surface is intentionally small.

## 6. Data retention and deletion

Data is retained until you delete it. ScuffedOS provides in-app deletion for every domain (tasks, events, habits, logs, memories, conversations), and the operator can delete any record — or all data — directly from the database at any time. Disconnecting WHOOP triggers deletion of synced WHOOP data and tokens as described in Section 4. For any deletion request, contact us at the address below and it will be honored within 30 days.

## 7. Your rights and choices

You can access, correct, export, or delete your data at any time — in-app, via the assistant, or by direct database access. You can decline to connect WHOOP (the rest of the app works without it), disable voice dictation by simply not using the microphone, and disconnect any integration at any time.

## 8. Children

ScuffedOS is not directed at children and is not intended for use by anyone under 13 (or the minimum age required in your jurisdiction).

## 9. Changes to this policy

If the app's data practices change — for example, when new integrations are added — this policy will be updated and the effective date revised. The current version is always available at the URL where you are reading it.

## 10. Contact

Questions, or a data access/deletion request? Email **contact@scuffedcorporation.com**.
