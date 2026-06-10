/* Scuffed OS — Task manager */
function TasksScreen() {
  const LIST_COLOR = { Work: "sky", Health: "green", Finance: "honey", Personal: "plum" };
  const [tasks, setTasks] = React.useState([
    { id: 1, label: "Reply to Priya about Lighthouse", group: "Today", due: "11:00am", deadline: "2026-06-08", prio: "high", list: "Work",
      description: "She asked about the moved deadline — confirm the 30th works and loop in the design review.",
      subtasks: [{ id: 11, label: "Check calendar for the 30th", done: true }, { id: 12, label: "Draft reply", done: false }],
      reminders: ["1 hour before"], files: [{ id: 101, name: "lighthouse-brief.pdf", size: 248000 }] },
    { id: 2, label: "Log lunch", group: "Today", due: "1:00pm", deadline: "2026-06-08", prio: "low", list: "Health",
      description: "", subtasks: [], labels: ["nutrition"], reminders: ["1:00pm"] },
    { id: 3, label: "Book dentist follow-up", group: "Today", due: "Overdue", late: true, deadline: "2026-06-06", prio: "med", list: "Health",
      description: "Call Oak Street Dental — ask for an early-morning slot.", subtasks: [], labels: [], reminders: [] },
    { id: 4, label: "Move $120 to savings", group: "Today", due: "Today", deadline: "2026-06-08", prio: "med", list: "Finance",
      description: "Roll over the dining-budget surplus.", subtasks: [], labels: ["savings"], reminders: [] },
    { id: 5, label: "Pay rent", group: "Today", due: "Done 8:02am", deadline: "2026-06-08", prio: "high", list: "Finance", done: true,
      description: "", subtasks: [], labels: [], reminders: [] },
    { id: 6, label: "Draft Q3 planning doc", group: "Upcoming", due: "Tomorrow", deadline: "2026-06-09", prio: "high", list: "Work",
      description: "Outline goals, headcount, and the roadmap themes.",
      subtasks: [{ id: 61, label: "Goals", done: false }, { id: 62, label: "Roadmap themes", done: false }],
      labels: ["planning"], reminders: [] },
    { id: 7, label: "Order mom's birthday gift", group: "Upcoming", due: "Jun 12", deadline: "2026-06-12", prio: "med", list: "Personal",
      description: "The ceramics class she mentioned in a voice note.", subtasks: [], reminders: ["Jun 11, 9:00am"],
      files: [{ id: 701, name: "ceramics-studio.png", size: 1340000 }, { id: 702, name: "gift-ideas.txt", size: 1200 }] },
    { id: 8, label: "Meal prep for the week", group: "Upcoming", due: "Sun", deadline: "2026-06-14", prio: "low", list: "Health",
      description: "", subtasks: [], labels: [], reminders: [] },
    { id: 9, label: "Renew gym membership", group: "Someday", prio: "low", list: "Health",
      description: "", subtasks: [], labels: [], reminders: [] },
    { id: 10, label: "Read 'Deep Work'", group: "Someday", prio: "low", list: "Personal",
      description: "", subtasks: [], labels: ["reading"], reminders: [] },
  ].map((t) => ({ done: false, subtasks: [], reminders: [], files: [], description: "", ...t, listColor: LIST_COLOR[t.list] })));

  const [openId, setOpenId] = React.useState(null);
  const toggle = (id) => setTasks((ts) => ts.map((t) => t.id === id ? { ...t, done: !t.done } : t));
  const update = (id, patch) => setTasks((ts) => ts.map((t) => t.id === id ? { ...t, ...patch } : t));

  const lists = [
    { name: "Work", color: "sky" }, { name: "Health", color: "green" },
    { name: "Finance", color: "honey" }, { name: "Personal", color: "plum" },
  ];
  const groups = ["Today", "Upcoming", "Someday"];
  const openCount = tasks.filter((t) => !t.done).length;
  const doneToday = tasks.filter((t) => t.done).length;
  const openTask = tasks.find((t) => t.id === openId);

  const TaskRow = (t) => {
    const subs = t.subtasks || [];
    const subsDone = subs.filter((s) => s.done).length;
    return (
      <div className={"kit-task" + (t.done ? " kit-task--done" : "")} key={t.id} onClick={() => setOpenId(t.id)}>
        <span onClick={(e) => e.stopPropagation()} style={{ display: "inline-flex" }}>
          <Checkbox checked={t.done} onChange={() => toggle(t.id)} />
        </span>
        <div className="kit-task__main">
          <p className="kit-task__title">{t.label}</p>
          <div className="kit-task__meta">
            <span className="kit-prio" style={{ background: t.prio === "high" ? "var(--clay-600)" : t.prio === "med" ? "var(--honey-600)" : "var(--green-500)" }} />
            {t.due && <span className={"kit-task__due" + (t.late ? " is-late" : "")}><Icon name={t.late ? "alarm-clock" : "clock"} />{t.due}</span>}
            <Badge color={t.listColor || "neutral"}>{t.list}</Badge>
            {subs.length > 0 && <span className="kit-task__due"><Icon name="list-checks" />{subsDone}/{subs.length}</span>}
            {(t.files || []).length > 0 && <span className="kit-task__due"><Icon name="paperclip" />{t.files.length}</span>}
          </div>
        </div>
        <span className="kit-task__chev"><Icon name="chevron-right" /></span>
      </div>
    );
  };

  return (
    <React.Fragment>
      <div className="kit-grid" style={{ gridTemplateColumns: "1fr 280px" }}>
        <div className="kit-col">
          <div className="kit-quickadd">
            <Icon name="plus" />
            <input placeholder="Add a task — or say it as a voice note…" />
            <Badge color="green" icon={<Icon name="mic" />}>Voice</Badge>
          </div>

          {groups.map((g) => {
            const rows = tasks.filter((t) => t.group === g);
            if (!rows.length) return null;
            return (
              <Card key={g} title={g} action={<span className="kit-muted">{rows.filter((t) => !t.done).length} open</span>}>
                <div className="kit-tasklist">{rows.map(TaskRow)}</div>
              </Card>
            );
          })}
        </div>

        <div className="kit-col">
          <Card title="Progress" variant="sunken">
            <div className="kit-spread" style={{ marginBottom: 14 }}>
              <Stat label="Open" value={openCount} />
              <Stat label="Done today" value={doneToday} trend="up" delta="+2" />
            </div>
            <ProgressBar label="Today" value={doneToday} max={doneToday + tasks.filter((t) => t.group === "Today" && !t.done).length} color="green" meta={`${doneToday} done`} />
          </Card>

          <Card title="Lists">
            <div className="kit-stack" style={{ gap: 0 }}>
              {lists.map((l) => (
                <div className="kit-listrow" key={l.name}>
                  <span className="kit-listrow__dot" style={{ background: `var(--${l.color}-600)` }} />
                  <span style={{ fontSize: "var(--text-base)", fontWeight: 600, color: "var(--text-strong)" }}>{l.name}</span>
                  <span className="kit-listrow__count">{tasks.filter((t) => t.list === l.name && !t.done).length}</span>
                </div>
              ))}
            </div>
            <div className="kit-divider" style={{ margin: "10px 0" }} />
            <Button variant="ghost" size="sm" iconLeft={<Icon name="plus" />}>New list</Button>
          </Card>

          <Card title="Assistant" eyebrow="Suggestion">
            <div className="kit-insight">
              <div className="kit-insight__icon"><Icon name="sparkles" /></div>
              <p>3 tasks are <strong>overdue or due today</strong>. Want me to reschedule the rest to this evening?</p>
            </div>
            <div className="kit-inline" style={{ marginTop: 12 }}>
              <Button variant="soft" size="sm">Reschedule</Button>
              <Button variant="ghost" size="sm">No thanks</Button>
            </div>
          </Card>
        </div>
      </div>

      {openTask && <TaskDetail task={openTask} onUpdate={update} onClose={() => setOpenId(null)} />}
    </React.Fragment>
  );
}
window.TasksScreen = TasksScreen;
