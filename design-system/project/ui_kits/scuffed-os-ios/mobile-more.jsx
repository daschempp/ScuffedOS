/* Scuffed OS — iPhone: More menu + Fitness / Habits / People / Email screens */

function MoreScreen({ onOpen }) {
  const groups = [
    { label: "Health", items: [
      { id: "nutrition", lab: "Nutrition", sub: "1,690 kcal · 410 to go", icon: "apple", tint: "green" },
      { id: "fitness", lab: "Fitness", sub: "82% recovered · Whoop", icon: "activity", tint: "clay" },
    ] },
    { label: "Daily", items: [
      { id: "habits", lab: "Habits", sub: "2 of 5 done today", icon: "repeat", tint: "honey" },
    ] },
    { label: "Inbox & people", items: [
      { id: "email", lab: "Email", sub: "4 need a reply", icon: "mail", tint: "sky" },
      { id: "people", lab: "People", sub: "2 to reach out to", icon: "users", tint: "plum" },
    ] },
    { label: "Intelligence", items: [
      { id: "memory", lab: "Second Brain", sub: "142 memories", icon: "brain", tint: "green" },
    ] },
  ];
  return (
    <div className="m-screen">
      <div className="m-head"><h1 className="m-title">More</h1></div>
      {groups.map((g, i) => (
        <div key={i} className="m-more">
          <div className="m-sectionhead"><h3 style={{ fontSize: 13, textTransform: "uppercase", letterSpacing: "var(--tracking-caps)", color: "var(--text-faint)" }}>{g.label}</h3></div>
          <div className="m-menu">
            {g.items.map((it) => (
              <div className="m-menu__row" key={it.id} onClick={() => onOpen(it.id)}>
                <span className="m-menu__ico" style={{ background: `var(--${it.tint}-100)`, color: `var(--${it.tint}-600)` }}><Icon name={it.icon} /></span>
                <span className="m-menu__lab"><b>{it.lab}</b><span>{it.sub}</span></span>
                <span className="m-menu__chev"><Icon name="chevron-right" /></span>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function MobileFitness() {
  const vitals = [
    { lab: "HRV", val: "68", unit: "ms", icon: "activity", tint: "green" },
    { lab: "Resting HR", val: "52", unit: "bpm", icon: "heart", tint: "clay" },
    { lab: "Respiratory", val: "14.2", unit: "rpm", icon: "wind", tint: "sky" },
    { lab: "Sleep", val: "7:38", unit: "hrs", icon: "moon", tint: "plum" },
  ];
  const workouts = [
    { name: "Morning run", when: "Today · 32 min · 318 cal", icon: "footprints", tint: "green", strain: "9.4" },
    { name: "Strength — push", when: "Yesterday · 48 min", icon: "dumbbell", tint: "clay", strain: "11.2" },
    { name: "Cycling", when: "Mon · 1:05 · 540 cal", icon: "bike", tint: "sky", strain: "13.1" },
  ];
  return (
    <React.Fragment>
      <Card style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 6 }} action={null}>
        <Badge color="green" dot>Synced with Whoop</Badge>
        <ProgressRing value={82} max={100} size={142} thickness={13} color="green" label="82%" sublabel="recovery" />
        <div style={{ display: "flex", gap: 22 }}>
          <div className="m-ring"><ProgressRing value={14.2} max={21} size={64} color="sky" label="14.2" sublabel="strain" /></div>
          <div className="m-ring"><ProgressRing value={91} max={100} size={64} color="plum" label="91%" sublabel="sleep" /></div>
        </div>
      </Card>
      <Card title="Vitals">
        <div className="kit-statgrid">
          {vitals.map((v, i) => (
            <div className="kit-statline" key={i}>
              <span className="kit-statline__ico" style={{ background: `var(--${v.tint}-100)`, color: `var(--${v.tint}-600)` }}><Icon name={v.icon} /></span>
              <div><div className="kit-statline__lab">{v.lab}</div><div className="kit-statline__val">{v.val}<span style={{ fontSize: 11, color: "var(--text-faint)" }}> {v.unit}</span></div></div>
            </div>
          ))}
        </div>
      </Card>
      <Card title="Workouts" action={<Badge color="green" icon={<Icon name="plus" />}>Log</Badge>}>
        {workouts.map((w, i) => (
          <div className="m-row" key={i}>
            <span className="m-ico" style={{ background: `var(--${w.tint}-100)`, color: `var(--${w.tint}-600)` }}><Icon name={w.icon} /></span>
            <div className="m-row__main"><p className="m-row__title">{w.name}</p><p className="m-row__sub">{w.when}</p></div>
            <Badge color="sky">{w.strain}</Badge>
          </div>
        ))}
      </Card>
    </React.Fragment>
  );
}

function MobileHabits() {
  const DOW = ["M", "T", "W", "T", "F", "S", "S"];
  const TODAY = 1;
  const [habits, setHabits] = React.useState([
    { id: 1, name: "Meditate", icon: "flower-2", tint: "green", streak: 12, days: [1, 1, 0, 0, 0, 0, 0] },
    { id: 2, name: "Read 30 min", icon: "book-open", tint: "sky", streak: 5, days: [1, 1, 0, 0, 0, 0, 0] },
    { id: 3, name: "Workout", icon: "dumbbell", tint: "clay", streak: 3, days: [1, 0, 0, 0, 0, 0, 0] },
    { id: 4, name: "No phone after 10", icon: "moon", tint: "plum", streak: 8, days: [1, 1, 0, 0, 0, 0, 0] },
    { id: 5, name: "Drink water", icon: "droplet", tint: "honey", streak: 2, days: [1, 0, 0, 0, 0, 0, 0] },
  ]);
  const toggle = (id, d) => setHabits((hs) => hs.map((h) => h.id === id ? { ...h, days: h.days.map((v, i) => i === d ? (v ? 0 : 1) : v) } : h));
  const doneToday = habits.filter((h) => h.days[TODAY]).length;
  return (
    <React.Fragment>
      <Card variant="sunken">
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <ProgressRing value={doneToday} max={habits.length} size={78} color="green" label={`${doneToday}/${habits.length}`} sublabel="today" />
          <div><p className="m-row__title" style={{ fontSize: 16 }}>{doneToday === habits.length ? "All done!" : `${habits.length - doneToday} to go`}</p><p className="kit-muted" style={{ marginTop: 3 }}>Keep your streaks alive.</p></div>
        </div>
      </Card>
      <Card title="This week">
        {habits.map((h) => (
          <div className="m-habitrow" key={h.id}>
            <span className="m-ico" style={{ background: `var(--${h.tint}-100)`, color: `var(--${h.tint}-600)` }}><Icon name={h.icon} /></span>
            <div className="m-row__main" style={{ minWidth: 0 }}>
              <p className="m-row__title" style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{h.name}</p>
              <p className="m-row__sub" style={{ color: "var(--honey-600)" }}>🔥 {h.streak} days</p>
            </div>
            <div className="m-week">
              {h.days.map((on, di) => (
                <div key={di} className={"m-wd" + (on ? " on" : "") + (di === TODAY ? " today" : "")}
                  style={on ? { background: `var(--${h.tint}-600)` } : null} onClick={() => toggle(h.id, di)}>
                  <Icon name="check" />
                </div>
              ))}
            </div>
          </div>
        ))}
      </Card>
    </React.Fragment>
  );
}

function MobilePeople() {
  const Strength = ({ n }) => <span className="kit-strength">{[0, 1, 2, 3, 4].map((i) => <i key={i} className={i < n ? "on" : ""} />)}</span>;
  const reach = [
    { name: "Jordan Lee", why: "You usually catch up every 2 weeks", tint: "green" },
    { name: "Alex Mehta", why: "It's been 2 months", tint: "honey" },
  ];
  const people = [
    { name: "Priya Anand", rel: "Colleague", relColor: "sky", last: "Talked 2 days ago", strength: 4, tint: "sky" },
    { name: "Lila Rivera", rel: "Family", relColor: "plum", last: "Called 1 week ago", strength: 5, tint: "plum" },
    { name: "Jordan Lee", rel: "Friend", relColor: "green", last: "3 weeks ago", strength: 3, tint: "green" },
    { name: "Alex Mehta", rel: "Friend", relColor: "green", last: "2 months ago", over: true, strength: 2, tint: "honey" },
  ];
  return (
    <React.Fragment>
      <Card title="Reach out" action={<Badge color="honey" dot>2 due</Badge>}>
        <div className="kit-stack">
          {reach.map((r, i) => (
            <div className="kit-memory" key={i}>
              <div className="kit-memory__top"><Avatar name={r.name} tint={r.tint} size="sm" /><span className="kit-row__title" style={{ fontSize: 14 }}>{r.name}</span></div>
              <p style={{ margin: 0, fontSize: 13, color: "var(--text-muted)" }}>{r.why}</p>
              <Button variant="soft" size="sm" iconLeft={<Icon name="sparkles" />}>Draft a hello</Button>
            </div>
          ))}
        </div>
      </Card>
      <Card title="People" eyebrow="142 contacts">
        {people.map((p, i) => (
          <div className="kit-person" key={i}>
            <Avatar name={p.name} tint={p.tint} size="sm" />
            <div className="kit-person__main">
              <p className="kit-person__name" style={{ fontSize: 14 }}>{p.name}</p>
              <p className="kit-person__sub" style={p.over ? { color: "var(--clay-600)" } : null}>{p.last}</p>
            </div>
            <Strength n={p.strength} />
          </div>
        ))}
      </Card>
    </React.Fragment>
  );
}

function MobileEmail() {
  const emails = [
    { id: 1, from: "Priya Anand", time: "8:24am", cat: "Needs reply", unread: true,
      subject: "Lighthouse timeline — confirm the 30th?",
      summary: ["Confirm the June 30 ship date.", "Loop in design review by the 20th."],
      drafts: { Friendly: "Hi Priya,\n\nThe 30th works — let's lock it in. I'll schedule design review before the 20th.\n\nThanks!\nSam", Brief: "Hi Priya — 30th works. Design review before the 20th. — Sam" } },
    { id: 2, from: "Oak St. Realty", time: "Yesterday", cat: "Needs reply", unread: true,
      subject: "Lease renewal — by Jun 25",
      summary: ["Decision needed by Jun 25.", "Rent holds at $1,450 for 12 months."],
      drafts: { Friendly: "Hi,\n\nI'd like to renew for 12 months at the current rate. Send the paperwork whenever.\n\nBest,\nSam", Brief: "Hi — renewing 12 months at $1,450. Send papers. — Sam" } },
    { id: 3, from: "Vanguard", time: "Jun 5", cat: "FYI", unread: false,
      subject: "Your June statement is ready", summary: ["Statement available.", "Portfolio up 0.9%. No action."] },
  ];
  const [selId, setSelId] = React.useState(1);
  const [tone, setTone] = React.useState("Friendly");
  const sel = emails.find((e) => e.id === selId);
  return (
    <React.Fragment>
      <Card eyebrow="12 new · I triaged & cleared 8" title="Inbox" action={<Badge color="green" dot>4 need you</Badge>}>
        {emails.map((e) => (
          <div key={e.id} className={"kit-mail" + (e.id === selId ? " is-active" : "")} onClick={() => { setSelId(e.id); setTone("Friendly"); }}>
            <span className={"kit-mail__dot" + (e.unread ? "" : " read")} />
            <div className="kit-mail__main">
              <div className="kit-mail__top"><span className="kit-mail__from">{e.from}</span><span className="kit-mail__time">{e.time}</span></div>
              <p className="kit-mail__subj">{e.subject}</p>
            </div>
            <Badge color={e.cat === "FYI" ? "neutral" : "honey"}>{e.cat}</Badge>
          </div>
        ))}
      </Card>
      <Card eyebrow={sel.from} title={sel.subject}>
        <p className="sa-card__eyebrow" style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 9 }}><Icon name="sparkles" style={{ width: 13, height: 13 }} />AI summary</p>
        <div className="kit-bullets">{sel.summary.map((b, i) => <div className="kit-bullet" key={i}><Icon name="check" />{b}</div>)}</div>
      </Card>
      {sel.drafts ? (
        <Card title="Suggested reply" action={
          <div className="kit-cal__seg" style={{ marginLeft: 0 }}>{["Friendly", "Brief"].map((t) => <button key={t} className={tone === t ? "is-on" : ""} onClick={() => setTone(t)}>{t}</button>)}</div>
        }>
          <div className="kit-draft">{sel.drafts[tone]}</div>
          <div className="m-pillrow" style={{ marginTop: 12 }}>
            <Button variant="primary" fullWidth iconLeft={<Icon name="send" />}>Send</Button>
            <Button variant="secondary" iconLeft={<Icon name="pen-line" />}>Edit</Button>
          </div>
        </Card>
      ) : (
        <Card variant="sunken"><div className="kit-insight"><div className="kit-insight__icon"><Icon name="check-check" /></div><p>No reply needed — filed as <strong>FYI</strong>.</p></div></Card>
      )}
    </React.Fragment>
  );
}

Object.assign(window, { MoreScreen, MobileFitness, MobileHabits, MobilePeople, MobileEmail });
