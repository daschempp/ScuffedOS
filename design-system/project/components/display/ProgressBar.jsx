import React from "react";

let _injected = false;
function ensureStyles() {
  if (_injected || typeof document === "undefined") return;
  _injected = true;
  const css = `
  .sa-progress { font-family: var(--font-sans); display: flex; flex-direction: column; gap: 7px; }
  .sa-progress__top { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; }
  .sa-progress__label { font-size: var(--text-sm); font-weight: 600; color: var(--text-strong); }
  .sa-progress__meta { font-family: var(--font-mono); font-size: var(--text-xs); color: var(--text-muted); }
  .sa-progress__track {
    height: 10px; border-radius: var(--radius-pill);
    background: var(--paper-300);
    box-shadow: var(--shadow-inset);
    overflow: hidden;
  }
  .sa-progress__fill {
    height: 100%; border-radius: var(--radius-pill);
    background: var(--accent);
    transition: width var(--dur-slow) var(--ease-out);
  }
  .sa-progress--sm .sa-progress__track { height: 6px; }
  .sa-progress--lg .sa-progress__track { height: 14px; }
  `;
  const el = document.createElement("style");
  el.setAttribute("data-sa", "progressbar");
  el.textContent = css;
  document.head.appendChild(el);
}

const COLORS = {
  green: "var(--green-600)", clay: "var(--clay-600)", honey: "var(--honey-600)",
  sky: "var(--sky-600)", plum: "var(--plum-600)",
};

export function ProgressBar({ value = 0, max = 100, label, meta, color = "green", size = "md", className = "", ...rest }) {
  ensureStyles();
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  return (
    <div className={["sa-progress", `sa-progress--${size}`, className].filter(Boolean).join(" ")} {...rest}>
      {(label || meta) && (
        <div className="sa-progress__top">
          {label && <span className="sa-progress__label">{label}</span>}
          {meta && <span className="sa-progress__meta">{meta}</span>}
        </div>
      )}
      <div className="sa-progress__track">
        <div className="sa-progress__fill" style={{ width: pct + "%", background: COLORS[color] || COLORS.green }} />
      </div>
    </div>
  );
}
