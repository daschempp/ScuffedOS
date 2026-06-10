/* Scuffed OS — Email triage & response drafting */
function EmailScreen() {
  const emails = [
    { id: 1, from: "Priya Anand", time: "8:24am", cat: "Needs reply", unread: true, tint: "sky",
      subject: "Lighthouse timeline — can we confirm the 30th?",
      snippet: "Wanted to lock the new ship date before I update the roadmap…",
      summary: ["Priya wants to confirm the June 30 ship date.", "She needs it before updating the public roadmap.", "Asking you to loop in design review by the 20th."],
      drafts: {
        Friendly: "Hi Priya,\n\nThe 30th works on my end — let's lock it in. I'll get design review scheduled before the 20th and send you the calendar invite today.\n\nThanks for keeping this moving!\nSam",
        Brief: "Hi Priya — 30th works. I'll set up design review before the 20th and send the invite today. — Sam",
        Formal: "Hi Priya,\n\nConfirming June 30 works. I'll arrange the design review ahead of the 20th and forward an invitation shortly.\n\nBest,\nSam",
      } },
    { id: 2, from: "Oak St. Realty", time: "Yesterday", cat: "Needs reply", unread: true, tint: "honey",
      subject: "Lease renewal — action needed by Jun 25",
      snippet: "Your lease is up for renewal. Please confirm whether you intend to…",
      summary: ["Lease renews; they need your decision by Jun 25.", "Rent stays at $1,450 if you renew for 12 months.", "Month-to-month would increase to $1,610."],
      drafts: {
        Friendly: "Hi,\n\nThanks for the heads up — I'd like to renew for another 12 months at the current rate. Happy to sign whenever the paperwork's ready.\n\nBest,\nSam",
        Brief: "Hi — I'll renew for 12 months at $1,450. Send the paperwork whenever. — Sam",
        Formal: "Hello,\n\nI would like to renew for a 12-month term at the current rate of $1,450. Please send the renewal documents at your convenience.\n\nRegards,\nSam",
      } },
    { id: 3, from: "Jordan Lee", time: "Tue", cat: "Needs reply", unread: false, tint: "green",
      subject: "Dinner this weekend?",
      snippet: "It's been ages! Free Saturday for that ramen place we talked about?",
      summary: ["Jordan's inviting you to dinner Saturday.", "Suggesting the ramen place you'd discussed.", "It's been a while since you caught up."],
      drafts: {
        Friendly: "Yes!! Saturday's perfect — I've been craving that ramen. 7pm? Can't wait to catch up.\n\n— Sam",
        Brief: "Saturday works — 7pm at the ramen place? — Sam",
        Formal: "Hi Jordan,\n\nSaturday works well. Shall we say 7pm at the ramen restaurant?\n\nBest,\nSam",
      } },
    { id: 4, from: "Vanguard", time: "Jun 5", cat: "FYI", unread: false, tint: "clay",
      subject: "Your June statement is ready",
      snippet: "Your account statement for the period ending May 31 is now available…",
      summary: ["Monthly statement is available.", "Portfolio up 0.9% for the period.", "No action required."] },
    { id: 5, from: "Figma", time: "Jun 4", cat: "FYI", unread: false, tint: "plum",
      subject: "What's new this month",
      snippet: "New cursor chat, dev mode updates, and more in this month's roundup…",
      summary: ["Product newsletter — feature roundup.", "Highlights: cursor chat, dev mode updates.", "No action required."] },
  ];
  const [selId, setSelId] = React.useState(1);
  const [tone, setTone] = React.useState("Friendly");
  const sel = emails.find((e) => e.id === selId);
  const cats = ["Needs reply", "FYI"];

  return (
    <div className="kit-grid" style={{ gridTemplateColumns: "1fr 1.15fr" }}>
      <Card title="Inbox" eyebrow="12 new · I triaged & cleared 8" action={<Badge color="green" dot>4 need you</Badge>}>
        {cats.map((c) => (
          <div key={c}>
            <p className="sa-card__eyebrow" style={{ margin: "12px 0 4px" }}>{c}</p>
            {emails.filter((e) => e.cat === c).map((e) => (
              <div key={e.id} className={"kit-mail" + (e.id === selId ? " is-active" : "")} onClick={() => { setSelId(e.id); setTone("Friendly"); }}>
                <span className={"kit-mail__dot" + (e.unread ? "" : " read")} />
                <div className="kit-mail__main">
                  <div className="kit-mail__top">
                    <span className="kit-mail__from">{e.from}</span>
                    <span className="kit-mail__time">{e.time}</span>
                  </div>
                  <p className="kit-mail__subj">{e.subject}</p>
                  <p className="kit-mail__snip">{e.snippet}</p>
                </div>
              </div>
            ))}
          </div>
        ))}
      </Card>

      <div className="kit-col">
        <Card eyebrow={sel.from} title={sel.subject} action={<IconButton label="Archive"><Icon name="archive" /></IconButton>}>
          <p className="sa-card__eyebrow" style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 10 }}><Icon name="sparkles" style={{ width: 13, height: 13 }} />AI summary</p>
          <div className="kit-bullets">
            {sel.summary.map((b, i) => (
              <div className="kit-bullet" key={i}><Icon name="check" />{b}</div>
            ))}
          </div>
        </Card>

        {sel.drafts ? (
          <Card title="Suggested reply" action={
            <div className="kit-cal__seg" style={{ marginLeft: 0 }}>
              {["Friendly", "Brief", "Formal"].map((t) => (
                <button key={t} className={tone === t ? "is-on" : ""} onClick={() => setTone(t)}>{t}</button>
              ))}
            </div>
          }>
            <div className="kit-draft">{sel.drafts[tone]}</div>
            <div className="kit-inline" style={{ marginTop: 14 }}>
              <Button variant="primary" iconLeft={<Icon name="send" />}>Send</Button>
              <Button variant="secondary" iconLeft={<Icon name="pen-line" />}>Edit</Button>
              <Button variant="ghost" iconLeft={<Icon name="refresh-cw" />}>Regenerate</Button>
            </div>
          </Card>
        ) : (
          <Card variant="sunken">
            <div className="kit-insight">
              <div className="kit-insight__icon"><Icon name="check-check" /></div>
              <p>No reply needed — I've filed this as <strong>FYI</strong>. Archive it or keep for later.</p>
            </div>
            <div className="kit-inline" style={{ marginTop: 12 }}>
              <Button variant="soft" size="sm" iconLeft={<Icon name="archive" />}>Archive</Button>
            </div>
          </Card>
        )}
      </div>
    </div>
  );
}
window.EmailScreen = EmailScreen;
