/* Scuffed OS — App shell + state */
const SCREENS = {
  home: { title: "Good morning, Sam", sub: "Tuesday, June 9 · 4 things need you today" },
  nutrition: { title: "Nutrition", sub: "1,690 of 2,100 kcal · 410 to go" },
  fitness: { title: "Fitness", sub: "82% recovered · ready for a hard session" },
  finance: { title: "Finance", sub: "$129,050 net worth · on budget for June" },
  memory: { title: "Second Brain", sub: "142 memories · learning from your notes" },
  calendar: { title: "Calendar", sub: "3 events today" },
  tasks: { title: "Tasks", sub: "5 open · 2 done today" },
  habits: { title: "Habits", sub: "2 of 5 done · keep your streaks alive" },
  people: { title: "People", sub: "142 contacts · 2 to reach out to" },
  email: { title: "Email", sub: "12 new · 4 need a reply" },
  settings: { title: "Settings", sub: "Preferences & connections" },
};

function Placeholder({ icon, name }) {
  return (
    <Card variant="flat" style={{ textAlign: "center", padding: "56px 24px" }}>
      <div style={{ display: "inline-flex", width: 56, height: 56, borderRadius: "var(--radius-lg)", background: "var(--accent-soft)", color: "var(--accent-text)", alignItems: "center", justifyContent: "center", marginBottom: 14 }}>
        <Icon name={icon} />
      </div>
      <h3 style={{ fontFamily: "var(--font-display)", fontSize: "var(--text-xl)", color: "var(--text-strong)", margin: "0 0 6px" }}>{name}</h3>
      <p className="kit-muted" style={{ maxWidth: 360, margin: "0 auto" }}>This surface isn't part of the current design-system sample. The Home, Nutrition, Finance and Second Brain screens are fully built out.</p>
    </Card>
  );
}

function App() {
  const [screen, setScreen] = React.useState("home");
  const [recording, setRecording] = React.useState(false);
  const [tasks, setTasks] = React.useState([
    { id: 1, label: "Pay rent", done: true },
    { id: 2, label: "Reply to Priya about Lighthouse", done: false },
    { id: 3, label: "Log lunch", done: false },
    { id: 4, label: "Book dentist follow-up", done: false },
    { id: 5, label: "Move $120 to savings", done: false },
  ]);
  const voiceNotes = [
    { text: "“Remind me to call mom about the ceramics class”", time: "8:10am", len: "0:06", done: true },
    { text: "“Lighthouse deadline moved to the 30th”", time: "Yesterday", len: "0:11", done: true },
    { text: "“Cut dining out to twice a week”", time: "Yesterday", len: "0:04", done: true },
  ];
  const [assistantOpen, setAssistantOpen] = React.useState(false);
  const toggleTask = (id) => setTasks((ts) => ts.map((t) => t.id === id ? { ...t, done: !t.done } : t));
  const addTask = (label) => setTasks((ts) => [{ id: Date.now(), label, done: false }, ...ts]);

  const meta = SCREENS[screen] || SCREENS.home;

  let body;
  if (screen === "home") body = <DashboardScreen tasks={tasks} onToggleTask={toggleTask} voiceNotes={voiceNotes} />;
  else if (screen === "nutrition") body = <NutritionScreen />;
  else if (screen === "finance") body = <FinanceScreen />;
  else if (screen === "memory") body = <MemoryScreen voiceNotes={voiceNotes} />;
  else if (screen === "calendar") body = <CalendarScreen />;
  else if (screen === "tasks") body = <TasksScreen />;
  else if (screen === "fitness") body = <FitnessScreen />;
  else if (screen === "habits") body = <HabitsScreen />;
  else if (screen === "people") body = <CRMScreen />;
  else if (screen === "email") body = <EmailScreen />;
  else body = <Placeholder icon={{ settings: "settings" }[screen] || "sparkles"} name={meta.title} />;

  return (
    <div className="kit">
      <Sidebar active={screen} onNavigate={setScreen} />
      <main className="kit-main">
        <TopBar title={meta.title} subtitle={meta.sub} recording={recording} onToggleRecord={() => setRecording((r) => !r)} />
        <div className="kit-page">
          {recording && (
            <div className="kit-voice" style={{ marginBottom: "var(--gutter)" }}>
              <span className="kit-insight__icon" style={{ background: "var(--green-600)", color: "#fff" }}><Icon name="mic" /></span>
              <div className="kit-voice__wave">{Array.from({ length: 30 }).map((_, i) => <i key={i} style={{ height: 6 + (i % 6) * 3, animationDelay: (i * 0.04) + "s" }} />)}</div>
              <div className="kit-voice__label"><b>Listening…</b>Speak — I'll file it into your second brain</div>
              <Button variant="secondary" size="sm" onClick={() => setRecording(false)}>Done</Button>
            </div>
          )}
          {body}
        </div>
      </main>

      {!assistantOpen && (
        <button className="kit-fab" onClick={() => setAssistantOpen(true)}>
          <span className="kit-fab__pulse" />
          <Icon name="sparkles" />Assistant
        </button>
      )}
      {assistantOpen && (
        <ChatPanel onClose={() => setAssistantOpen(false)} onNavigate={setScreen} onCreateTask={addTask} />
      )}
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
