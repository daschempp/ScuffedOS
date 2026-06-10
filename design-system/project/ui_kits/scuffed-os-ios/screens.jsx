/* Scuffed OS — iPhone screens */

function MobileHome({ tasks, onToggleTask, onOpenAssistant, onTab }) {
  const agenda = [
    { time: "09:00", title: "Deep work — Q3 plan", meta: "Focus block", active: true },
    { time: "11:30", title: "Design standup", meta: "Google Meet", active: true },
    { time: "13:00", title: "Lunch — log it", meta: "Assistant reminder", active: false },
  ];
  return (
    <div className="m-screen">
      <div className="m-head">
        <div className="m-eyebrow">Tuesday · June 8</div>
        <h1 className="m-title">Good morning, Sam</h1>
        <p className="m-sub">4 things need you today</p>
      </div>

      <div className="m-ask" onClick={onOpenAssistant}>
        <span className="m-ask__ico"><Icon name="sparkles" /></span>
        <div className="m-ask__main"><b>Ask your assistant</b><span>Tasks, money, meals — or just talk</span></div>
        <Icon name="arrow-right" />
      </div>

      <Card title="Today" action={<button className="m-link" onClick={() => onTab("tasks")}>Calendar</button>}>
        <div className="m-agenda">
          {agenda.map((a, i) => (
            <div key={i} className={"m-agenda__item" + (a.active ? "" : " m-agenda__item--muted")}>
              <div className="m-agenda__time">{a.time}</div>
              <div className="m-agenda__body">
                <p className="m-agenda__title">{a.title}</p>
                <p className="m-agenda__meta">{a.meta}</p>
              </div>
            </div>
          ))}
        </div>
      </Card>

      <Card title="Tasks" action={<span className="kit-muted">{tasks.filter((t) => !t.done).length} left</span>}>
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          {tasks.slice(0, 4).map((t) => (
            <div key={t.id} style={{ padding: "6px 0" }}>
              <Checkbox checked={t.done} strikeWhenChecked label={t.label} onChange={() => onToggleTask(t.id)} />
            </div>
          ))}
        </div>
      </Card>

      <Card variant="sunken" title="Nutrition" action={<button className="m-link" onClick={() => onTab("nutrition")}>Details</button>}>
        <div className="m-rings">
          <div className="m-ring"><ProgressRing value={1690} max={2100} size={74} color="green" label="1690" sublabel="kcal" /><span className="m-ring__lab">Calories</span></div>
          <div className="m-ring"><ProgressRing value={114} max={160} size={74} color="clay" label="114g" sublabel="protein" /><span className="m-ring__lab">Protein</span></div>
          <div className="m-ring"><ProgressRing value={5} max={8} size={74} color="sky" label="5/8" sublabel="cups" /><span className="m-ring__lab">Water</span></div>
        </div>
      </Card>
    </div>
  );
}

function MobileTasks({ tasks, onToggleTask }) {
  const groups = ["Today", "Upcoming"];
  const byGroup = (g) => tasks.filter((t) => (t.group || "Today") === g);
  return (
    <div className="m-screen">
      <div className="m-head">
        <h1 className="m-title">Tasks</h1>
        <p className="m-sub">{tasks.filter((t) => !t.done).length} open · 2 done today</p>
      </div>

      <div className="m-ask" style={{ background: "var(--surface-sunken)", color: "var(--text-faint)", boxShadow: "none" }}>
        <Icon name="plus" />
        <div className="m-ask__main" style={{ color: "var(--text-muted)" }}><b style={{ color: "var(--text-strong)" }}>Add a task</b><span style={{ color: "var(--text-faint)" }}>or hold the mic to say it</span></div>
        <Badge color="green" icon={<Icon name="mic" />}>Voice</Badge>
      </div>

      {groups.map((g) => byGroup(g).length > 0 && (
        <Card key={g} title={g} action={<span className="kit-muted">{byGroup(g).filter((t) => !t.done).length} open</span>}>
          {byGroup(g).map((t) => (
            <div className="m-row" key={t.id}>
              <span onClick={(e) => e.stopPropagation()} style={{ display: "inline-flex" }}>
                <Checkbox checked={t.done} onChange={() => onToggleTask(t.id)} />
              </span>
              <div className="m-row__main">
                <p className="m-row__title" style={t.done ? { color: "var(--text-faint)", textDecoration: "line-through" } : null}>{t.label}</p>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 3 }}>
                  <span className="m-cat" style={{ borderRadius: 999, width: 8, height: 8, background: t.prio === "high" ? "var(--clay-600)" : t.prio === "med" ? "var(--honey-600)" : "var(--green-500)" }} />
                  {t.due && <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: t.late ? "var(--clay-600)" : "var(--text-muted)" }}>{t.due}</span>}
                  {t.list && <Badge color={t.listColor || "neutral"}>{t.list}</Badge>}
                </div>
              </div>
            </div>
          ))}
        </Card>
      ))}
    </div>
  );
}

