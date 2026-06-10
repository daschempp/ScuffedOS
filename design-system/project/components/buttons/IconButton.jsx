import React from "react";

let _injected = false;
function ensureStyles() {
  if (_injected || typeof document === "undefined") return;
  _injected = true;
  const css = `
  .sa-iconbtn {
    font-family: var(--font-sans);
    border: none;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border-radius: var(--radius-md);
    color: var(--text-muted);
    background: transparent;
    transition: background var(--dur-fast) var(--ease-out),
                color var(--dur-fast) var(--ease-out),
                box-shadow var(--dur-fast) var(--ease-out),
                transform var(--dur-fast) var(--ease-out);
    -webkit-tap-highlight-color: transparent;
  }
  .sa-iconbtn:hover:not([disabled]) { background: var(--surface-sunken); color: var(--text-strong); }
  .sa-iconbtn:active:not([disabled]) { transform: scale(0.92); }
  .sa-iconbtn:focus-visible { outline: none; box-shadow: 0 0 0 3px var(--focus-ring); }
  .sa-iconbtn[disabled] { opacity: 0.45; cursor: not-allowed; }

  .sa-iconbtn--sm { width: 32px; height: 32px; border-radius: var(--radius-sm); }
  .sa-iconbtn--md { width: 40px; height: 40px; }
  .sa-iconbtn--lg { width: 48px; height: 48px; border-radius: var(--radius-lg); }

  .sa-iconbtn--solid { background: var(--accent); color: var(--text-on-accent); box-shadow: var(--shadow-accent); }
  .sa-iconbtn--solid:hover:not([disabled]) { background: var(--accent-hover); color: var(--text-on-accent); }
  .sa-iconbtn--soft { background: var(--accent-soft); color: var(--accent-text); }
  .sa-iconbtn--soft:hover:not([disabled]) { background: var(--green-200); color: var(--accent-text); }

  .sa-iconbtn svg { width: 1.25em; height: 1.25em; display: block; }
  .sa-iconbtn--sm svg { font-size: 15px; }
  .sa-iconbtn--md svg { font-size: 18px; }
  .sa-iconbtn--lg svg { font-size: 21px; }
  `;
  const el = document.createElement("style");
  el.setAttribute("data-sa", "iconbutton");
  el.textContent = css;
  document.head.appendChild(el);
}

export function IconButton({
  variant = "ghost",
  size = "md",
  label,
  disabled = false,
  className = "",
  children,
  ...rest
}) {
  ensureStyles();
  const cls = [
    "sa-iconbtn",
    `sa-iconbtn--${variant}`,
    `sa-iconbtn--${size}`,
    className,
  ].filter(Boolean).join(" ");
  return (
    <button className={cls} aria-label={label} title={label} disabled={disabled} {...rest}>
      {children}
    </button>
  );
}
