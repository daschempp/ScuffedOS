/* Scuffed OS — iPhone voice-capture bottom sheet (the "send from anywhere" feature) */
function VoiceSheet({ onClose, onCapture }) {
  const phrase = "Remind me to call the dentist tomorrow";
  const [done, setDone] = React.useState(false);
  const [shown, setShown] = React.useState("");

  React.useEffect(() => {
    let i = 0;
    const id = setInterval(() => {
      i += 1;
      setShown(phrase.slice(0, i));
      if (i >= phrase.length) clearInterval(id);
    }, 45);
    return () => clearInterval(id);
  }, []);

  const send = () => {
    setDone(true);
    if (onCapture) onCapture(window.ScuffedAssistant.cleanTitle(phrase));
    setTimeout(onClose, 850);
  };

  return (
    <React.Fragment>
      <div className="m-scrim" onClick={onClose} />
      <div className="m-sheet">
        <div className="m-grip" />
        {done ? (
          <div className="m-voice">
            <div className="m-voice__mic" style={{ background: "var(--green-600)" }}><Icon name="check" /></div>
            <h3>Sent to Scuffed</h3>
            <p>I've added it to your tasks and set a reminder.</p>
          </div>
        ) : (
          <div className="m-voice">
            <div className="m-voice__mic"><Icon name="mic" /></div>
            <div className="m-voice__wave">
              {Array.from({ length: 18 }).map((_, i) => <i key={i} style={{ height: 7 + (i % 6) * 4, animationDelay: (i * 0.05) + "s" }} />)}
            </div>
            <h3>Listening…</h3>
            <p style={{ minHeight: 40 }}>"{shown}<span style={{ opacity: 0.4 }}>|</span>"</p>
            <div className="m-pillrow" style={{ width: "100%" }}>
              <Button variant="secondary" fullWidth onClick={onClose}>Cancel</Button>
              <Button variant="primary" fullWidth iconLeft={<Icon name="arrow-up" />} onClick={send}>Send to Scuffed</Button>
            </div>
            <p style={{ fontSize: 12, color: "var(--text-faint)" }}>Also works from Telegram, anywhere you are</p>
          </div>
        )}
      </div>
    </React.Fragment>
  );
}
window.VoiceSheet = VoiceSheet;
