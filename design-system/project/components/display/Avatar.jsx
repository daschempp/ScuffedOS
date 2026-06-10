import React from "react";

let _injected = false;
function ensureStyles() {
  if (_injected || typeof document === "undefined") return;
  _injected = true;
  const css = `
  .sa-avatar {
    display: inline-flex; align-items: center; justify-content: center;
    border-radius: var(--radius-pill);
    background: var(--green-200); color: var(--green-800);
    font-family: var(--font-display); font-weight: 700;
    overflow: hidden; flex: none;
    box-shadow: inset 0 0 0 1.5px rgba(255,255,255,0.5);
  }
  .sa-avatar img { width: 100%; height: 100%; object-fit: cover; }
  .sa-avatar--xs { width: 24px; height: 24px; font-size: 10px; }
  .sa-avatar--sm { width: 32px; height: 32px; font-size: 12px; }
  .sa-avatar--md { width: 40px; height: 40px; font-size: 15px; }
  .sa-avatar--lg { width: 52px; height: 52px; font-size: 19px; }
  `;
  const el = document.createElement("style");
  el.setAttribute("data-sa", "avatar");
  el.textContent = css;
  document.head.appendChild(el);
}

const TINTS = {
  green: ["var(--green-200)", "var(--green-800)"],
  clay:  ["var(--clay-100)", "#97432c"],
  honey: ["var(--honey-100)", "#8d6320"],
  sky:   ["var(--sky-100)", "#2c556d"],
  plum:  ["var(--plum-100)", "#5f4267"],
};

export function Avatar({ name = "", src, size = "md", tint = "green", className = "", ...rest }) {
  ensureStyles();
  const initials = name.split(/\s+/).filter(Boolean).slice(0, 2).map(w => w[0]).join("").toUpperCase();
  const [bg, fg] = TINTS[tint] || TINTS.green;
  return (
    <span
      className={["sa-avatar", `sa-avatar--${size}`, className].filter(Boolean).join(" ")}
      style={src ? undefined : { background: bg, color: fg }}
      {...rest}
    >
      {src ? <img src={src} alt={name} /> : initials || "?"}
    </span>
  );
}
