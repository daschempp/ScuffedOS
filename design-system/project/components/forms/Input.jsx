import React from "react";

let _injected = false;
function ensureStyles() {
  if (_injected || typeof document === "undefined") return;
  _injected = true;
  const css = `
  .sa-field { display: flex; flex-direction: column; gap: 6px; font-family: var(--font-sans); }
  .sa-field__label { font-size: var(--text-sm); font-weight: 600; color: var(--text-strong); }
  .sa-field__hint { font-size: var(--text-xs); color: var(--text-muted); }
  .sa-input-wrap { position: relative; display: flex; align-items: center; }
  .sa-input-wrap__icon { position: absolute; left: 13px; display: inline-flex; color: var(--text-faint); pointer-events: none; }
  .sa-input-wrap__icon svg { width: 17px; height: 17px; }
  .sa-input {
    font-family: var(--font-sans);
    font-size: var(--text-base);
    color: var(--text-strong);
    width: 100%;
    box-sizing: border-box;
    background: var(--surface-raised);
    border: 1px solid var(--border-soft);
    border-radius: var(--radius-sm);
    padding: 10px 13px;
    transition: border-color var(--dur-fast) var(--ease-out), box-shadow var(--dur-fast) var(--ease-out);
    box-shadow: var(--shadow-inset);
  }
  .sa-input::placeholder { color: var(--text-faint); }
  .sa-input:hover { border-color: var(--border-strong); }
  .sa-input:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px var(--focus-ring); }
  .sa-input--has-icon { padding-left: 38px; }
  .sa-input--error { border-color: var(--danger); }
  .sa-input--error:focus { box-shadow: 0 0 0 3px color-mix(in srgb, var(--danger) 30%, transparent); }
  .sa-input:disabled { background: var(--surface-sunken); color: var(--text-disabled); cursor: not-allowed; }
  `;
  const el = document.createElement("style");
  el.setAttribute("data-sa", "input");
  el.textContent = css;
  document.head.appendChild(el);
}

export function Input({
  label,
  hint,
  error,
  icon = null,
  id,
  className = "",
  ...rest
}) {
  ensureStyles();
  const fid = id || (label ? "sa-" + label.toLowerCase().replace(/\s+/g, "-") : undefined);
  return (
    <div className="sa-field">
      {label && <label className="sa-field__label" htmlFor={fid}>{label}</label>}
      <div className="sa-input-wrap">
        {icon && <span className="sa-input-wrap__icon">{icon}</span>}
        <input
          id={fid}
          className={[
            "sa-input",
            icon ? "sa-input--has-icon" : "",
            error ? "sa-input--error" : "",
            className,
          ].filter(Boolean).join(" ")}
          {...rest}
        />
      </div>
      {error ? (
        <span className="sa-field__hint" style={{ color: "var(--danger)" }}>{error}</span>
      ) : hint ? (
        <span className="sa-field__hint">{hint}</span>
      ) : null}
    </div>
  );
}
