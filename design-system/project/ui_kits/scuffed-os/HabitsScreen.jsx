/* Scuffed OS — Habit tracker */
function HabitsScreen() {
  const DOW = ["M", "T", "W", "T", "F", "S", "S"];
  const TODAY = 1; // Tuesday
  const [habits, setHabits] = React.useState([
    { id: 1, name: "Meditate", icon: "flower-2", tint: "green", streak: 12, days: [true, true, false, false, false, false, false] },
    { id: 2, name: "Read 30 min", icon: "book-open", tint: "sky", streak: 5, days: [true, true, false, false, false, false, false] },
    { id: 3, name: "Workout", icon: "dumbbell", tint: "clay", streak: 3, days: [true, false, false, false, false, false, false] },
    { id: 4, name: "No phone after 10", icon: "moon", tint: "plum", streak: 8, days: [true, true, false, false, false, false, false] },
    { id: 5, name: "Drink 8 cups water", icon: "droplet", tint: "honey", streak: 2, days: [true, false, false, false, false, false, false] },
  ]);
  const toggle = (hid, day) => setHabits((hs) => hs.map((h) => h.id === hid ? { ...h, days: h.days.map((d, i) => i === day ? !d : d) } : h));

  const doneToday = habits.filter((h) => h.days[TODAY]).length;
  const bestStreak = Math.max.apply(null, habits.map((h) => h.streak));

  return (
    <div className="kit-grid" style={{ gridTemplateColumns: "1.5fr 1fr" }}>
      <Card title="This week" eyebrow="Tap to mark complete" action={<Button variant="soft" size="sm" iconLeft={<Icon name="plus" />}>New habit</Button>}>
        <div className="kit-habits">
          <div />
          {DOW.map((d, i) => <div className="kit-habits__dow" key={i} style={i === TODAY ? { color: "var(--accent-text)" } : null}>{d}</div>)}
          {habits.map((h) => (
            <React.Fragment key={h.id}>
              <div className="kit-habits__name">
                <span className="kit-habits__ico" style={{ background: `var(--${h.tint}-100)`, color: `var(--${h.tint}-600)` }}><Icon name={h.icon} /></span>
                <div style={{ minWidth: 0 }}>
                  <div className="kit-habits__title">{h.name}</div>
                  <div className="kit-habits__streak"><Icon name="flame" />{h.streak} day streak</div>
                </div>
              </div>
              {h.days.map((done, di) => (
                <div key={di}
                  className={"kit-hcell" + (done ? " is-done" : "") + (di === TODAY ? " is-today" : "")}
                  style={done ? { background: `var(--${h.tint}-600)` } : null}
                  onClick={() => toggle(h.id, di)}>
                  <Icon name="check" />
                </div>
              ))}
            </React.Fragment>
          ))}
        </div>
      </Card>

      <div className="kit-col">
        <Card title="Today" variant="sunken">
          <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
            <ProgressRing value={doneToday} max={habits.length} size={92} thickness={11} color="green" label={`${doneToday}/${habits.length}`} sublabel="done" />
            <div>
              <p className="kit-row__title" style={{ fontSize: "var(--text-md)" }}>{doneToday === habits.length ? "All done — nice!" : `${habits.length - doneToday} to go`}</p>
              <p className="kit-muted" style={{ marginTop: 4 }}>Keep your streaks alive before midnight.</p>
            </div>
          </div>
        </Card>

        <Card title="Streaks">
          <div className="kit-spread" style={{ marginBottom: 14 }}>
            <Stat label="Best streak" value={bestStreak} unit="days" icon={<Icon name="flame" />} />
            <Stat label="This week" value="68%" trend="up" delta="+9%" />
          </div>
          <div className="kit-insight">
            <div className="kit-insight__icon"><Icon name="sparkles" /></div>
            <p>You're most consistent in the <strong>morning</strong>. Want me to stack “Read” right after “Meditate”?</p>
          </div>
        </Card>
      </div>
    </div>
  );
}
window.HabitsScreen = HabitsScreen;
