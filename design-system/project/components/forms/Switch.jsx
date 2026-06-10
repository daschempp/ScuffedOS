import React from "react";

let _injected = false;
function ensureStyles() {
  if (_injected || typeof document === "undefined") return;
  _injected = true;
  const css = `
  .sa-switch { display: inline-flex; align-items: center; gap: 10px; cursor: pointer; font-family: var(--font-sans); font-size: var(--text-base); color: var(--text-strong); -webkit-tap-highlight-color: transparent; }
  .sa-switch input { position: absolute; opacity: 0; pointer-events: none; }
  .sa-switch__track {
    width: 42px; height: 24px; border-radius: var(--radius-pill);
    background: var(--paper-300);
    box-shadow: var(--shadow-inset);
    position: relative; flex: none;
    transition: background var(--dur-base) var(--ease-out);
  }
  .sa-switch__thumb {
    position: absolute; top: 2px; left: 2px;
    width: 20px; height: 20px; border-radius: 999px;
    background: var(--surface-raised);
    box-shadow: var(--shadow-sm);
    transition: transform var(--dur-base) var(--ease-soft);
  }
  .sa-switch input:checked + .sa-switch__track { background: var(--accent); }
  .sa-switch input:checked + .sa-switch__track .sa-switch__thumb { transform: translateX(18px); }
  .sa-switch input:focus-visible + .sa-switch__track { box-shadow: 0 0 0 3px var(--focus-ring); }
  .sa-switch--disabled { opacity: 0.5; cursor: not-allowed; }
  `;
  const el = document.createElement("style");
  el.setAttribute("data-sa", "switch");
  el.textContent = css;
  document.head.appendChild(el);
}

export function Switch({ checked, defaultChecked, onChange, label, disabled = false, ...rest }) {
  ensureStyles();
  return (
    <label className={"sa-switch" + (disabled ? " sa-switch--disabled" : "")}>
      <input
        type="checkbox"
        checked={checked}
        defaultChecked={defaultChecked}
        onChange={onChange}
        disabled={disabled}
        {...rest}
      />
      <span className="sa-switch__track"><span className="sa-switch__thumb" /></span>
      {label && <span>{label}</span>}
    </label>
  );
}
