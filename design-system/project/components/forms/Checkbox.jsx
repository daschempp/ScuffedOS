import React from "react";

let _injected = false;
function ensureStyles() {
  if (_injected || typeof document === "undefined") return;
  _injected = true;
  const css = `
  .sa-check { display: inline-flex; align-items: center; gap: 10px; cursor: pointer; font-family: var(--font-sans); font-size: var(--text-base); color: var(--text-strong); -webkit-tap-highlight-color: transparent; }
  .sa-check input { position: absolute; opacity: 0; pointer-events: none; }
  .sa-check__box {
    width: 20px; height: 20px; border-radius: 6px; flex: none;
    background: var(--surface-raised);
    border: 1.5px solid var(--border-strong);
    box-shadow: var(--shadow-inset);
    display: inline-flex; align-items: center; justify-content: center;
    color: #fff;
    transition: background var(--dur-fast) var(--ease-out), border-color var(--dur-fast) var(--ease-out);
  }
  .sa-check__box svg { width: 13px; height: 13px; opacity: 0; transform: scale(0.6); transition: opacity var(--dur-fast) var(--ease-out), transform var(--dur-fast) var(--ease-soft); }
  .sa-check input:checked + .sa-check__box { background: var(--accent); border-color: var(--accent); }
  .sa-check input:checked + .sa-check__box svg { opacity: 1; transform: scale(1); }
  .sa-check input:focus-visible + .sa-check__box { box-shadow: 0 0 0 3px var(--focus-ring); }
  .sa-check--done { color: var(--text-faint); text-decoration: line-through; }
  .sa-check--disabled { opacity: 0.5; cursor: not-allowed; }
  `;
  const el = document.createElement("style");
  el.setAttribute("data-sa", "checkbox");
  el.textContent = css;
  document.head.appendChild(el);
}

export function Checkbox({ checked, defaultChecked, onChange, label, strikeWhenChecked = false, disabled = false, ...rest }) {
  ensureStyles();
  const isOn = checked !== undefined ? checked : defaultChecked;
  return (
    <label className={"sa-check" + (disabled ? " sa-check--disabled" : "") + (strikeWhenChecked && isOn ? " sa-check--done" : "")}>
      <input type="checkbox" checked={checked} defaultChecked={defaultChecked} onChange={onChange} disabled={disabled} {...rest} />
      <span className="sa-check__box">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12" /></svg>
      </span>
      {label && <span>{label}</span>}
    </label>
  );
}
