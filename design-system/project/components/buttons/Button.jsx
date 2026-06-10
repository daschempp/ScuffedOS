import React from "react";

let _injected = false;
function ensureStyles() {
  if (_injected || typeof document === "undefined") return;
  _injected = true;
  const css = `
  .sa-btn {
    font-family: var(--font-sans);
    font-weight: 600;
    border: none;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    border-radius: var(--radius-md);
    transition: background var(--dur-fast) var(--ease-out),
                box-shadow var(--dur-fast) var(--ease-out),
                transform var(--dur-fast) var(--ease-out),
                color var(--dur-fast) var(--ease-out);
    white-space: nowrap;
    line-height: 1;
    text-decoration: none;
    -webkit-tap-highlight-color: transparent;
  }
  .sa-btn:focus-visible { outline: none; box-shadow: 0 0 0 3px var(--focus-ring); }
  .sa-btn:active { transform: translateY(0.5px) scale(0.985); }
  .sa-btn[disabled] { cursor: not-allowed; opacity: 0.5; transform: none; box-shadow: none; }

  .sa-btn--sm { font-size: var(--text-sm); padding: 7px 13px; border-radius: var(--radius-sm); gap: 6px; }
  .sa-btn--md { font-size: var(--text-base); padding: 10px 17px; }
  .sa-btn--lg { font-size: var(--text-md); padding: 13px 22px; border-radius: var(--radius-lg); }
  .sa-btn--full { width: 100%; }

  .sa-btn--primary { background: var(--accent); color: var(--text-on-accent); box-shadow: var(--shadow-accent); }
  .sa-btn--primary:hover:not([disabled]) { background: var(--accent-hover); }
  .sa-btn--primary:active:not([disabled]) { background: var(--accent-press); }

  .sa-btn--secondary { background: var(--surface-raised); color: var(--text-strong); box-shadow: inset 0 0 0 1px var(--border-soft), var(--shadow-xs); }
  .sa-btn--secondary:hover:not([disabled]) { background: var(--paper-100); box-shadow: inset 0 0 0 1px var(--border-strong), var(--shadow-sm); }

  .sa-btn--soft { background: var(--accent-soft); color: var(--accent-text); }
  .sa-btn--soft:hover:not([disabled]) { background: var(--green-200); }

  .sa-btn--ghost { background: transparent; color: var(--text-body); }
  .sa-btn--ghost:hover:not([disabled]) { background: var(--surface-sunken); color: var(--text-strong); }

  .sa-btn--danger { background: var(--danger); color: #fff; box-shadow: 0 8px 22px -8px rgba(188,90,60,0.42); }
  .sa-btn--danger:hover:not([disabled]) { background: #a84c31; }

  .sa-btn__icon { display: inline-flex; width: 1.1em; height: 1.1em; }
  .sa-btn__icon svg { width: 100%; height: 100%; }
  `;
  const el = document.createElement("style");
  el.setAttribute("data-sa", "button");
  el.textContent = css;
  document.head.appendChild(el);
}

export function Button({
  variant = "primary",
  size = "md",
  iconLeft = null,
  iconRight = null,
  fullWidth = false,
  disabled = false,
  as = "button",
  className = "",
  children,
  ...rest
}) {
  ensureStyles();
  const Tag = as;
  const cls = [
    "sa-btn",
    `sa-btn--${variant}`,
    `sa-btn--${size}`,
    fullWidth ? "sa-btn--full" : "",
    className,
  ].filter(Boolean).join(" ");
  return (
    <Tag className={cls} disabled={Tag === "button" ? disabled : undefined} {...rest}>
      {iconLeft && <span className="sa-btn__icon">{iconLeft}</span>}
      {children && <span>{children}</span>}
      {iconRight && <span className="sa-btn__icon">{iconRight}</span>}
    </Tag>
  );
}