function MobileFinance() {
  const [period, setPeriod] = React.useState("Month");
  const cats = [
    { name: "Groceries", spent: 320, budget: 400, color: "clay" },
    { name: "Rent & bills", spent: 1450, budget: 1450, color: "honey" },
    { name: "Dining out", spent: 186, budget: 250, color: "plum" },
    { name: "Savings", spent: 600, budget: 600, color: "green" },
  ];
  const txns = [
    { title: "Whole Foods", sub: "Groceries · today", amt: "-$64.20", cat: "var(--clay-600)" },
    { title: "Salary", sub: "Acme Inc · Jun 1", amt: "+$3,200", cat: "var(--green-600)", pos: true },
    { title: "Spotify", sub: "Subscriptions", amt: "-$11.99", cat: "var(--plum-600)" },
  ];
  return (
    <div className="m-screen">
      <div className="m-head"><h1 className="m-title">Finance</h1></div>
      <Card>
        <div className="m-eyebrow">Balance</div>
        <div className="m-bigamt">$4,820<small>.50</small></div>
        <div style={{ marginTop: 12 }}>
          <ProgressBar label="June spending" meta="$1,840 / $2,400" value={1840} max={2400} color="clay" />
        </div>
      </Card>

      <div className="m-seg">
        {["Week", "Month", "Year"].map((p) => (
          <button key={p} className={period === p ? "is-on" : ""} onClick={() => setPeriod(p)}>{p}</button>
        ))}
      </div>

      <Card title="Budgets">
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          {cats.map((c, i) => (
            <ProgressBar key={i} label={c.name} value={c.spent} max={c.budget} color={c.color} meta={`$${c.spent} / $${c.budget}`} />
          ))}
        </div>
      </Card>

      <Card title="Recent">
        {txns.map((t, i) => (
          <div className="m-row" key={i}>
            <span className="m-cat" style={{ background: t.cat }} />
            <div className="m-row__main"><p className="m-row__title">{t.title}</p><p className="m-row__sub">{t.sub}</p></div>
            <span className={"m-row__amt" + (t.pos ? " m-amt--pos" : "")}>{t.amt}</span>
          </div>
        ))}
      </Card>
    </div>
  );
}

function MobileNutrition() {
  const meals = [
    { ico: "egg", tint: "honey", name: "Greek yogurt & berries", time: "Breakfast", kcal: 320 },
    { ico: "sandwich", tint: "clay", name: "Chicken & avocado wrap", time: "Lunch", kcal: 540 },
    { ico: "apple", tint: "green", name: "Apple + almonds", time: "Snack", kcal: 210 },
  ];
  return (
    <div className="m-screen">
      <div className="m-head"><h1 className="m-title">Nutrition</h1></div>
      <Card style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 6 }}>
        <ProgressRing value={1690} max={2100} size={150} thickness={14} color="green" label="1690" sublabel="of 2100 kcal" />
        <p className="kit-muted" style={{ margin: 0 }}>410 calories left today</p>
      </Card>

      <Card title="Macros">
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <ProgressBar label="Protein" value={114} max={160} color="clay" meta="114 / 160g" />
          <ProgressBar label="Carbs" value={148} max={210} color="honey" meta="148 / 210g" />
          <ProgressBar label="Fat" value={52} max={70} color="sky" meta="52 / 70g" />
        </div>
      </Card>

      <Card title="Meals" action={<Badge color="green" icon={<Icon name="plus" />}>Log</Badge>}>
        {meals.map((m, i) => (
          <div className="m-row" key={i}>
            <span className="m-ico" style={{ background: `var(--${m.tint}-100)`, color: `var(--${m.tint}-600)` }}><Icon name={m.ico} /></span>
            <div className="m-row__main"><p className="m-row__title">{m.name}</p><p className="m-row__sub">{m.time}</p></div>
            <span className="m-row__amt">{m.kcal}<span style={{ color: "var(--text-faint)", fontSize: 11 }}> kcal</span></span>
          </div>
        ))}
      </Card>
    </div>
  );
}

Object.assign(window, { MobileHome, MobileTasks, MobileFinance, MobileNutrition });
