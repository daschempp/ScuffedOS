/* Scuffed OS — iPhone app shell */
function MobileApp() {
  const LIST_COLOR = { Work: "sky", Health: "green", Finance: "honey", Personal: "plum" };
  const [tab, setTab] = React.useState("home");
  const [pushed, setPushed] = React.useState(null);
  const [chatOpen, setChatOpen] = React.useState(false);
  const [voiceOpen, setVoiceOpen] = React.useState(false);
  const [tasks, setTasks] = React.useState([
    { id: 1, label: "Reply to Priya about Lighthouse", group: "Today", due: "11:00am", prio: "high", list: "Work", done: false },
    { id: 2, label: "Log lunch", group: "Today", due: "1:00pm", prio: "low", list: "Health", done: false },
    { id: 3, label: "Book dentist follow-up", group: "Today", due: "Overdue", late: true, prio: "med", list: "Health", done: false },
    { id: 4, label: "Move $120 to savings", group: "Today", due: "Today", prio: "med", list: "Finance", done: false },
    { id: 5, label: "Pay rent", group: "Today", due: "Done", prio: "high", list: "Finance", done: true },
    { id: 6, label: "Draft Q3 planning doc", group: "Upcoming", due: "Tomorrow", prio: "high", list: "Work", done: false },
    { id: 7, label: "Order mom's birthday gift", group: "Upcoming", due: "Jun 12", prio: "med", list: "Personal", done: false },
  ].map((t) => ({ ...t, listColor: LIST_COLOR[t.list] })));

  const toggleTask = (id) => setTasks((ts) => ts.map((t) => t.id === id ? { ...t, done: !t.done } : t));
  const addTask = (label) => setTasks((ts) => [{ id: Date.now(), label, done: false, group: "Today", due: "Today", prio: "med", list: "Personal", listColor: "plum" }, ...ts]);

  const TABS = [
    { id: "home", label: "Home", icon: "house" },
    { id: "tasks", label: "Tasks", icon: "circle-check-big" },
    { id: "finance", label: "Money", icon: "wallet" },
    { id: "more", label: "More", icon: "layout-grid" },
  ];

  const PUSH = {
    nutrition: { title: "Nutrition", el: <MobileNutrition /> },
    fitness: { title: "Fitness", el: <MobileFitness /> },
    habits: { title: "Habits", el: <MobileHabits /> },
    people: { title: "People", el: <MobilePeople /> },
    email: { title: "Email", el: <MobileEmail /> },
    memory: { title: "Second Brain", el: (
      <Card title="Recent memories" eyebrow="142 stored">
        <div className="kit-stack">
          {[["Mom's birthday is March 14", "voice note", "plum"], ["Prefer morning workouts", "learned", "green"], ["Lighthouse deadline moved to Jun 30", "telegram", "sky"]].map((m, i) => (
            <div className="kit-memory" key={i}>
              <div className="kit-memory__top"><span className="kit-cat" style={{ background: `var(--${m[2]}-600)`, borderRadius: 999 }} /><Badge color={m[1] === "voice note" ? "sky" : m[1] === "telegram" ? "green" : "plum"}>{m[1]}</Badge></div>
              <p style={{ margin: 0, fontSize: 14 }}>{m[0]}</p>
            </div>
          ))}
        </div>
      </Card>
    ) },
  };

  let screen;
  if (tab === "home") screen = <MobileHome tasks={tasks} onToggleTask={toggleTask} onOpenAssistant={() => setChatOpen(true)} onTab={setTab} />;
  else if (tab === "tasks") screen = <MobileTasks tasks={tasks} onToggleTask={toggleTask} />;
  else if (tab === "finance") screen = <MobileFinance />;
  else screen = <MoreScreen onOpen={setPushed} />;

  const navFromAction = (s) => {
    if (["home", "tasks", "finance"].includes(s)) setTab(s);
    else if (PUSH[s]) setPushed(s);
    else if (s === "calendar") setTab("home");
  };

  return (
    <IOSDevice>
      <div className="m-app">
        <div className="m-statusspace" />
        <div className="m-scroll">{screen}</div>

        <div className="m-tabbar">
          {TABS.slice(0, 2).map((t) => (
            <button key={t.id} className={"m-tab" + (tab === t.id ? " is-on" : "")} onClick={() => setTab(t.id)}>
              <Icon name={t.icon} /><span>{t.label}</span>
            </button>
          ))}
          <div className="m-tab--center">
            <div className="m-mic" onClick={() => setVoiceOpen(true)}><Icon name="mic" /></div>
          </div>
          {TABS.slice(2).map((t) => (
            <button key={t.id} className={"m-tab" + (tab === t.id ? " is-on" : "")} onClick={() => setTab(t.id)}>
              <Icon name={t.icon} /><span>{t.label}</span>
            </button>
          ))}
        </div>

        {voiceOpen && <VoiceSheet onClose={() => setVoiceOpen(false)} onCapture={addTask} />}
        {chatOpen && <MobileAssistant onClose={() => setChatOpen(false)} onNavigate={navFromAction} onCreateTask={addTask} />}
        {pushed && (
          <div className="m-push">
            <div className="m-push__head">
              <IconButton label="Back" size="sm" onClick={() => setPushed(null)}><Icon name="chevron-left" /></IconButton>
              <span className="m-push__title">{PUSH[pushed].title}</span>
            </div>
            <div className="m-push__body">{PUSH[pushed].el}</div>
          </div>
        )}
      </div>
    </IOSDevice>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<MobileApp />);
