import React from "react";

let _injected = false;
function ensureStyles() {
  if (_injected || typeof document === "undefined") return;
  _injected = true;
  const css = `
  .sa-stat { font-family: var(--font-sans); display: flex; flex-direction: column; gap: 4px; }
  .sa-stat__label { font-size: var(--text-xs); text-transform: uppercase; letter-spacing: var(--tracking-caps); font-weight: 600; color: var(--text-faint); display: inline-flex; align-items: center; gap: 6px; }
  .sa-stat__label svg { width: 13px; height: 13px; }
  .sa-stat__value { font-family: var(--font-mono); font-size: var(--text-2xl); font-weight: 600; color: var(--text-strong); letter-spacing: -0.02em; line-height: 1.05; }
  .sa-stat__value .sa-stat__unit { font-size: 0.6em; color: var(--text-faint); margin-left: 2px; }
  .sa-stat__delta { display: inline-flex; align-items: center; gap: 4px; font-family: var(--font-sans); font-size: var(--text-sm); font-weight: 600; }
  .sa-stat__delta svg { width: 14px; height: 14px; }
  .sa-stat__delta--up { color: var(--green-600); }
  .sa-stat__delta--down { color: var(--clay-600); }
  .sa-stat__delta--flat { color: var(--text-muted); }
  `;
  const el = document.createElement("style");
  el.setAttribute("data-sa", "stat");
  el.textContent = css;
  document.head.appendChild(el);
}

export function Stat({ label, value, unit, icon = null, delta, trend = "up", className = "", ...rest }) {
  ensureStyles();
  return (
    <div className={["sa-stat", className].filter(Boolean).join(" ")} {...rest}>
      {label && <span className="sa-stat__label">{icon}{label}</span>}
      <span className="sa-stat__value">{value}{unit && <span className="sa-stat__unit">{unit}</span>}</span>
      {delta != null && (
        <span className={`sa-stat__delta sa-stat__delta--${trend}`}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            {trend === "down"
              ? <polyline points="6 9 12 15 18 9" />
              : trend === "flat"
              ? <line x1="5" y1="12" x2="19" y2="12" />
              : <polyline points="6 15 12 9 18 15" />}
          </svg>
          {delta}
        </span>
      )}
    </div>
  );
}
