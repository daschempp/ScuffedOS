import React from "react";

let _injected = false;
function ensureStyles() {
  if (_injected || typeof document === "undefined") return;
  _injected = true;
  const css = `
  .sa-card {
    background: var(--surface-raised);
    border-radius: var(--radius-lg);
    box-shadow: var(--shadow-md);
    padding: var(--space-5);
    box-sizing: border-box;
    font-family: var(--font-sans);
    color: var(--text-body);
    position: relative;
  }
  .sa-card--flat { box-shadow: inset 0 0 0 1px var(--border-hairline); }
  .sa-card--raised { box-shadow: var(--shadow-lg); }
  .sa-card--sunken { background: var(--surface-sunken); box-shadow: none; }
  .sa-card--interactive { cursor: pointer; transition: box-shadow var(--dur-base) var(--ease-out), transform var(--dur-base) var(--ease-out); }
  .sa-card--interactive:hover { box-shadow: var(--shadow-lg); transform: translateY(-2px); }
  .sa-card__head { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: var(--space-4); }
  .sa-card__title { font-family: var(--font-display); font-size: var(--text-lg); font-weight: 600; color: var(--text-strong); letter-spacing: var(--tracking-snug); margin: 0; }
  .sa-card__eyebrow { font-size: var(--text-xs); text-transform: uppercase; letter-spacing: var(--tracking-caps); font-weight: 600; color: var(--text-faint); margin: 0 0 4px; }
  `;
  const el = document.createElement("style");
  el.setAttribute("data-sa", "card");
  el.textContent = css;
  document.head.appendChild(el);
}

export function Card({
  variant = "default",
  interactive = false,
  title,
  eyebrow,
  action,
  className = "",
  children,
  ...rest
}) {
  ensureStyles();
  const cls = [
    "sa-card",
    variant !== "default" ? `sa-card--${variant}` : "",
    interactive ? "sa-card--interactive" : "",
    className,
  ].filter(Boolean).join(" ");
  const hasHead = title || eyebrow || action;
  return (
    <div className={cls} {...rest}>
      {hasHead && (
        <div className="sa-card__head">
          <div>
            {eyebrow && <p className="sa-card__eyebrow">{eyebrow}</p>}
            {title && <h3 className="sa-card__title">{title}</h3>}
          </div>
          {action}
        </div>
      )}
      {children}
    </div>
  );
}
