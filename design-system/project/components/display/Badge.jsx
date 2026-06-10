import React from "react";

let _injected = false;
function ensureStyles() {
  if (_injected || typeof document === "undefined") return;
  _injected = true;
  const css = `
  .sa-badge {
    display: inline-flex; align-items: center; gap: 5px;
    font-family: var(--font-sans);
    font-size: var(--text-xs); font-weight: 600;
    line-height: 1; white-space: nowrap;
    padding: 4px 9px; border-radius: var(--radius-pill);
  }
  .sa-badge__dot { width: 6px; height: 6px; border-radius: 999px; background: currentColor; }
  .sa-badge svg { width: 12px; height: 12px; }
  .sa-badge--neutral { background: var(--surface-sunken); color: var(--text-muted); }
  .sa-badge--green  { background: var(--green-100); color: var(--green-700); }
  .sa-badge--clay   { background: var(--clay-100);  color: #97432c; }
  .sa-badge--honey  { background: var(--honey-100); color: #8d6320; }
  .sa-badge--sky    { background: var(--sky-100);   color: #2c556d; }
  .sa-badge--plum   { background: var(--plum-100);  color: #5f4267; }
  .sa-badge--solid  { background: var(--accent); color: var(--text-on-accent); }
  `;
  const el = document.createElement("style");
  el.setAttribute("data-sa", "badge");
  el.textContent = css;
  document.head.appendChild(el);
}

export function Badge({ color = "neutral", dot = false, icon = null, className = "", children, ...rest }) {
  ensureStyles();
  return (
    <span className={["sa-badge", `sa-badge--${color}`, className].filter(Boolean).join(" ")} {...rest}>
      {dot && <span className="sa-badge__dot" />}
      {icon}
      {children}
    </span>
  );
}
