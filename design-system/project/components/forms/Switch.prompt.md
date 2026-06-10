Pill toggle for settings and on/off preferences.

```jsx
<Switch defaultChecked label="Telegram voice notes" />
<Switch checked={muted} onChange={e => setMuted(e.target.checked)} />
```

Controlled via `checked`/`onChange` or uncontrolled via `defaultChecked`. Track turns forest-green when on; thumb slides with a soft ease.
