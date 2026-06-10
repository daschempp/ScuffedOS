/* Scuffed OS — iPhone full-screen assistant chat */
function MobileAssistant({ onClose, onNavigate, onCreateTask }) {
  const [messages, setMessages] = React.useState([
    { id: 1, role: "ai", text: "Good morning, Sam. <strong>4 tasks</strong> today, a standup at 11:30, and you're $120 under budget. What can I do?" },
  ]);
  const [input, setInput] = React.useState("");
  const [typing, setTyping] = React.useState(false);
  const logRef = React.useRef(null);

  React.useEffect(() => { if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight; }, [messages, typing]);

  const send = (raw) => {
    const text = (raw != null ? raw : input).trim();
    if (!text) return;
    setMessages((m) => [...m, { id: Date.now(), role: "user", text }]);
    setInput("");
    setTyping(true);
    setTimeout(() => {
      const r = window.ScuffedAssistant.reply(text);
      if (r.action && r.action.makeTask && onCreateTask) onCreateTask(r.action.makeTask);
      setTyping(false);
      setMessages((m) => [...m, { id: Date.now() + 1, role: "ai", text: r.text, action: r.action }]);
    }, 800);
  };
  const goAction = (screen) => { if (screen && onNavigate) onNavigate(screen); onClose(); };
  const suggestions = ["Plan my day", "Add a task", "Spent on dining?", "Log breakfast"];

  return (
    <div className="m-chat">
      <div className="m-chat__head">
        <div className="m-chat__id"><img src="../../assets/logo-mark.svg" alt="" /></div>
        <div style={{ flex: 1 }}>
          <div className="m-chat__name">Scuffed Assistant</div>
          <div className="m-chat__status">Connected to your second brain</div>
        </div>
        <IconButton label="Close" size="sm" onClick={onClose}><Icon name="chevron-down" /></IconButton>
      </div>

      <div className="m-chat__log" ref={logRef}>
        {messages.map((m) => (
          <div key={m.id} className={"kit-msg kit-msg--" + m.role}>
            {m.role === "ai" && <span className="kit-msg__av"><Icon name="sparkles" /></span>}
            <div>
              <div className="kit-bubble" dangerouslySetInnerHTML={{ __html: m.text }} />
              {m.action && (
                <div className="kit-action">
                  <span className="kit-action__ico"><Icon name={m.action.icon} /></span>
                  <div className="kit-action__main">
                    <div className="kit-action__title"><Icon name="check" />{m.action.title}</div>
                    <div className="kit-action__meta">{m.action.meta}</div>
                  </div>
                  <span className="kit-action__cta" onClick={() => goAction(m.action.screen)}>{m.action.cta}</span>
                </div>
              )}
            </div>
          </div>
        ))}
        {typing && (
          <div className="kit-msg kit-msg--ai">
            <span className="kit-msg__av"><Icon name="sparkles" /></span>
            <div className="kit-bubble" style={{ padding: 0 }}><div className="kit-typing"><i /><i /><i /></div></div>
          </div>
        )}
      </div>

      <div className="m-chat__suggest">
        {suggestions.map((s) => <span key={s} className="kit-suggest" onClick={() => send(s)}>{s}</span>)}
      </div>

      <div className="m-composer">
        <div className="m-composer__box">
          <input value={input} placeholder="Ask or tell your assistant…"
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") send(); }} />
          <IconButton label="Voice" variant="ghost" size="sm"><Icon name="mic" /></IconButton>
        </div>
        <IconButton label="Send" variant="solid" onClick={() => send()}><Icon name="arrow-up" /></IconButton>
      </div>
    </div>
  );
}
window.MobileAssistant = MobileAssistant;
