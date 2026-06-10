/* @ds-bundle: {"format":3,"namespace":"ScuffedOSDesignSystem_c8c4c3","components":[{"name":"Button","sourcePath":"components/buttons/Button.jsx"},{"name":"IconButton","sourcePath":"components/buttons/IconButton.jsx"},{"name":"Avatar","sourcePath":"components/display/Avatar.jsx"},{"name":"Badge","sourcePath":"components/display/Badge.jsx"},{"name":"Card","sourcePath":"components/display/Card.jsx"},{"name":"ProgressBar","sourcePath":"components/display/ProgressBar.jsx"},{"name":"ProgressRing","sourcePath":"components/display/ProgressRing.jsx"},{"name":"Stat","sourcePath":"components/display/Stat.jsx"},{"name":"Checkbox","sourcePath":"components/forms/Checkbox.jsx"},{"name":"Input","sourcePath":"components/forms/Input.jsx"},{"name":"Switch","sourcePath":"components/forms/Switch.jsx"}],"sourceHashes":{"components/buttons/Button.jsx":"ee27599efbd8","components/buttons/IconButton.jsx":"65f85fd57981","components/display/Avatar.jsx":"fa4992cc1b9d","components/display/Badge.jsx":"9d4d17683690","components/display/Card.jsx":"8d628fd6c520","components/display/ProgressBar.jsx":"f928002b3bed","components/display/ProgressRing.jsx":"7ae6fe42d629","components/display/Stat.jsx":"66b1265dc3ac","components/forms/Checkbox.jsx":"15fc693a1a0f","components/forms/Input.jsx":"60fbae7b79ea","components/forms/Switch.jsx":"2e5be6c384f8","ui_kits/scuffed-os-ios/MobileAssistant.jsx":"54ddfc2a42c8","ui_kits/scuffed-os-ios/VoiceSheet.jsx":"cc5d60e22687","ui_kits/scuffed-os-ios/ios-frame.jsx":"be3343be4b51","ui_kits/scuffed-os-ios/mobile-more.jsx":"28581b6c584e","ui_kits/scuffed-os-ios/mobileapp.jsx":"92b87dd624e8","ui_kits/scuffed-os-ios/screens.jsx":"2fd15cbfb62e","ui_kits/scuffed-os/CRMScreen.jsx":"d01cea8510b9","ui_kits/scuffed-os/CalendarScreen.jsx":"fa7e936c6b15","ui_kits/scuffed-os/ChatPanel.jsx":"60100d417d27","ui_kits/scuffed-os/DashboardScreen.jsx":"70a98bb5af66","ui_kits/scuffed-os/EmailScreen.jsx":"bbd8dbe90e2e","ui_kits/scuffed-os/FinanceScreen.jsx":"c5849556a529","ui_kits/scuffed-os/FitnessScreen.jsx":"dafbebe12be5","ui_kits/scuffed-os/HabitsScreen.jsx":"ccfa8f5532ce","ui_kits/scuffed-os/MemoryScreen.jsx":"1d5c80d07c30","ui_kits/scuffed-os/NutritionScreen.jsx":"08a603ed2626","ui_kits/scuffed-os/Sidebar.jsx":"dc4c6cdf97cc","ui_kits/scuffed-os/TaskDetail.jsx":"1e424d9afc04","ui_kits/scuffed-os/TasksScreen.jsx":"cd01944a2795","ui_kits/scuffed-os/TopBar.jsx":"1683312451e5","ui_kits/scuffed-os/app.jsx":"7fdbb57a4914","ui_kits/scuffed-os/assistant-logic.js":"87119f1012fa","ui_kits/scuffed-os/ui.jsx":"8aaf1935944f"},"inlinedExternals":[],"unexposedExports":[]} */

(() => {

const __ds_ns = (window.ScuffedOSDesignSystem_c8c4c3 = window.ScuffedOSDesignSystem_c8c4c3 || {});

const __ds_scope = {};

(__ds_ns.__errors = __ds_ns.__errors || []);

// components/buttons/Button.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
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
function Button({
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
  const cls = ["sa-btn", `sa-btn--${variant}`, `sa-btn--${size}`, fullWidth ? "sa-btn--full" : "", className].filter(Boolean).join(" ");
  return /*#__PURE__*/React.createElement(Tag, _extends({
    className: cls,
    disabled: Tag === "button" ? disabled : undefined
  }, rest), iconLeft && /*#__PURE__*/React.createElement("span", {
    className: "sa-btn__icon"
  }, iconLeft), children && /*#__PURE__*/React.createElement("span", null, children), iconRight && /*#__PURE__*/React.createElement("span", {
    className: "sa-btn__icon"
  }, iconRight));
}
Object.assign(__ds_scope, { Button });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/buttons/Button.jsx", error: String((e && e.message) || e) }); }

// components/buttons/IconButton.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
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
function IconButton({
  variant = "ghost",
  size = "md",
  label,
  disabled = false,
  className = "",
  children,
  ...rest
}) {
  ensureStyles();
  const cls = ["sa-iconbtn", `sa-iconbtn--${variant}`, `sa-iconbtn--${size}`, className].filter(Boolean).join(" ");
  return /*#__PURE__*/React.createElement("button", _extends({
    className: cls,
    "aria-label": label,
    title: label,
    disabled: disabled
  }, rest), children);
}
Object.assign(__ds_scope, { IconButton });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/buttons/IconButton.jsx", error: String((e && e.message) || e) }); }

// components/display/Avatar.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
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
  clay: ["var(--clay-100)", "#97432c"],
  honey: ["var(--honey-100)", "#8d6320"],
  sky: ["var(--sky-100)", "#2c556d"],
  plum: ["var(--plum-100)", "#5f4267"]
};
function Avatar({
  name = "",
  src,
  size = "md",
  tint = "green",
  className = "",
  ...rest
}) {
  ensureStyles();
  const initials = name.split(/\s+/).filter(Boolean).slice(0, 2).map(w => w[0]).join("").toUpperCase();
  const [bg, fg] = TINTS[tint] || TINTS.green;
  return /*#__PURE__*/React.createElement("span", _extends({
    className: ["sa-avatar", `sa-avatar--${size}`, className].filter(Boolean).join(" "),
    style: src ? undefined : {
      background: bg,
      color: fg
    }
  }, rest), src ? /*#__PURE__*/React.createElement("img", {
    src: src,
    alt: name
  }) : initials || "?");
}
Object.assign(__ds_scope, { Avatar });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/display/Avatar.jsx", error: String((e && e.message) || e) }); }

// components/display/Badge.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
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
function Badge({
  color = "neutral",
  dot = false,
  icon = null,
  className = "",
  children,
  ...rest
}) {
  ensureStyles();
  return /*#__PURE__*/React.createElement("span", _extends({
    className: ["sa-badge", `sa-badge--${color}`, className].filter(Boolean).join(" ")
  }, rest), dot && /*#__PURE__*/React.createElement("span", {
    className: "sa-badge__dot"
  }), icon, children);
}
Object.assign(__ds_scope, { Badge });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/display/Badge.jsx", error: String((e && e.message) || e) }); }

// components/display/Card.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
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
function Card({
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
  const cls = ["sa-card", variant !== "default" ? `sa-card--${variant}` : "", interactive ? "sa-card--interactive" : "", className].filter(Boolean).join(" ");
  const hasHead = title || eyebrow || action;
  return /*#__PURE__*/React.createElement("div", _extends({
    className: cls
  }, rest), hasHead && /*#__PURE__*/React.createElement("div", {
    className: "sa-card__head"
  }, /*#__PURE__*/React.createElement("div", null, eyebrow && /*#__PURE__*/React.createElement("p", {
    className: "sa-card__eyebrow"
  }, eyebrow), title && /*#__PURE__*/React.createElement("h3", {
    className: "sa-card__title"
  }, title)), action), children);
}
Object.assign(__ds_scope, { Card });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/display/Card.jsx", error: String((e && e.message) || e) }); }

// components/display/ProgressBar.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
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
  green: "var(--green-600)",
  clay: "var(--clay-600)",
  honey: "var(--honey-600)",
  sky: "var(--sky-600)",
  plum: "var(--plum-600)"
};
function ProgressBar({
  value = 0,
  max = 100,
  label,
  meta,
  color = "green",
  size = "md",
  className = "",
  ...rest
}) {
  ensureStyles();
  const pct = Math.max(0, Math.min(100, value / max * 100));
  return /*#__PURE__*/React.createElement("div", _extends({
    className: ["sa-progress", `sa-progress--${size}`, className].filter(Boolean).join(" ")
  }, rest), (label || meta) && /*#__PURE__*/React.createElement("div", {
    className: "sa-progress__top"
  }, label && /*#__PURE__*/React.createElement("span", {
    className: "sa-progress__label"
  }, label), meta && /*#__PURE__*/React.createElement("span", {
    className: "sa-progress__meta"
  }, meta)), /*#__PURE__*/React.createElement("div", {
    className: "sa-progress__track"
  }, /*#__PURE__*/React.createElement("div", {
    className: "sa-progress__fill",
    style: {
      width: pct + "%",
      background: COLORS[color] || COLORS.green
    }
  })));
}
Object.assign(__ds_scope, { ProgressBar });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/display/ProgressBar.jsx", error: String((e && e.message) || e) }); }

// components/display/ProgressRing.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
const COLORS = {
  green: "var(--green-600)",
  clay: "var(--clay-600)",
  honey: "var(--honey-600)",
  sky: "var(--sky-600)",
  plum: "var(--plum-600)"
};

/** Concentric progress ring — the nutrition tracker's signature widget. */
function ProgressRing({
  value = 0,
  max = 100,
  size = 72,
  thickness = 9,
  color = "green",
  trackColor = "var(--paper-300)",
  label,
  sublabel,
  ...rest
}) {
  const pct = Math.max(0, Math.min(1, value / max));
  const r = (size - thickness) / 2;
  const c = 2 * Math.PI * r;
  const stroke = COLORS[color] || COLORS.green;
  return /*#__PURE__*/React.createElement("div", _extends({
    style: {
      position: "relative",
      width: size,
      height: size,
      fontFamily: "var(--font-sans)"
    }
  }, rest), /*#__PURE__*/React.createElement("svg", {
    width: size,
    height: size,
    style: {
      transform: "rotate(-90deg)"
    }
  }, /*#__PURE__*/React.createElement("circle", {
    cx: size / 2,
    cy: size / 2,
    r: r,
    fill: "none",
    stroke: trackColor,
    strokeWidth: thickness
  }), /*#__PURE__*/React.createElement("circle", {
    cx: size / 2,
    cy: size / 2,
    r: r,
    fill: "none",
    stroke: stroke,
    strokeWidth: thickness,
    strokelinecap: "round",
    strokeDasharray: c,
    strokeDashoffset: c * (1 - pct),
    strokeLinecap: "round",
    style: {
      transition: "stroke-dashoffset var(--dur-slow) var(--ease-out)"
    }
  })), (label || sublabel) && /*#__PURE__*/React.createElement("div", {
    style: {
      position: "absolute",
      inset: 0,
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      justifyContent: "center",
      textAlign: "center"
    }
  }, label && /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: size * 0.26,
      fontWeight: 600,
      color: "var(--text-strong)",
      lineHeight: 1
    }
  }, label), sublabel && /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: size * 0.13,
      color: "var(--text-faint)",
      marginTop: 2
    }
  }, sublabel)));
}
Object.assign(__ds_scope, { ProgressRing });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/display/ProgressRing.jsx", error: String((e && e.message) || e) }); }

// components/display/Stat.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
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
function Stat({
  label,
  value,
  unit,
  icon = null,
  delta,
  trend = "up",
  className = "",
  ...rest
}) {
  ensureStyles();
  return /*#__PURE__*/React.createElement("div", _extends({
    className: ["sa-stat", className].filter(Boolean).join(" ")
  }, rest), label && /*#__PURE__*/React.createElement("span", {
    className: "sa-stat__label"
  }, icon, label), /*#__PURE__*/React.createElement("span", {
    className: "sa-stat__value"
  }, value, unit && /*#__PURE__*/React.createElement("span", {
    className: "sa-stat__unit"
  }, unit)), delta != null && /*#__PURE__*/React.createElement("span", {
    className: `sa-stat__delta sa-stat__delta--${trend}`
  }, /*#__PURE__*/React.createElement("svg", {
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: "2.5",
    strokeLinecap: "round",
    strokeLinejoin: "round"
  }, trend === "down" ? /*#__PURE__*/React.createElement("polyline", {
    points: "6 9 12 15 18 9"
  }) : trend === "flat" ? /*#__PURE__*/React.createElement("line", {
    x1: "5",
    y1: "12",
    x2: "19",
    y2: "12"
  }) : /*#__PURE__*/React.createElement("polyline", {
    points: "6 15 12 9 18 15"
  })), delta));
}
Object.assign(__ds_scope, { Stat });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/display/Stat.jsx", error: String((e && e.message) || e) }); }

// components/forms/Checkbox.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
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
function Checkbox({
  checked,
  defaultChecked,
  onChange,
  label,
  strikeWhenChecked = false,
  disabled = false,
  ...rest
}) {
  ensureStyles();
  const isOn = checked !== undefined ? checked : defaultChecked;
  return /*#__PURE__*/React.createElement("label", {
    className: "sa-check" + (disabled ? " sa-check--disabled" : "") + (strikeWhenChecked && isOn ? " sa-check--done" : "")
  }, /*#__PURE__*/React.createElement("input", _extends({
    type: "checkbox",
    checked: checked,
    defaultChecked: defaultChecked,
    onChange: onChange,
    disabled: disabled
  }, rest)), /*#__PURE__*/React.createElement("span", {
    className: "sa-check__box"
  }, /*#__PURE__*/React.createElement("svg", {
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: "3.5",
    strokeLinecap: "round",
    strokeLinejoin: "round"
  }, /*#__PURE__*/React.createElement("polyline", {
    points: "20 6 9 17 4 12"
  }))), label && /*#__PURE__*/React.createElement("span", null, label));
}
Object.assign(__ds_scope, { Checkbox });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/forms/Checkbox.jsx", error: String((e && e.message) || e) }); }

// components/forms/Input.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
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
function Input({
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
  return /*#__PURE__*/React.createElement("div", {
    className: "sa-field"
  }, label && /*#__PURE__*/React.createElement("label", {
    className: "sa-field__label",
    htmlFor: fid
  }, label), /*#__PURE__*/React.createElement("div", {
    className: "sa-input-wrap"
  }, icon && /*#__PURE__*/React.createElement("span", {
    className: "sa-input-wrap__icon"
  }, icon), /*#__PURE__*/React.createElement("input", _extends({
    id: fid,
    className: ["sa-input", icon ? "sa-input--has-icon" : "", error ? "sa-input--error" : "", className].filter(Boolean).join(" ")
  }, rest))), error ? /*#__PURE__*/React.createElement("span", {
    className: "sa-field__hint",
    style: {
      color: "var(--danger)"
    }
  }, error) : hint ? /*#__PURE__*/React.createElement("span", {
    className: "sa-field__hint"
  }, hint) : null);
}
Object.assign(__ds_scope, { Input });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/forms/Input.jsx", error: String((e && e.message) || e) }); }

// components/forms/Switch.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
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
function Switch({
  checked,
  defaultChecked,
  onChange,
  label,
  disabled = false,
  ...rest
}) {
  ensureStyles();
  return /*#__PURE__*/React.createElement("label", {
    className: "sa-switch" + (disabled ? " sa-switch--disabled" : "")
  }, /*#__PURE__*/React.createElement("input", _extends({
    type: "checkbox",
    checked: checked,
    defaultChecked: defaultChecked,
    onChange: onChange,
    disabled: disabled
  }, rest)), /*#__PURE__*/React.createElement("span", {
    className: "sa-switch__track"
  }, /*#__PURE__*/React.createElement("span", {
    className: "sa-switch__thumb"
  })), label && /*#__PURE__*/React.createElement("span", null, label));
}
Object.assign(__ds_scope, { Switch });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/forms/Switch.jsx", error: String((e && e.message) || e) }); }

// ui_kits/scuffed-os-ios/MobileAssistant.jsx
try { (() => {
/* Scuffed OS — iPhone full-screen assistant chat */
function MobileAssistant({
  onClose,
  onNavigate,
  onCreateTask
}) {
  const [messages, setMessages] = React.useState([{
    id: 1,
    role: "ai",
    text: "Good morning, Sam. <strong>4 tasks</strong> today, a standup at 11:30, and you're $120 under budget. What can I do?"
  }]);
  const [input, setInput] = React.useState("");
  const [typing, setTyping] = React.useState(false);
  const logRef = React.useRef(null);
  React.useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [messages, typing]);
  const send = raw => {
    const text = (raw != null ? raw : input).trim();
    if (!text) return;
    setMessages(m => [...m, {
      id: Date.now(),
      role: "user",
      text
    }]);
    setInput("");
    setTyping(true);
    setTimeout(() => {
      const r = window.ScuffedAssistant.reply(text);
      if (r.action && r.action.makeTask && onCreateTask) onCreateTask(r.action.makeTask);
      setTyping(false);
      setMessages(m => [...m, {
        id: Date.now() + 1,
        role: "ai",
        text: r.text,
        action: r.action
      }]);
    }, 800);
  };
  const goAction = screen => {
    if (screen && onNavigate) onNavigate(screen);
    onClose();
  };
  const suggestions = ["Plan my day", "Add a task", "Spent on dining?", "Log breakfast"];
  return /*#__PURE__*/React.createElement("div", {
    className: "m-chat"
  }, /*#__PURE__*/React.createElement("div", {
    className: "m-chat__head"
  }, /*#__PURE__*/React.createElement("div", {
    className: "m-chat__id"
  }, /*#__PURE__*/React.createElement("img", {
    src: "../../assets/logo-mark.svg",
    alt: ""
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "m-chat__name"
  }, "Scuffed Assistant"), /*#__PURE__*/React.createElement("div", {
    className: "m-chat__status"
  }, "Connected to your second brain")), /*#__PURE__*/React.createElement(IconButton, {
    label: "Close",
    size: "sm",
    onClick: onClose
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "chevron-down"
  }))), /*#__PURE__*/React.createElement("div", {
    className: "m-chat__log",
    ref: logRef
  }, messages.map(m => /*#__PURE__*/React.createElement("div", {
    key: m.id,
    className: "kit-msg kit-msg--" + m.role
  }, m.role === "ai" && /*#__PURE__*/React.createElement("span", {
    className: "kit-msg__av"
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "sparkles"
  })), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    className: "kit-bubble",
    dangerouslySetInnerHTML: {
      __html: m.text
    }
  }), m.action && /*#__PURE__*/React.createElement("div", {
    className: "kit-action"
  }, /*#__PURE__*/React.createElement("span", {
    className: "kit-action__ico"
  }, /*#__PURE__*/React.createElement(Icon, {
    name: m.action.icon
  })), /*#__PURE__*/React.createElement("div", {
    className: "kit-action__main"
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-action__title"
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "check"
  }), m.action.title), /*#__PURE__*/React.createElement("div", {
    className: "kit-action__meta"
  }, m.action.meta)), /*#__PURE__*/React.createElement("span", {
    className: "kit-action__cta",
    onClick: () => goAction(m.action.screen)
  }, m.action.cta))))), typing && /*#__PURE__*/React.createElement("div", {
    className: "kit-msg kit-msg--ai"
  }, /*#__PURE__*/React.createElement("span", {
    className: "kit-msg__av"
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "sparkles"
  })), /*#__PURE__*/React.createElement("div", {
    className: "kit-bubble",
    style: {
      padding: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-typing"
  }, /*#__PURE__*/React.createElement("i", null), /*#__PURE__*/React.createElement("i", null), /*#__PURE__*/React.createElement("i", null))))), /*#__PURE__*/React.createElement("div", {
    className: "m-chat__suggest"
  }, suggestions.map(s => /*#__PURE__*/React.createElement("span", {
    key: s,
    className: "kit-suggest",
    onClick: () => send(s)
  }, s))), /*#__PURE__*/React.createElement("div", {
    className: "m-composer"
  }, /*#__PURE__*/React.createElement("div", {
    className: "m-composer__box"
  }, /*#__PURE__*/React.createElement("input", {
    value: input,
    placeholder: "Ask or tell your assistant\u2026",
    onChange: e => setInput(e.target.value),
    onKeyDown: e => {
      if (e.key === "Enter") send();
    }
  }), /*#__PURE__*/React.createElement(IconButton, {
    label: "Voice",
    variant: "ghost",
    size: "sm"
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "mic"
  }))), /*#__PURE__*/React.createElement(IconButton, {
    label: "Send",
    variant: "solid",
    onClick: () => send()
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "arrow-up"
  }))));
}
window.MobileAssistant = MobileAssistant;
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/scuffed-os-ios/MobileAssistant.jsx", error: String((e && e.message) || e) }); }

// ui_kits/scuffed-os-ios/VoiceSheet.jsx
try { (() => {
/* Scuffed OS — iPhone voice-capture bottom sheet (the "send from anywhere" feature) */
function VoiceSheet({
  onClose,
  onCapture
}) {
  const phrase = "Remind me to call the dentist tomorrow";
  const [done, setDone] = React.useState(false);
  const [shown, setShown] = React.useState("");
  React.useEffect(() => {
    let i = 0;
    const id = setInterval(() => {
      i += 1;
      setShown(phrase.slice(0, i));
      if (i >= phrase.length) clearInterval(id);
    }, 45);
    return () => clearInterval(id);
  }, []);
  const send = () => {
    setDone(true);
    if (onCapture) onCapture(window.ScuffedAssistant.cleanTitle(phrase));
    setTimeout(onClose, 850);
  };
  return /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("div", {
    className: "m-scrim",
    onClick: onClose
  }), /*#__PURE__*/React.createElement("div", {
    className: "m-sheet"
  }, /*#__PURE__*/React.createElement("div", {
    className: "m-grip"
  }), done ? /*#__PURE__*/React.createElement("div", {
    className: "m-voice"
  }, /*#__PURE__*/React.createElement("div", {
    className: "m-voice__mic",
    style: {
      background: "var(--green-600)"
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "check"
  })), /*#__PURE__*/React.createElement("h3", null, "Sent to Scuffed"), /*#__PURE__*/React.createElement("p", null, "I've added it to your tasks and set a reminder.")) : /*#__PURE__*/React.createElement("div", {
    className: "m-voice"
  }, /*#__PURE__*/React.createElement("div", {
    className: "m-voice__mic"
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "mic"
  })), /*#__PURE__*/React.createElement("div", {
    className: "m-voice__wave"
  }, Array.from({
    length: 18
  }).map((_, i) => /*#__PURE__*/React.createElement("i", {
    key: i,
    style: {
      height: 7 + i % 6 * 4,
      animationDelay: i * 0.05 + "s"
    }
  }))), /*#__PURE__*/React.createElement("h3", null, "Listening\u2026"), /*#__PURE__*/React.createElement("p", {
    style: {
      minHeight: 40
    }
  }, "\"", shown, /*#__PURE__*/React.createElement("span", {
    style: {
      opacity: 0.4
    }
  }, "|"), "\""), /*#__PURE__*/React.createElement("div", {
    className: "m-pillrow",
    style: {
      width: "100%"
    }
  }, /*#__PURE__*/React.createElement(Button, {
    variant: "secondary",
    fullWidth: true,
    onClick: onClose
  }, "Cancel"), /*#__PURE__*/React.createElement(Button, {
    variant: "primary",
    fullWidth: true,
    iconLeft: /*#__PURE__*/React.createElement(Icon, {
      name: "arrow-up"
    }),
    onClick: send
  }, "Send to Scuffed")), /*#__PURE__*/React.createElement("p", {
    style: {
      fontSize: 12,
      color: "var(--text-faint)"
    }
  }, "Also works from Telegram, anywhere you are"))));
}
window.VoiceSheet = VoiceSheet;
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/scuffed-os-ios/VoiceSheet.jsx", error: String((e && e.message) || e) }); }

// ui_kits/scuffed-os-ios/ios-frame.jsx
try { (() => {
// @ds-adherence-ignore -- omelette starter scaffold (raw elements/hex/px by design)

/* BEGIN USAGE */
// iOS.jsx — Simplified iOS 26 (Liquid Glass) device frame
// Based on the iOS 26 UI Kit + Figma status bar spec. No assets, no deps.
// Exports (to window): IOSDevice, IOSStatusBar, IOSNavBar, IOSGlassPill, IOSList, IOSListRow, IOSKeyboard
//
// Usage — wrap your screen content in <IOSDevice> to get the bezel, status bar
// and home indicator (props: title, dark, keyboard):
//
//   <IOSDevice title="Settings">
//     ...your screen content...
//   </IOSDevice>
//   <IOSDevice dark title="Search" keyboard>…</IOSDevice>
/* END USAGE */

// ─────────────────────────────────────────────────────────────
// Status bar
// ─────────────────────────────────────────────────────────────
function IOSStatusBar({
  dark = false,
  time = '9:41'
}) {
  const c = dark ? '#fff' : '#000';
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 154,
      alignItems: 'center',
      justifyContent: 'center',
      padding: '21px 24px 19px',
      boxSizing: 'border-box',
      position: 'relative',
      zIndex: 20,
      width: '100%'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      height: 22,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      paddingTop: 1.5
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: '-apple-system, "SF Pro", system-ui',
      fontWeight: 590,
      fontSize: 17,
      lineHeight: '22px',
      color: c
    }
  }, time)), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      height: 22,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      gap: 7,
      paddingTop: 1,
      paddingRight: 1
    }
  }, /*#__PURE__*/React.createElement("svg", {
    width: "19",
    height: "12",
    viewBox: "0 0 19 12"
  }, /*#__PURE__*/React.createElement("rect", {
    x: "0",
    y: "7.5",
    width: "3.2",
    height: "4.5",
    rx: "0.7",
    fill: c
  }), /*#__PURE__*/React.createElement("rect", {
    x: "4.8",
    y: "5",
    width: "3.2",
    height: "7",
    rx: "0.7",
    fill: c
  }), /*#__PURE__*/React.createElement("rect", {
    x: "9.6",
    y: "2.5",
    width: "3.2",
    height: "9.5",
    rx: "0.7",
    fill: c
  }), /*#__PURE__*/React.createElement("rect", {
    x: "14.4",
    y: "0",
    width: "3.2",
    height: "12",
    rx: "0.7",
    fill: c
  })), /*#__PURE__*/React.createElement("svg", {
    width: "17",
    height: "12",
    viewBox: "0 0 17 12"
  }, /*#__PURE__*/React.createElement("path", {
    d: "M8.5 3.2C10.8 3.2 12.9 4.1 14.4 5.6L15.5 4.5C13.7 2.7 11.2 1.5 8.5 1.5C5.8 1.5 3.3 2.7 1.5 4.5L2.6 5.6C4.1 4.1 6.2 3.2 8.5 3.2Z",
    fill: c
  }), /*#__PURE__*/React.createElement("path", {
    d: "M8.5 6.8C9.9 6.8 11.1 7.3 12 8.2L13.1 7.1C11.8 5.9 10.2 5.1 8.5 5.1C6.8 5.1 5.2 5.9 3.9 7.1L5 8.2C5.9 7.3 7.1 6.8 8.5 6.8Z",
    fill: c
  }), /*#__PURE__*/React.createElement("circle", {
    cx: "8.5",
    cy: "10.5",
    r: "1.5",
    fill: c
  })), /*#__PURE__*/React.createElement("svg", {
    width: "27",
    height: "13",
    viewBox: "0 0 27 13"
  }, /*#__PURE__*/React.createElement("rect", {
    x: "0.5",
    y: "0.5",
    width: "23",
    height: "12",
    rx: "3.5",
    stroke: c,
    strokeOpacity: "0.35",
    fill: "none"
  }), /*#__PURE__*/React.createElement("rect", {
    x: "2",
    y: "2",
    width: "20",
    height: "9",
    rx: "2",
    fill: c
  }), /*#__PURE__*/React.createElement("path", {
    d: "M25 4.5V8.5C25.8 8.2 26.5 7.2 26.5 6.5C26.5 5.8 25.8 4.8 25 4.5Z",
    fill: c,
    fillOpacity: "0.4"
  }))));
}

// ─────────────────────────────────────────────────────────────
// Liquid glass pill — blur + tint + shine
// ─────────────────────────────────────────────────────────────
function IOSGlassPill({
  children,
  dark = false,
  style = {}
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      height: 44,
      minWidth: 44,
      borderRadius: 9999,
      position: 'relative',
      overflow: 'hidden',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      boxShadow: dark ? '0 2px 6px rgba(0,0,0,0.35), 0 6px 16px rgba(0,0,0,0.2)' : '0 1px 3px rgba(0,0,0,0.07), 0 3px 10px rgba(0,0,0,0.06)',
      ...style
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      inset: 0,
      borderRadius: 9999,
      backdropFilter: 'blur(12px) saturate(180%)',
      WebkitBackdropFilter: 'blur(12px) saturate(180%)',
      background: dark ? 'rgba(120,120,128,0.28)' : 'rgba(255,255,255,0.5)'
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      inset: 0,
      borderRadius: 9999,
      boxShadow: dark ? 'inset 1.5px 1.5px 1px rgba(255,255,255,0.15), inset -1px -1px 1px rgba(255,255,255,0.08)' : 'inset 1.5px 1.5px 1px rgba(255,255,255,0.7), inset -1px -1px 1px rgba(255,255,255,0.4)',
      border: dark ? '0.5px solid rgba(255,255,255,0.15)' : '0.5px solid rgba(0,0,0,0.06)'
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'relative',
      zIndex: 1,
      display: 'flex',
      alignItems: 'center',
      padding: '0 4px'
    }
  }, children));
}

// ─────────────────────────────────────────────────────────────
// Navigation bar — glass pills + large title
// ─────────────────────────────────────────────────────────────
function IOSNavBar({
  title = 'Title',
  dark = false,
  trailingIcon = true
}) {
  const muted = dark ? 'rgba(255,255,255,0.6)' : '#404040';
  const text = dark ? '#fff' : '#000';
  const pillIcon = content => /*#__PURE__*/React.createElement(IOSGlassPill, {
    dark: dark
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: 36,
      height: 36,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center'
    }
  }, content));
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 10,
      paddingTop: 62,
      paddingBottom: 10,
      position: 'relative',
      zIndex: 5
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      padding: '0 16px'
    }
  }, pillIcon(/*#__PURE__*/React.createElement("svg", {
    width: "12",
    height: "20",
    viewBox: "0 0 12 20",
    fill: "none",
    style: {
      marginLeft: -1
    }
  }, /*#__PURE__*/React.createElement("path", {
    d: "M10 2L2 10l8 8",
    stroke: muted,
    strokeWidth: "2.5",
    strokeLinecap: "round",
    strokeLinejoin: "round"
  }))), trailingIcon && pillIcon(/*#__PURE__*/React.createElement("svg", {
    width: "22",
    height: "6",
    viewBox: "0 0 22 6"
  }, /*#__PURE__*/React.createElement("circle", {
    cx: "3",
    cy: "3",
    r: "2.5",
    fill: muted
  }), /*#__PURE__*/React.createElement("circle", {
    cx: "11",
    cy: "3",
    r: "2.5",
    fill: muted
  }), /*#__PURE__*/React.createElement("circle", {
    cx: "19",
    cy: "3",
    r: "2.5",
    fill: muted
  })))), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '0 16px',
      fontFamily: '-apple-system, system-ui',
      fontSize: 34,
      fontWeight: 700,
      lineHeight: '41px',
      color: text,
      letterSpacing: 0.4
    }
  }, title));
}

// ─────────────────────────────────────────────────────────────
// Grouped list (inset card, r:26) + row (52px)
// ─────────────────────────────────────────────────────────────
function IOSListRow({
  title,
  detail,
  icon,
  chevron = true,
  isLast = false,
  dark = false
}) {
  const text = dark ? '#fff' : '#000';
  const sec = dark ? 'rgba(235,235,245,0.6)' : 'rgba(60,60,67,0.6)';
  const ter = dark ? 'rgba(235,235,245,0.3)' : 'rgba(60,60,67,0.3)';
  const sep = dark ? 'rgba(84,84,88,0.65)' : 'rgba(60,60,67,0.12)';
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      minHeight: 52,
      padding: '0 16px',
      position: 'relative',
      fontFamily: '-apple-system, system-ui',
      fontSize: 17,
      letterSpacing: -0.43
    }
  }, icon && /*#__PURE__*/React.createElement("div", {
    style: {
      width: 30,
      height: 30,
      borderRadius: 7,
      background: icon,
      marginRight: 12,
      flexShrink: 0
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      color: text
    }
  }, title), detail && /*#__PURE__*/React.createElement("span", {
    style: {
      color: sec,
      marginRight: 6
    }
  }, detail), chevron && /*#__PURE__*/React.createElement("svg", {
    width: "8",
    height: "14",
    viewBox: "0 0 8 14",
    style: {
      flexShrink: 0
    }
  }, /*#__PURE__*/React.createElement("path", {
    d: "M1 1l6 6-6 6",
    stroke: ter,
    strokeWidth: "2",
    fill: "none",
    strokeLinecap: "round",
    strokeLinejoin: "round"
  })), !isLast && /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      bottom: 0,
      right: 0,
      left: icon ? 58 : 16,
      height: 0.5,
      background: sep
    }
  }));
}
function IOSList({
  header,
  children,
  dark = false
}) {
  const hc = dark ? 'rgba(235,235,245,0.6)' : 'rgba(60,60,67,0.6)';
  const bg = dark ? '#1C1C1E' : '#fff';
  return /*#__PURE__*/React.createElement("div", null, header && /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: '-apple-system, system-ui',
      fontSize: 13,
      color: hc,
      textTransform: 'uppercase',
      padding: '8px 36px 6px',
      letterSpacing: -0.08
    }
  }, header), /*#__PURE__*/React.createElement("div", {
    style: {
      background: bg,
      borderRadius: 26,
      margin: '0 16px',
      overflow: 'hidden'
    }
  }, children));
}

// ─────────────────────────────────────────────────────────────
// Device frame
// ─────────────────────────────────────────────────────────────
function IOSDevice({
  children,
  width = 402,
  height = 874,
  dark = false,
  title,
  keyboard = false
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      width,
      height,
      borderRadius: 48,
      overflow: 'hidden',
      position: 'relative',
      background: dark ? '#000' : '#F2F2F7',
      boxShadow: '0 40px 80px rgba(0,0,0,0.18), 0 0 0 1px rgba(0,0,0,0.12)',
      fontFamily: '-apple-system, system-ui, sans-serif',
      WebkitFontSmoothing: 'antialiased'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      top: 11,
      left: '50%',
      transform: 'translateX(-50%)',
      width: 126,
      height: 37,
      borderRadius: 24,
      background: '#000',
      zIndex: 50
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      top: 0,
      left: 0,
      right: 0,
      zIndex: 10
    }
  }, /*#__PURE__*/React.createElement(IOSStatusBar, {
    dark: dark
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      height: '100%',
      display: 'flex',
      flexDirection: 'column'
    }
  }, title !== undefined && /*#__PURE__*/React.createElement(IOSNavBar, {
    title: title,
    dark: dark
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      overflow: 'auto'
    }
  }, children), keyboard && /*#__PURE__*/React.createElement(IOSKeyboard, {
    dark: dark
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      bottom: 0,
      left: 0,
      right: 0,
      zIndex: 60,
      height: 34,
      display: 'flex',
      justifyContent: 'center',
      alignItems: 'flex-end',
      paddingBottom: 8,
      pointerEvents: 'none'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: 139,
      height: 5,
      borderRadius: 100,
      background: dark ? 'rgba(255,255,255,0.7)' : 'rgba(0,0,0,0.25)'
    }
  })));
}

// ─────────────────────────────────────────────────────────────
// Keyboard — iOS 26 liquid glass
// ─────────────────────────────────────────────────────────────
function IOSKeyboard({
  dark = false
}) {
  const glyph = dark ? 'rgba(255,255,255,0.7)' : '#595959';
  const sugg = dark ? 'rgba(255,255,255,0.6)' : '#333';
  const keyBg = dark ? 'rgba(255,255,255,0.22)' : 'rgba(255,255,255,0.85)';

  // special-key icons
  const icons = {
    shift: /*#__PURE__*/React.createElement("svg", {
      width: "19",
      height: "17",
      viewBox: "0 0 19 17"
    }, /*#__PURE__*/React.createElement("path", {
      d: "M9.5 1L1 9.5h4.5V16h8V9.5H18L9.5 1z",
      fill: glyph
    })),
    del: /*#__PURE__*/React.createElement("svg", {
      width: "23",
      height: "17",
      viewBox: "0 0 23 17"
    }, /*#__PURE__*/React.createElement("path", {
      d: "M7 1h13a2 2 0 012 2v11a2 2 0 01-2 2H7l-6-7.5L7 1z",
      fill: "none",
      stroke: glyph,
      strokeWidth: "1.6",
      strokeLinejoin: "round"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M10 5l7 7M17 5l-7 7",
      stroke: glyph,
      strokeWidth: "1.6",
      strokeLinecap: "round"
    })),
    ret: /*#__PURE__*/React.createElement("svg", {
      width: "20",
      height: "14",
      viewBox: "0 0 20 14"
    }, /*#__PURE__*/React.createElement("path", {
      d: "M18 1v6H4m0 0l4-4M4 7l4 4",
      fill: "none",
      stroke: "#fff",
      strokeWidth: "1.8",
      strokeLinecap: "round",
      strokeLinejoin: "round"
    }))
  };
  const key = (content, {
    w,
    flex,
    ret,
    fs = 25,
    k
  } = {}) => /*#__PURE__*/React.createElement("div", {
    key: k,
    style: {
      height: 42,
      borderRadius: 8.5,
      flex: flex ? 1 : undefined,
      width: w,
      minWidth: 0,
      background: ret ? '#08f' : keyBg,
      boxShadow: '0 1px 0 rgba(0,0,0,0.075)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      fontFamily: '-apple-system, "SF Compact", system-ui',
      fontSize: fs,
      fontWeight: 458,
      color: ret ? '#fff' : glyph
    }
  }, content);
  const row = (keys, pad = 0) => /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 6.5,
      justifyContent: 'center',
      padding: `0 ${pad}px`
    }
  }, keys.map(l => key(l, {
    flex: true,
    k: l
  })));
  return /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'relative',
      zIndex: 15,
      borderRadius: 27,
      overflow: 'hidden',
      padding: '11px 0 2px',
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      boxShadow: dark ? '0 -2px 20px rgba(0,0,0,0.09)' : '0 -1px 6px rgba(0,0,0,0.018), 0 -3px 20px rgba(0,0,0,0.012)'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      inset: 0,
      borderRadius: 27,
      backdropFilter: 'blur(12px) saturate(180%)',
      WebkitBackdropFilter: 'blur(12px) saturate(180%)',
      background: dark ? 'rgba(120,120,128,0.14)' : 'rgba(255,255,255,0.25)'
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      inset: 0,
      borderRadius: 27,
      boxShadow: dark ? 'inset 1.5px 1.5px 1px rgba(255,255,255,0.15)' : 'inset 1.5px 1.5px 1px rgba(255,255,255,0.7), inset -1px -1px 1px rgba(255,255,255,0.4)',
      border: dark ? '0.5px solid rgba(255,255,255,0.15)' : '0.5px solid rgba(0,0,0,0.06)',
      pointerEvents: 'none'
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 20,
      alignItems: 'center',
      padding: '8px 22px 13px',
      width: '100%',
      boxSizing: 'border-box',
      position: 'relative'
    }
  }, ['"The"', 'the', 'to'].map((w, i) => /*#__PURE__*/React.createElement(React.Fragment, {
    key: i
  }, i > 0 && /*#__PURE__*/React.createElement("div", {
    style: {
      width: 1,
      height: 25,
      background: '#ccc',
      opacity: 0.3
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      textAlign: 'center',
      fontFamily: '-apple-system, system-ui',
      fontSize: 17,
      color: sugg,
      letterSpacing: -0.43,
      lineHeight: '22px'
    }
  }, w)))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 13,
      padding: '0 6.5px',
      width: '100%',
      boxSizing: 'border-box',
      position: 'relative'
    }
  }, row(['q', 'w', 'e', 'r', 't', 'y', 'u', 'i', 'o', 'p']), row(['a', 's', 'd', 'f', 'g', 'h', 'j', 'k', 'l'], 20), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 14.25,
      alignItems: 'center'
    }
  }, key(icons.shift, {
    w: 45,
    k: 'shift'
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 6.5,
      flex: 1
    }
  }, ['z', 'x', 'c', 'v', 'b', 'n', 'm'].map(l => key(l, {
    flex: true,
    k: l
  }))), key(icons.del, {
    w: 45,
    k: 'del'
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 6,
      alignItems: 'center'
    }
  }, key('ABC', {
    w: 92.25,
    fs: 18,
    k: 'abc'
  }), key('', {
    flex: true,
    k: 'space'
  }), key(icons.ret, {
    w: 92.25,
    ret: true,
    k: 'ret'
  }))), /*#__PURE__*/React.createElement("div", {
    style: {
      height: 56,
      width: '100%',
      position: 'relative'
    }
  }));
}
Object.assign(window, {
  IOSDevice,
  IOSStatusBar,
  IOSNavBar,
  IOSGlassPill,
  IOSList,
  IOSListRow,
  IOSKeyboard
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/scuffed-os-ios/ios-frame.jsx", error: String((e && e.message) || e) }); }

// ui_kits/scuffed-os-ios/mobile-more.jsx
try { (() => {
/* Scuffed OS — iPhone: More menu + Fitness / Habits / People / Email screens */

function MoreScreen({
  onOpen
}) {
  const groups = [{
    label: "Health",
    items: [{
      id: "nutrition",
      lab: "Nutrition",
      sub: "1,690 kcal · 410 to go",
      icon: "apple",
      tint: "green"
    }, {
      id: "fitness",
      lab: "Fitness",
      sub: "82% recovered · Whoop",
      icon: "activity",
      tint: "clay"
    }]
  }, {
    label: "Daily",
    items: [{
      id: "habits",
      lab: "Habits",
      sub: "2 of 5 done today",
      icon: "repeat",
      tint: "honey"
    }]
  }, {
    label: "Inbox & people",
    items: [{
      id: "email",
      lab: "Email",
      sub: "4 need a reply",
      icon: "mail",
      tint: "sky"
    }, {
      id: "people",
      lab: "People",
      sub: "2 to reach out to",
      icon: "users",
      tint: "plum"
    }]
  }, {
    label: "Intelligence",
    items: [{
      id: "memory",
      lab: "Second Brain",
      sub: "142 memories",
      icon: "brain",
      tint: "green"
    }]
  }];
  return /*#__PURE__*/React.createElement("div", {
    className: "m-screen"
  }, /*#__PURE__*/React.createElement("div", {
    className: "m-head"
  }, /*#__PURE__*/React.createElement("h1", {
    className: "m-title"
  }, "More")), groups.map((g, i) => /*#__PURE__*/React.createElement("div", {
    key: i,
    className: "m-more"
  }, /*#__PURE__*/React.createElement("div", {
    className: "m-sectionhead"
  }, /*#__PURE__*/React.createElement("h3", {
    style: {
      fontSize: 13,
      textTransform: "uppercase",
      letterSpacing: "var(--tracking-caps)",
      color: "var(--text-faint)"
    }
  }, g.label)), /*#__PURE__*/React.createElement("div", {
    className: "m-menu"
  }, g.items.map(it => /*#__PURE__*/React.createElement("div", {
    className: "m-menu__row",
    key: it.id,
    onClick: () => onOpen(it.id)
  }, /*#__PURE__*/React.createElement("span", {
    className: "m-menu__ico",
    style: {
      background: `var(--${it.tint}-100)`,
      color: `var(--${it.tint}-600)`
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: it.icon
  })), /*#__PURE__*/React.createElement("span", {
    className: "m-menu__lab"
  }, /*#__PURE__*/React.createElement("b", null, it.lab), /*#__PURE__*/React.createElement("span", null, it.sub)), /*#__PURE__*/React.createElement("span", {
    className: "m-menu__chev"
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "chevron-right"
  }))))))));
}
function MobileFitness() {
  const vitals = [{
    lab: "HRV",
    val: "68",
    unit: "ms",
    icon: "activity",
    tint: "green"
  }, {
    lab: "Resting HR",
    val: "52",
    unit: "bpm",
    icon: "heart",
    tint: "clay"
  }, {
    lab: "Respiratory",
    val: "14.2",
    unit: "rpm",
    icon: "wind",
    tint: "sky"
  }, {
    lab: "Sleep",
    val: "7:38",
    unit: "hrs",
    icon: "moon",
    tint: "plum"
  }];
  const workouts = [{
    name: "Morning run",
    when: "Today · 32 min · 318 cal",
    icon: "footprints",
    tint: "green",
    strain: "9.4"
  }, {
    name: "Strength — push",
    when: "Yesterday · 48 min",
    icon: "dumbbell",
    tint: "clay",
    strain: "11.2"
  }, {
    name: "Cycling",
    when: "Mon · 1:05 · 540 cal",
    icon: "bike",
    tint: "sky",
    strain: "13.1"
  }];
  return /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement(Card, {
    style: {
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      gap: 6
    },
    action: null
  }, /*#__PURE__*/React.createElement(Badge, {
    color: "green",
    dot: true
  }, "Synced with Whoop"), /*#__PURE__*/React.createElement(ProgressRing, {
    value: 82,
    max: 100,
    size: 142,
    thickness: 13,
    color: "green",
    label: "82%",
    sublabel: "recovery"
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: 22
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "m-ring"
  }, /*#__PURE__*/React.createElement(ProgressRing, {
    value: 14.2,
    max: 21,
    size: 64,
    color: "sky",
    label: "14.2",
    sublabel: "strain"
  })), /*#__PURE__*/React.createElement("div", {
    className: "m-ring"
  }, /*#__PURE__*/React.createElement(ProgressRing, {
    value: 91,
    max: 100,
    size: 64,
    color: "plum",
    label: "91%",
    sublabel: "sleep"
  })))), /*#__PURE__*/React.createElement(Card, {
    title: "Vitals"
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-statgrid"
  }, vitals.map((v, i) => /*#__PURE__*/React.createElement("div", {
    className: "kit-statline",
    key: i
  }, /*#__PURE__*/React.createElement("span", {
    className: "kit-statline__ico",
    style: {
      background: `var(--${v.tint}-100)`,
      color: `var(--${v.tint}-600)`
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: v.icon
  })), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    className: "kit-statline__lab"
  }, v.lab), /*#__PURE__*/React.createElement("div", {
    className: "kit-statline__val"
  }, v.val, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 11,
      color: "var(--text-faint)"
    }
  }, " ", v.unit))))))), /*#__PURE__*/React.createElement(Card, {
    title: "Workouts",
    action: /*#__PURE__*/React.createElement(Badge, {
      color: "green",
      icon: /*#__PURE__*/React.createElement(Icon, {
        name: "plus"
      })
    }, "Log")
  }, workouts.map((w, i) => /*#__PURE__*/React.createElement("div", {
    className: "m-row",
    key: i
  }, /*#__PURE__*/React.createElement("span", {
    className: "m-ico",
    style: {
      background: `var(--${w.tint}-100)`,
      color: `var(--${w.tint}-600)`
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: w.icon
  })), /*#__PURE__*/React.createElement("div", {
    className: "m-row__main"
  }, /*#__PURE__*/React.createElement("p", {
    className: "m-row__title"
  }, w.name), /*#__PURE__*/React.createElement("p", {
    className: "m-row__sub"
  }, w.when)), /*#__PURE__*/React.createElement(Badge, {
    color: "sky"
  }, w.strain)))));
}
function MobileHabits() {
  const DOW = ["M", "T", "W", "T", "F", "S", "S"];
  const TODAY = 1;
  const [habits, setHabits] = React.useState([{
    id: 1,
    name: "Meditate",
    icon: "flower-2",
    tint: "green",
    streak: 12,
    days: [1, 1, 0, 0, 0, 0, 0]
  }, {
    id: 2,
    name: "Read 30 min",
    icon: "book-open",
    tint: "sky",
    streak: 5,
    days: [1, 1, 0, 0, 0, 0, 0]
  }, {
    id: 3,
    name: "Workout",
    icon: "dumbbell",
    tint: "clay",
    streak: 3,
    days: [1, 0, 0, 0, 0, 0, 0]
  }, {
    id: 4,
    name: "No phone after 10",
    icon: "moon",
    tint: "plum",
    streak: 8,
    days: [1, 1, 0, 0, 0, 0, 0]
  }, {
    id: 5,
    name: "Drink water",
    icon: "droplet",
    tint: "honey",
    streak: 2,
    days: [1, 0, 0, 0, 0, 0, 0]
  }]);
  const toggle = (id, d) => setHabits(hs => hs.map(h => h.id === id ? {
    ...h,
    days: h.days.map((v, i) => i === d ? v ? 0 : 1 : v)
  } : h));
  const doneToday = habits.filter(h => h.days[TODAY]).length;
  return /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement(Card, {
    variant: "sunken"
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: 16
    }
  }, /*#__PURE__*/React.createElement(ProgressRing, {
    value: doneToday,
    max: habits.length,
    size: 78,
    color: "green",
    label: `${doneToday}/${habits.length}`,
    sublabel: "today"
  }), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("p", {
    className: "m-row__title",
    style: {
      fontSize: 16
    }
  }, doneToday === habits.length ? "All done!" : `${habits.length - doneToday} to go`), /*#__PURE__*/React.createElement("p", {
    className: "kit-muted",
    style: {
      marginTop: 3
    }
  }, "Keep your streaks alive.")))), /*#__PURE__*/React.createElement(Card, {
    title: "This week"
  }, habits.map(h => /*#__PURE__*/React.createElement("div", {
    className: "m-habitrow",
    key: h.id
  }, /*#__PURE__*/React.createElement("span", {
    className: "m-ico",
    style: {
      background: `var(--${h.tint}-100)`,
      color: `var(--${h.tint}-600)`
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: h.icon
  })), /*#__PURE__*/React.createElement("div", {
    className: "m-row__main",
    style: {
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement("p", {
    className: "m-row__title",
    style: {
      whiteSpace: "nowrap",
      overflow: "hidden",
      textOverflow: "ellipsis"
    }
  }, h.name), /*#__PURE__*/React.createElement("p", {
    className: "m-row__sub",
    style: {
      color: "var(--honey-600)"
    }
  }, "\uD83D\uDD25 ", h.streak, " days")), /*#__PURE__*/React.createElement("div", {
    className: "m-week"
  }, h.days.map((on, di) => /*#__PURE__*/React.createElement("div", {
    key: di,
    className: "m-wd" + (on ? " on" : "") + (di === TODAY ? " today" : ""),
    style: on ? {
      background: `var(--${h.tint}-600)`
    } : null,
    onClick: () => toggle(h.id, di)
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "check"
  }))))))));
}
function MobilePeople() {
  const Strength = ({
    n
  }) => /*#__PURE__*/React.createElement("span", {
    className: "kit-strength"
  }, [0, 1, 2, 3, 4].map(i => /*#__PURE__*/React.createElement("i", {
    key: i,
    className: i < n ? "on" : ""
  })));
  const reach = [{
    name: "Jordan Lee",
    why: "You usually catch up every 2 weeks",
    tint: "green"
  }, {
    name: "Alex Mehta",
    why: "It's been 2 months",
    tint: "honey"
  }];
  const people = [{
    name: "Priya Anand",
    rel: "Colleague",
    relColor: "sky",
    last: "Talked 2 days ago",
    strength: 4,
    tint: "sky"
  }, {
    name: "Lila Rivera",
    rel: "Family",
    relColor: "plum",
    last: "Called 1 week ago",
    strength: 5,
    tint: "plum"
  }, {
    name: "Jordan Lee",
    rel: "Friend",
    relColor: "green",
    last: "3 weeks ago",
    strength: 3,
    tint: "green"
  }, {
    name: "Alex Mehta",
    rel: "Friend",
    relColor: "green",
    last: "2 months ago",
    over: true,
    strength: 2,
    tint: "honey"
  }];
  return /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement(Card, {
    title: "Reach out",
    action: /*#__PURE__*/React.createElement(Badge, {
      color: "honey",
      dot: true
    }, "2 due")
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-stack"
  }, reach.map((r, i) => /*#__PURE__*/React.createElement("div", {
    className: "kit-memory",
    key: i
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-memory__top"
  }, /*#__PURE__*/React.createElement(Avatar, {
    name: r.name,
    tint: r.tint,
    size: "sm"
  }), /*#__PURE__*/React.createElement("span", {
    className: "kit-row__title",
    style: {
      fontSize: 14
    }
  }, r.name)), /*#__PURE__*/React.createElement("p", {
    style: {
      margin: 0,
      fontSize: 13,
      color: "var(--text-muted)"
    }
  }, r.why), /*#__PURE__*/React.createElement(Button, {
    variant: "soft",
    size: "sm",
    iconLeft: /*#__PURE__*/React.createElement(Icon, {
      name: "sparkles"
    })
  }, "Draft a hello"))))), /*#__PURE__*/React.createElement(Card, {
    title: "People",
    eyebrow: "142 contacts"
  }, people.map((p, i) => /*#__PURE__*/React.createElement("div", {
    className: "kit-person",
    key: i
  }, /*#__PURE__*/React.createElement(Avatar, {
    name: p.name,
    tint: p.tint,
    size: "sm"
  }), /*#__PURE__*/React.createElement("div", {
    className: "kit-person__main"
  }, /*#__PURE__*/React.createElement("p", {
    className: "kit-person__name",
    style: {
      fontSize: 14
    }
  }, p.name), /*#__PURE__*/React.createElement("p", {
    className: "kit-person__sub",
    style: p.over ? {
      color: "var(--clay-600)"
    } : null
  }, p.last)), /*#__PURE__*/React.createElement(Strength, {
    n: p.strength
  })))));
}
function MobileEmail() {
  const emails = [{
    id: 1,
    from: "Priya Anand",
    time: "8:24am",
    cat: "Needs reply",
    unread: true,
    subject: "Lighthouse timeline — confirm the 30th?",
    summary: ["Confirm the June 30 ship date.", "Loop in design review by the 20th."],
    drafts: {
      Friendly: "Hi Priya,\n\nThe 30th works — let's lock it in. I'll schedule design review before the 20th.\n\nThanks!\nSam",
      Brief: "Hi Priya — 30th works. Design review before the 20th. — Sam"
    }
  }, {
    id: 2,
    from: "Oak St. Realty",
    time: "Yesterday",
    cat: "Needs reply",
    unread: true,
    subject: "Lease renewal — by Jun 25",
    summary: ["Decision needed by Jun 25.", "Rent holds at $1,450 for 12 months."],
    drafts: {
      Friendly: "Hi,\n\nI'd like to renew for 12 months at the current rate. Send the paperwork whenever.\n\nBest,\nSam",
      Brief: "Hi — renewing 12 months at $1,450. Send papers. — Sam"
    }
  }, {
    id: 3,
    from: "Vanguard",
    time: "Jun 5",
    cat: "FYI",
    unread: false,
    subject: "Your June statement is ready",
    summary: ["Statement available.", "Portfolio up 0.9%. No action."]
  }];
  const [selId, setSelId] = React.useState(1);
  const [tone, setTone] = React.useState("Friendly");
  const sel = emails.find(e => e.id === selId);
  return /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement(Card, {
    eyebrow: "12 new \xB7 I triaged & cleared 8",
    title: "Inbox",
    action: /*#__PURE__*/React.createElement(Badge, {
      color: "green",
      dot: true
    }, "4 need you")
  }, emails.map(e => /*#__PURE__*/React.createElement("div", {
    key: e.id,
    className: "kit-mail" + (e.id === selId ? " is-active" : ""),
    onClick: () => {
      setSelId(e.id);
      setTone("Friendly");
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "kit-mail__dot" + (e.unread ? "" : " read")
  }), /*#__PURE__*/React.createElement("div", {
    className: "kit-mail__main"
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-mail__top"
  }, /*#__PURE__*/React.createElement("span", {
    className: "kit-mail__from"
  }, e.from), /*#__PURE__*/React.createElement("span", {
    className: "kit-mail__time"
  }, e.time)), /*#__PURE__*/React.createElement("p", {
    className: "kit-mail__subj"
  }, e.subject)), /*#__PURE__*/React.createElement(Badge, {
    color: e.cat === "FYI" ? "neutral" : "honey"
  }, e.cat)))), /*#__PURE__*/React.createElement(Card, {
    eyebrow: sel.from,
    title: sel.subject
  }, /*#__PURE__*/React.createElement("p", {
    className: "sa-card__eyebrow",
    style: {
      display: "flex",
      alignItems: "center",
      gap: 6,
      marginBottom: 9
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "sparkles",
    style: {
      width: 13,
      height: 13
    }
  }), "AI summary"), /*#__PURE__*/React.createElement("div", {
    className: "kit-bullets"
  }, sel.summary.map((b, i) => /*#__PURE__*/React.createElement("div", {
    className: "kit-bullet",
    key: i
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "check"
  }), b)))), sel.drafts ? /*#__PURE__*/React.createElement(Card, {
    title: "Suggested reply",
    action: /*#__PURE__*/React.createElement("div", {
      className: "kit-cal__seg",
      style: {
        marginLeft: 0
      }
    }, ["Friendly", "Brief"].map(t => /*#__PURE__*/React.createElement("button", {
      key: t,
      className: tone === t ? "is-on" : "",
      onClick: () => setTone(t)
    }, t)))
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-draft"
  }, sel.drafts[tone]), /*#__PURE__*/React.createElement("div", {
    className: "m-pillrow",
    style: {
      marginTop: 12
    }
  }, /*#__PURE__*/React.createElement(Button, {
    variant: "primary",
    fullWidth: true,
    iconLeft: /*#__PURE__*/React.createElement(Icon, {
      name: "send"
    })
  }, "Send"), /*#__PURE__*/React.createElement(Button, {
    variant: "secondary",
    iconLeft: /*#__PURE__*/React.createElement(Icon, {
      name: "pen-line"
    })
  }, "Edit"))) : /*#__PURE__*/React.createElement(Card, {
    variant: "sunken"
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-insight"
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-insight__icon"
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "check-check"
  })), /*#__PURE__*/React.createElement("p", null, "No reply needed \u2014 filed as ", /*#__PURE__*/React.createElement("strong", null, "FYI"), "."))));
}
Object.assign(window, {
  MoreScreen,
  MobileFitness,
  MobileHabits,
  MobilePeople,
  MobileEmail
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/scuffed-os-ios/mobile-more.jsx", error: String((e && e.message) || e) }); }

// ui_kits/scuffed-os-ios/mobileapp.jsx
try { (() => {
/* Scuffed OS — iPhone app shell */
function MobileApp() {
  const LIST_COLOR = {
    Work: "sky",
    Health: "green",
    Finance: "honey",
    Personal: "plum"
  };
  const [tab, setTab] = React.useState("home");
  const [pushed, setPushed] = React.useState(null);
  const [chatOpen, setChatOpen] = React.useState(false);
  const [voiceOpen, setVoiceOpen] = React.useState(false);
  const [tasks, setTasks] = React.useState([{
    id: 1,
    label: "Reply to Priya about Lighthouse",
    group: "Today",
    due: "11:00am",
    prio: "high",
    list: "Work",
    done: false
  }, {
    id: 2,
    label: "Log lunch",
    group: "Today",
    due: "1:00pm",
    prio: "low",
    list: "Health",
    done: false
  }, {
    id: 3,
    label: "Book dentist follow-up",
    group: "Today",
    due: "Overdue",
    late: true,
    prio: "med",
    list: "Health",
    done: false
  }, {
    id: 4,
    label: "Move $120 to savings",
    group: "Today",
    due: "Today",
    prio: "med",
    list: "Finance",
    done: false
  }, {
    id: 5,
    label: "Pay rent",
    group: "Today",
    due: "Done",
    prio: "high",
    list: "Finance",
    done: true
  }, {
    id: 6,
    label: "Draft Q3 planning doc",
    group: "Upcoming",
    due: "Tomorrow",
    prio: "high",
    list: "Work",
    done: false
  }, {
    id: 7,
    label: "Order mom's birthday gift",
    group: "Upcoming",
    due: "Jun 12",
    prio: "med",
    list: "Personal",
    done: false
  }].map(t => ({
    ...t,
    listColor: LIST_COLOR[t.list]
  })));
  const toggleTask = id => setTasks(ts => ts.map(t => t.id === id ? {
    ...t,
    done: !t.done
  } : t));
  const addTask = label => setTasks(ts => [{
    id: Date.now(),
    label,
    done: false,
    group: "Today",
    due: "Today",
    prio: "med",
    list: "Personal",
    listColor: "plum"
  }, ...ts]);
  const TABS = [{
    id: "home",
    label: "Home",
    icon: "house"
  }, {
    id: "tasks",
    label: "Tasks",
    icon: "circle-check-big"
  }, {
    id: "finance",
    label: "Money",
    icon: "wallet"
  }, {
    id: "more",
    label: "More",
    icon: "layout-grid"
  }];
  const PUSH = {
    nutrition: {
      title: "Nutrition",
      el: /*#__PURE__*/React.createElement(MobileNutrition, null)
    },
    fitness: {
      title: "Fitness",
      el: /*#__PURE__*/React.createElement(MobileFitness, null)
    },
    habits: {
      title: "Habits",
      el: /*#__PURE__*/React.createElement(MobileHabits, null)
    },
    people: {
      title: "People",
      el: /*#__PURE__*/React.createElement(MobilePeople, null)
    },
    email: {
      title: "Email",
      el: /*#__PURE__*/React.createElement(MobileEmail, null)
    },
    memory: {
      title: "Second Brain",
      el: /*#__PURE__*/React.createElement(Card, {
        title: "Recent memories",
        eyebrow: "142 stored"
      }, /*#__PURE__*/React.createElement("div", {
        className: "kit-stack"
      }, [["Mom's birthday is March 14", "voice note", "plum"], ["Prefer morning workouts", "learned", "green"], ["Lighthouse deadline moved to Jun 30", "telegram", "sky"]].map((m, i) => /*#__PURE__*/React.createElement("div", {
        className: "kit-memory",
        key: i
      }, /*#__PURE__*/React.createElement("div", {
        className: "kit-memory__top"
      }, /*#__PURE__*/React.createElement("span", {
        className: "kit-cat",
        style: {
          background: `var(--${m[2]}-600)`,
          borderRadius: 999
        }
      }), /*#__PURE__*/React.createElement(Badge, {
        color: m[1] === "voice note" ? "sky" : m[1] === "telegram" ? "green" : "plum"
      }, m[1])), /*#__PURE__*/React.createElement("p", {
        style: {
          margin: 0,
          fontSize: 14
        }
      }, m[0])))))
    }
  };
  let screen;
  if (tab === "home") screen = /*#__PURE__*/React.createElement(MobileHome, {
    tasks: tasks,
    onToggleTask: toggleTask,
    onOpenAssistant: () => setChatOpen(true),
    onTab: setTab
  });else if (tab === "tasks") screen = /*#__PURE__*/React.createElement(MobileTasks, {
    tasks: tasks,
    onToggleTask: toggleTask
  });else if (tab === "finance") screen = /*#__PURE__*/React.createElement(MobileFinance, null);else screen = /*#__PURE__*/React.createElement(MoreScreen, {
    onOpen: setPushed
  });
  const navFromAction = s => {
    if (["home", "tasks", "finance"].includes(s)) setTab(s);else if (PUSH[s]) setPushed(s);else if (s === "calendar") setTab("home");
  };
  return /*#__PURE__*/React.createElement(IOSDevice, null, /*#__PURE__*/React.createElement("div", {
    className: "m-app"
  }, /*#__PURE__*/React.createElement("div", {
    className: "m-statusspace"
  }), /*#__PURE__*/React.createElement("div", {
    className: "m-scroll"
  }, screen), /*#__PURE__*/React.createElement("div", {
    className: "m-tabbar"
  }, TABS.slice(0, 2).map(t => /*#__PURE__*/React.createElement("button", {
    key: t.id,
    className: "m-tab" + (tab === t.id ? " is-on" : ""),
    onClick: () => setTab(t.id)
  }, /*#__PURE__*/React.createElement(Icon, {
    name: t.icon
  }), /*#__PURE__*/React.createElement("span", null, t.label))), /*#__PURE__*/React.createElement("div", {
    className: "m-tab--center"
  }, /*#__PURE__*/React.createElement("div", {
    className: "m-mic",
    onClick: () => setVoiceOpen(true)
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "mic"
  }))), TABS.slice(2).map(t => /*#__PURE__*/React.createElement("button", {
    key: t.id,
    className: "m-tab" + (tab === t.id ? " is-on" : ""),
    onClick: () => setTab(t.id)
  }, /*#__PURE__*/React.createElement(Icon, {
    name: t.icon
  }), /*#__PURE__*/React.createElement("span", null, t.label)))), voiceOpen && /*#__PURE__*/React.createElement(VoiceSheet, {
    onClose: () => setVoiceOpen(false),
    onCapture: addTask
  }), chatOpen && /*#__PURE__*/React.createElement(MobileAssistant, {
    onClose: () => setChatOpen(false),
    onNavigate: navFromAction,
    onCreateTask: addTask
  }), pushed && /*#__PURE__*/React.createElement("div", {
    className: "m-push"
  }, /*#__PURE__*/React.createElement("div", {
    className: "m-push__head"
  }, /*#__PURE__*/React.createElement(IconButton, {
    label: "Back",
    size: "sm",
    onClick: () => setPushed(null)
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "chevron-left"
  })), /*#__PURE__*/React.createElement("span", {
    className: "m-push__title"
  }, PUSH[pushed].title)), /*#__PURE__*/React.createElement("div", {
    className: "m-push__body"
  }, PUSH[pushed].el))));
}
ReactDOM.createRoot(document.getElementById("root")).render(/*#__PURE__*/React.createElement(MobileApp, null));
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/scuffed-os-ios/mobileapp.jsx", error: String((e && e.message) || e) }); }

// ui_kits/scuffed-os-ios/screens.jsx
try { (() => {
/* Scuffed OS — iPhone screens */

function MobileHome({
  tasks,
  onToggleTask,
  onOpenAssistant,
  onTab
}) {
  const agenda = [{
    time: "09:00",
    title: "Deep work — Q3 plan",
    meta: "Focus block",
    active: true
  }, {
    time: "11:30",
    title: "Design standup",
    meta: "Google Meet",
    active: true
  }, {
    time: "13:00",
    title: "Lunch — log it",
    meta: "Assistant reminder",
    active: false
  }];
  return /*#__PURE__*/React.createElement("div", {
    className: "m-screen"
  }, /*#__PURE__*/React.createElement("div", {
    className: "m-head"
  }, /*#__PURE__*/React.createElement("div", {
    className: "m-eyebrow"
  }, "Tuesday \xB7 June 8"), /*#__PURE__*/React.createElement("h1", {
    className: "m-title"
  }, "Good morning, Sam"), /*#__PURE__*/React.createElement("p", {
    className: "m-sub"
  }, "4 things need you today")), /*#__PURE__*/React.createElement("div", {
    className: "m-ask",
    onClick: onOpenAssistant
  }, /*#__PURE__*/React.createElement("span", {
    className: "m-ask__ico"
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "sparkles"
  })), /*#__PURE__*/React.createElement("div", {
    className: "m-ask__main"
  }, /*#__PURE__*/React.createElement("b", null, "Ask your assistant"), /*#__PURE__*/React.createElement("span", null, "Tasks, money, meals \u2014 or just talk")), /*#__PURE__*/React.createElement(Icon, {
    name: "arrow-right"
  })), /*#__PURE__*/React.createElement(Card, {
    title: "Today",
    action: /*#__PURE__*/React.createElement("button", {
      className: "m-link",
      onClick: () => onTab("tasks")
    }, "Calendar")
  }, /*#__PURE__*/React.createElement("div", {
    className: "m-agenda"
  }, agenda.map((a, i) => /*#__PURE__*/React.createElement("div", {
    key: i,
    className: "m-agenda__item" + (a.active ? "" : " m-agenda__item--muted")
  }, /*#__PURE__*/React.createElement("div", {
    className: "m-agenda__time"
  }, a.time), /*#__PURE__*/React.createElement("div", {
    className: "m-agenda__body"
  }, /*#__PURE__*/React.createElement("p", {
    className: "m-agenda__title"
  }, a.title), /*#__PURE__*/React.createElement("p", {
    className: "m-agenda__meta"
  }, a.meta)))))), /*#__PURE__*/React.createElement(Card, {
    title: "Tasks",
    action: /*#__PURE__*/React.createElement("span", {
      className: "kit-muted"
    }, tasks.filter(t => !t.done).length, " left")
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: 2
    }
  }, tasks.slice(0, 4).map(t => /*#__PURE__*/React.createElement("div", {
    key: t.id,
    style: {
      padding: "6px 0"
    }
  }, /*#__PURE__*/React.createElement(Checkbox, {
    checked: t.done,
    strikeWhenChecked: true,
    label: t.label,
    onChange: () => onToggleTask(t.id)
  }))))), /*#__PURE__*/React.createElement(Card, {
    variant: "sunken",
    title: "Nutrition",
    action: /*#__PURE__*/React.createElement("button", {
      className: "m-link",
      onClick: () => onTab("nutrition")
    }, "Details")
  }, /*#__PURE__*/React.createElement("div", {
    className: "m-rings"
  }, /*#__PURE__*/React.createElement("div", {
    className: "m-ring"
  }, /*#__PURE__*/React.createElement(ProgressRing, {
    value: 1690,
    max: 2100,
    size: 74,
    color: "green",
    label: "1690",
    sublabel: "kcal"
  }), /*#__PURE__*/React.createElement("span", {
    className: "m-ring__lab"
  }, "Calories")), /*#__PURE__*/React.createElement("div", {
    className: "m-ring"
  }, /*#__PURE__*/React.createElement(ProgressRing, {
    value: 114,
    max: 160,
    size: 74,
    color: "clay",
    label: "114g",
    sublabel: "protein"
  }), /*#__PURE__*/React.createElement("span", {
    className: "m-ring__lab"
  }, "Protein")), /*#__PURE__*/React.createElement("div", {
    className: "m-ring"
  }, /*#__PURE__*/React.createElement(ProgressRing, {
    value: 5,
    max: 8,
    size: 74,
    color: "sky",
    label: "5/8",
    sublabel: "cups"
  }), /*#__PURE__*/React.createElement("span", {
    className: "m-ring__lab"
  }, "Water")))));
}
function MobileTasks({
  tasks,
  onToggleTask
}) {
  const groups = ["Today", "Upcoming"];
  const byGroup = g => tasks.filter(t => (t.group || "Today") === g);
  return /*#__PURE__*/React.createElement("div", {
    className: "m-screen"
  }, /*#__PURE__*/React.createElement("div", {
    className: "m-head"
  }, /*#__PURE__*/React.createElement("h1", {
    className: "m-title"
  }, "Tasks"), /*#__PURE__*/React.createElement("p", {
    className: "m-sub"
  }, tasks.filter(t => !t.done).length, " open \xB7 2 done today")), /*#__PURE__*/React.createElement("div", {
    className: "m-ask",
    style: {
      background: "var(--surface-sunken)",
      color: "var(--text-faint)",
      boxShadow: "none"
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "plus"
  }), /*#__PURE__*/React.createElement("div", {
    className: "m-ask__main",
    style: {
      color: "var(--text-muted)"
    }
  }, /*#__PURE__*/React.createElement("b", {
    style: {
      color: "var(--text-strong)"
    }
  }, "Add a task"), /*#__PURE__*/React.createElement("span", {
    style: {
      color: "var(--text-faint)"
    }
  }, "or hold the mic to say it")), /*#__PURE__*/React.createElement(Badge, {
    color: "green",
    icon: /*#__PURE__*/React.createElement(Icon, {
      name: "mic"
    })
  }, "Voice")), groups.map(g => byGroup(g).length > 0 && /*#__PURE__*/React.createElement(Card, {
    key: g,
    title: g,
    action: /*#__PURE__*/React.createElement("span", {
      className: "kit-muted"
    }, byGroup(g).filter(t => !t.done).length, " open")
  }, byGroup(g).map(t => /*#__PURE__*/React.createElement("div", {
    className: "m-row",
    key: t.id
  }, /*#__PURE__*/React.createElement("span", {
    onClick: e => e.stopPropagation(),
    style: {
      display: "inline-flex"
    }
  }, /*#__PURE__*/React.createElement(Checkbox, {
    checked: t.done,
    onChange: () => onToggleTask(t.id)
  })), /*#__PURE__*/React.createElement("div", {
    className: "m-row__main"
  }, /*#__PURE__*/React.createElement("p", {
    className: "m-row__title",
    style: t.done ? {
      color: "var(--text-faint)",
      textDecoration: "line-through"
    } : null
  }, t.label), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: 8,
      marginTop: 3
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "m-cat",
    style: {
      borderRadius: 999,
      width: 8,
      height: 8,
      background: t.prio === "high" ? "var(--clay-600)" : t.prio === "med" ? "var(--honey-600)" : "var(--green-500)"
    }
  }), t.due && /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: 11,
      color: t.late ? "var(--clay-600)" : "var(--text-muted)"
    }
  }, t.due), t.list && /*#__PURE__*/React.createElement(Badge, {
    color: t.listColor || "neutral"
  }, t.list))))))));
}
function MobileFinance() {
  const [period, setPeriod] = React.useState("Month");
  const cats = [{
    name: "Groceries",
    spent: 320,
    budget: 400,
    color: "clay"
  }, {
    name: "Rent & bills",
    spent: 1450,
    budget: 1450,
    color: "honey"
  }, {
    name: "Dining out",
    spent: 186,
    budget: 250,
    color: "plum"
  }, {
    name: "Savings",
    spent: 600,
    budget: 600,
    color: "green"
  }];
  const txns = [{
    title: "Whole Foods",
    sub: "Groceries · today",
    amt: "-$64.20",
    cat: "var(--clay-600)"
  }, {
    title: "Salary",
    sub: "Acme Inc · Jun 1",
    amt: "+$3,200",
    cat: "var(--green-600)",
    pos: true
  }, {
    title: "Spotify",
    sub: "Subscriptions",
    amt: "-$11.99",
    cat: "var(--plum-600)"
  }];
  return /*#__PURE__*/React.createElement("div", {
    className: "m-screen"
  }, /*#__PURE__*/React.createElement("div", {
    className: "m-head"
  }, /*#__PURE__*/React.createElement("h1", {
    className: "m-title"
  }, "Finance")), /*#__PURE__*/React.createElement(Card, null, /*#__PURE__*/React.createElement("div", {
    className: "m-eyebrow"
  }, "Balance"), /*#__PURE__*/React.createElement("div", {
    className: "m-bigamt"
  }, "$4,820", /*#__PURE__*/React.createElement("small", null, ".50")), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 12
    }
  }, /*#__PURE__*/React.createElement(ProgressBar, {
    label: "June spending",
    meta: "$1,840 / $2,400",
    value: 1840,
    max: 2400,
    color: "clay"
  }))), /*#__PURE__*/React.createElement("div", {
    className: "m-seg"
  }, ["Week", "Month", "Year"].map(p => /*#__PURE__*/React.createElement("button", {
    key: p,
    className: period === p ? "is-on" : "",
    onClick: () => setPeriod(p)
  }, p))), /*#__PURE__*/React.createElement(Card, {
    title: "Budgets"
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: 14
    }
  }, cats.map((c, i) => /*#__PURE__*/React.createElement(ProgressBar, {
    key: i,
    label: c.name,
    value: c.spent,
    max: c.budget,
    color: c.color,
    meta: `$${c.spent} / $${c.budget}`
  })))), /*#__PURE__*/React.createElement(Card, {
    title: "Recent"
  }, txns.map((t, i) => /*#__PURE__*/React.createElement("div", {
    className: "m-row",
    key: i
  }, /*#__PURE__*/React.createElement("span", {
    className: "m-cat",
    style: {
      background: t.cat
    }
  }), /*#__PURE__*/React.createElement("div", {
    className: "m-row__main"
  }, /*#__PURE__*/React.createElement("p", {
    className: "m-row__title"
  }, t.title), /*#__PURE__*/React.createElement("p", {
    className: "m-row__sub"
  }, t.sub)), /*#__PURE__*/React.createElement("span", {
    className: "m-row__amt" + (t.pos ? " m-amt--pos" : "")
  }, t.amt)))));
}
function MobileNutrition() {
  const meals = [{
    ico: "egg",
    tint: "honey",
    name: "Greek yogurt & berries",
    time: "Breakfast",
    kcal: 320
  }, {
    ico: "sandwich",
    tint: "clay",
    name: "Chicken & avocado wrap",
    time: "Lunch",
    kcal: 540
  }, {
    ico: "apple",
    tint: "green",
    name: "Apple + almonds",
    time: "Snack",
    kcal: 210
  }];
  return /*#__PURE__*/React.createElement("div", {
    className: "m-screen"
  }, /*#__PURE__*/React.createElement("div", {
    className: "m-head"
  }, /*#__PURE__*/React.createElement("h1", {
    className: "m-title"
  }, "Nutrition")), /*#__PURE__*/React.createElement(Card, {
    style: {
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      gap: 6
    }
  }, /*#__PURE__*/React.createElement(ProgressRing, {
    value: 1690,
    max: 2100,
    size: 150,
    thickness: 14,
    color: "green",
    label: "1690",
    sublabel: "of 2100 kcal"
  }), /*#__PURE__*/React.createElement("p", {
    className: "kit-muted",
    style: {
      margin: 0
    }
  }, "410 calories left today")), /*#__PURE__*/React.createElement(Card, {
    title: "Macros"
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: 14
    }
  }, /*#__PURE__*/React.createElement(ProgressBar, {
    label: "Protein",
    value: 114,
    max: 160,
    color: "clay",
    meta: "114 / 160g"
  }), /*#__PURE__*/React.createElement(ProgressBar, {
    label: "Carbs",
    value: 148,
    max: 210,
    color: "honey",
    meta: "148 / 210g"
  }), /*#__PURE__*/React.createElement(ProgressBar, {
    label: "Fat",
    value: 52,
    max: 70,
    color: "sky",
    meta: "52 / 70g"
  }))), /*#__PURE__*/React.createElement(Card, {
    title: "Meals",
    action: /*#__PURE__*/React.createElement(Badge, {
      color: "green",
      icon: /*#__PURE__*/React.createElement(Icon, {
        name: "plus"
      })
    }, "Log")
  }, meals.map((m, i) => /*#__PURE__*/React.createElement("div", {
    className: "m-row",
    key: i
  }, /*#__PURE__*/React.createElement("span", {
    className: "m-ico",
    style: {
      background: `var(--${m.tint}-100)`,
      color: `var(--${m.tint}-600)`
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: m.ico
  })), /*#__PURE__*/React.createElement("div", {
    className: "m-row__main"
  }, /*#__PURE__*/React.createElement("p", {
    className: "m-row__title"
  }, m.name), /*#__PURE__*/React.createElement("p", {
    className: "m-row__sub"
  }, m.time)), /*#__PURE__*/React.createElement("span", {
    className: "m-row__amt"
  }, m.kcal, /*#__PURE__*/React.createElement("span", {
    style: {
      color: "var(--text-faint)",
      fontSize: 11
    }
  }, " kcal"))))));
}
Object.assign(window, {
  MobileHome,
  MobileTasks,
  MobileFinance,
  MobileNutrition
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/scuffed-os-ios/screens.jsx", error: String((e && e.message) || e) }); }

// ui_kits/scuffed-os/CRMScreen.jsx
try { (() => {
/* Scuffed OS — Personal CRM */
function CRMScreen() {
  const Strength = ({
    n
  }) => /*#__PURE__*/React.createElement("span", {
    className: "kit-strength"
  }, [0, 1, 2, 3, 4].map(i => /*#__PURE__*/React.createElement("i", {
    key: i,
    className: i < n ? "on" : ""
  })));
  const people = [{
    name: "Priya Anand",
    rel: "Colleague",
    relColor: "sky",
    last: "Talked 2 days ago",
    strength: 4,
    tint: "sky"
  }, {
    name: "Lila Rivera",
    rel: "Family",
    relColor: "plum",
    last: "Called 1 week ago",
    strength: 5,
    tint: "plum"
  }, {
    name: "Jordan Lee",
    rel: "Friend",
    relColor: "green",
    last: "3 weeks ago",
    due: true,
    strength: 3,
    tint: "green"
  }, {
    name: "Alex Mehta",
    rel: "Friend",
    relColor: "green",
    last: "2 months ago",
    over: true,
    strength: 2,
    tint: "honey"
  }, {
    name: "Dr. Chen",
    rel: "Network",
    relColor: "neutral",
    last: "5 months ago",
    over: true,
    strength: 1,
    tint: "clay"
  }];
  const reachOut = [{
    name: "Jordan Lee",
    why: "You usually catch up every 2 weeks",
    tint: "green"
  }, {
    name: "Alex Mehta",
    why: "It's been 2 months",
    tint: "honey"
  }];
  const upcoming = [{
    name: "Lila's birthday",
    when: "Jun 14 · in 5 days",
    icon: "cake",
    tint: "plum"
  }, {
    name: "Anniversary with Jo",
    when: "Jun 20 · in 11 days",
    icon: "heart",
    tint: "clay"
  }, {
    name: "Priya — work-iversary",
    when: "Jun 28",
    icon: "party-popper",
    tint: "sky"
  }];
  return /*#__PURE__*/React.createElement("div", {
    className: "kit-grid",
    style: {
      gridTemplateColumns: "1.5fr 1fr"
    }
  }, /*#__PURE__*/React.createElement(Card, {
    title: "People",
    eyebrow: "142 contacts",
    action: /*#__PURE__*/React.createElement("div", {
      className: "kit-search",
      style: {
        width: 180
      }
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "search"
    }), /*#__PURE__*/React.createElement("input", {
      placeholder: "Search people"
    }))
  }, people.map((p, i) => /*#__PURE__*/React.createElement("div", {
    className: "kit-person",
    key: i
  }, /*#__PURE__*/React.createElement(Avatar, {
    name: p.name,
    tint: p.tint
  }), /*#__PURE__*/React.createElement("div", {
    className: "kit-person__main"
  }, /*#__PURE__*/React.createElement("p", {
    className: "kit-person__name"
  }, p.name, " ", /*#__PURE__*/React.createElement(Badge, {
    color: p.relColor
  }, p.rel)), /*#__PURE__*/React.createElement("p", {
    className: "kit-person__sub",
    style: p.over ? {
      color: "var(--clay-600)"
    } : null
  }, p.last)), /*#__PURE__*/React.createElement(Strength, {
    n: p.strength
  }), /*#__PURE__*/React.createElement(IconButton, {
    label: "Draft a note"
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "pen-line"
  }))))), /*#__PURE__*/React.createElement("div", {
    className: "kit-col"
  }, /*#__PURE__*/React.createElement(Card, {
    title: "Reach out",
    eyebrow: "Assistant nudges",
    action: /*#__PURE__*/React.createElement(Badge, {
      color: "honey",
      dot: true
    }, "2 due")
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-stack"
  }, reachOut.map((r, i) => /*#__PURE__*/React.createElement("div", {
    className: "kit-memory",
    key: i
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-memory__top"
  }, /*#__PURE__*/React.createElement(Avatar, {
    name: r.name,
    tint: r.tint,
    size: "sm"
  }), /*#__PURE__*/React.createElement("span", {
    className: "kit-row__title",
    style: {
      fontSize: "var(--text-sm)"
    }
  }, r.name)), /*#__PURE__*/React.createElement("p", {
    style: {
      margin: 0,
      fontSize: "var(--text-sm)",
      color: "var(--text-muted)"
    }
  }, r.why), /*#__PURE__*/React.createElement("div", {
    className: "kit-inline"
  }, /*#__PURE__*/React.createElement(Button, {
    variant: "soft",
    size: "sm",
    iconLeft: /*#__PURE__*/React.createElement(Icon, {
      name: "sparkles"
    })
  }, "Draft a hello"), /*#__PURE__*/React.createElement(Button, {
    variant: "ghost",
    size: "sm"
  }, "Snooze")))))), /*#__PURE__*/React.createElement(Card, {
    title: "Upcoming",
    variant: "sunken"
  }, upcoming.map((u, i) => /*#__PURE__*/React.createElement("div", {
    className: "kit-row",
    key: i
  }, /*#__PURE__*/React.createElement("span", {
    className: "kit-workout__ico",
    style: {
      width: 36,
      height: 36,
      background: `var(--${u.tint}-100)`,
      color: `var(--${u.tint}-600)`
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: u.icon
  })), /*#__PURE__*/React.createElement("div", {
    className: "kit-row__main"
  }, /*#__PURE__*/React.createElement("p", {
    className: "kit-row__title"
  }, u.name), /*#__PURE__*/React.createElement("p", {
    className: "kit-row__sub"
  }, u.when)))))));
}
window.CRMScreen = CRMScreen;
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/scuffed-os/CRMScreen.jsx", error: String((e && e.message) || e) }); }

// ui_kits/scuffed-os/CalendarScreen.jsx
try { (() => {
/* Scuffed OS — Calendar (week view) */
function CalendarScreen() {
  const [view, setView] = React.useState("Week");
  const days = [{
    dow: "Mon",
    date: 7
  }, {
    dow: "Tue",
    date: 8,
    today: true
  }, {
    dow: "Wed",
    date: 9
  }, {
    dow: "Thu",
    date: 10
  }, {
    dow: "Fri",
    date: 11
  }, {
    dow: "Sat",
    date: 12
  }, {
    dow: "Sun",
    date: 13
  }];
  const START = 8,
    END = 18,
    ROW = 52; // 8:00 → 18:00
  const hours = Array.from({
    length: END - START
  }, (_, i) => START + i);
  // events keyed by day index
  const events = {
    0: [{
      t: "Design review",
      s: 10,
      e: 11,
      c: "green",
      at: "10:00"
    }, {
      t: "Gym",
      s: 17,
      e: 18,
      c: "sky",
      at: "5:00pm"
    }],
    1: [{
      t: "Deep work — Q3 plan",
      s: 9,
      e: 10.5,
      c: "green",
      at: "9:00"
    }, {
      t: "Design standup",
      s: 11.5,
      e: 12,
      c: "plum",
      at: "11:30"
    }, {
      t: "Lunch",
      s: 13,
      e: 13.5,
      c: "honey",
      at: "1:00pm"
    }, {
      t: "Dentist",
      s: 16,
      e: 17,
      c: "clay",
      at: "4:00pm"
    }],
    2: [{
      t: "1:1 with Priya",
      s: 14,
      e: 14.75,
      c: "plum",
      at: "2:00pm"
    }],
    3: [{
      t: "Lighthouse sync",
      s: 10,
      e: 11.5,
      c: "green",
      at: "10:00"
    }, {
      t: "Meal prep",
      s: 16,
      e: 17,
      c: "honey",
      at: "4:00pm"
    }],
    4: [{
      t: "Focus block",
      s: 9,
      e: 11,
      c: "green",
      at: "9:00"
    }, {
      t: "Coffee w/ Al",
      s: 15,
      e: 15.5,
      c: "sky",
      at: "3:00pm"
    }],
    5: [{
      t: "Farmers market",
      s: 9,
      e: 10,
      c: "honey",
      at: "9:00"
    }],
    6: [{
      t: "Morning run",
      s: 8,
      e: 9,
      c: "sky",
      at: "8:00"
    }]
  };
  const monthDays = [];
  // June 2026 starts on Monday June 1. Show Mon-start grid.
  for (let d = 1; d <= 30; d++) monthDays.push({
    d,
    today: d === 8,
    dot: [7, 8, 9, 10, 11, 12].includes(d)
  });
  const upNext = [{
    t: "Deep work — Q3 plan",
    when: "Now · 9:00–10:30",
    c: "green"
  }, {
    t: "Design standup",
    when: "11:30am · Google Meet",
    c: "plum"
  }, {
    t: "Lunch — log it!",
    when: "1:00pm",
    c: "honey"
  }, {
    t: "Dentist",
    when: "4:00pm · Oak Street",
    c: "clay"
  }];
  return /*#__PURE__*/React.createElement("div", {
    className: "kit-grid",
    style: {
      gridTemplateColumns: "1fr 300px"
    }
  }, /*#__PURE__*/React.createElement(Card, null, /*#__PURE__*/React.createElement("div", {
    className: "kit-cal__toolbar"
  }, /*#__PURE__*/React.createElement("span", {
    className: "kit-cal__month"
  }, "June 2026"), /*#__PURE__*/React.createElement(IconButton, {
    label: "Previous",
    size: "sm"
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "chevron-left"
  })), /*#__PURE__*/React.createElement(IconButton, {
    label: "Next",
    size: "sm"
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "chevron-right"
  })), /*#__PURE__*/React.createElement(Button, {
    variant: "secondary",
    size: "sm"
  }, "Today"), /*#__PURE__*/React.createElement("div", {
    className: "kit-cal__seg"
  }, ["Day", "Week", "Month"].map(v => /*#__PURE__*/React.createElement("button", {
    key: v,
    className: view === v ? "is-on" : "",
    onClick: () => setView(v)
  }, v)))), /*#__PURE__*/React.createElement("div", {
    className: "kit-week"
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-week__corner"
  }), days.map((d, i) => /*#__PURE__*/React.createElement("div", {
    className: "kit-week__dayhead",
    key: i
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-week__dow"
  }, d.dow), /*#__PURE__*/React.createElement("div", {
    className: "kit-week__date" + (d.today ? " is-today" : "")
  }, d.date))), /*#__PURE__*/React.createElement("div", {
    className: "kit-week__body"
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-week__hours"
  }, hours.map(h => /*#__PURE__*/React.createElement("div", {
    className: "kit-week__hour",
    key: h
  }, h > 12 ? h - 12 + "p" : h + "a"))), days.map((d, i) => /*#__PURE__*/React.createElement("div", {
    className: "kit-week__col" + (d.today ? " is-today" : ""),
    key: i
  }, hours.map(h => /*#__PURE__*/React.createElement("div", {
    className: "kit-week__row",
    key: h
  })), (events[i] || []).map((ev, j) => /*#__PURE__*/React.createElement("div", {
    key: j,
    className: "kit-event kit-ev--" + ev.c,
    style: {
      top: (ev.s - START) * ROW + 1,
      height: (ev.e - ev.s) * ROW - 3
    }
  }, /*#__PURE__*/React.createElement("b", null, ev.t), /*#__PURE__*/React.createElement("span", null, ev.at)))))))), /*#__PURE__*/React.createElement("div", {
    className: "kit-col"
  }, /*#__PURE__*/React.createElement(Card, {
    title: "June",
    action: /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        gap: 2
      }
    }, /*#__PURE__*/React.createElement(IconButton, {
      label: "Previous",
      size: "sm"
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "chevron-left"
    })), /*#__PURE__*/React.createElement(IconButton, {
      label: "Next",
      size: "sm"
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "chevron-right"
    })))
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-month"
  }, ["M", "T", "W", "T", "F", "S", "S"].map((d, i) => /*#__PURE__*/React.createElement("div", {
    className: "kit-month__dow",
    key: i
  }, d)), monthDays.map(m => /*#__PURE__*/React.createElement("div", {
    key: m.d,
    className: "kit-month__day" + (m.today ? " is-today" : "") + (m.dot ? " has-dot" : "")
  }, m.d)))), /*#__PURE__*/React.createElement(Card, {
    title: "Up next",
    variant: "sunken"
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-stack",
    style: {
      gap: 2
    }
  }, upNext.map((u, i) => /*#__PURE__*/React.createElement("div", {
    className: "kit-listrow",
    key: i
  }, /*#__PURE__*/React.createElement("span", {
    className: "kit-listrow__dot",
    style: {
      background: `var(--${u.c}-600)`
    }
  }), /*#__PURE__*/React.createElement("div", {
    className: "kit-row__main"
  }, /*#__PURE__*/React.createElement("p", {
    className: "kit-row__title",
    style: {
      fontSize: "var(--text-sm)"
    }
  }, u.t), /*#__PURE__*/React.createElement("p", {
    className: "kit-row__sub",
    style: {
      fontSize: 12
    }
  }, u.when))))))));
}
window.CalendarScreen = CalendarScreen;
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/scuffed-os/CalendarScreen.jsx", error: String((e && e.message) || e) }); }

// ui_kits/scuffed-os/ChatPanel.jsx
try { (() => {
/* Scuffed OS — Assistant chat panel (AI backend that performs tasks).
   Reply logic lives in assistant-logic.js (window.ScuffedAssistant). */
function ChatPanel({
  onClose,
  onNavigate,
  onCreateTask
}) {
  const [messages, setMessages] = React.useState([{
    id: 1,
    role: "ai",
    text: "Good morning, Sam. I've gone through your day — <strong>4 tasks</strong>, a standup at 11:30, and you're $120 under budget. Want me to handle anything?"
  }]);
  const [input, setInput] = React.useState("");
  const [typing, setTyping] = React.useState(false);
  const logRef = React.useRef(null);
  React.useEffect(() => {
    const onKey = e => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  React.useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [messages, typing]);
  const send = raw => {
    const text = (raw != null ? raw : input).trim();
    if (!text) return;
    const userMsg = {
      id: Date.now(),
      role: "user",
      text
    };
    setMessages(m => [...m, userMsg]);
    setInput("");
    setTyping(true);
    setTimeout(() => {
      const r = window.ScuffedAssistant.reply(text);
      if (r.action && r.action.makeTask && onCreateTask) onCreateTask(r.action.makeTask);
      setTyping(false);
      setMessages(m => [...m, {
        id: Date.now() + 1,
        role: "ai",
        text: r.text,
        action: r.action
      }]);
    }, 850);
  };
  const goAction = screen => {
    if (screen && onNavigate) onNavigate(screen);
    onClose();
  };
  const suggestions = ["Plan my day", "Add a task to call the dentist", "How much did I spend on dining?", "Log my breakfast"];
  return /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("div", {
    className: "kit-scrim",
    onClick: onClose
  }), /*#__PURE__*/React.createElement("aside", {
    className: "kit-drawer kit-chat",
    role: "dialog",
    "aria-label": "Assistant"
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-chat__head"
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-chat__id"
  }, /*#__PURE__*/React.createElement("img", {
    src: "../../assets/logo-mark.svg",
    alt: ""
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-chat__name"
  }, "Scuffed Assistant"), /*#__PURE__*/React.createElement("div", {
    className: "kit-chat__status"
  }, "Connected to your second brain")), /*#__PURE__*/React.createElement(IconButton, {
    label: "Close",
    size: "sm",
    onClick: onClose
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "x"
  }))), /*#__PURE__*/React.createElement("div", {
    className: "kit-chat__log",
    ref: logRef
  }, messages.map(m => /*#__PURE__*/React.createElement("div", {
    key: m.id,
    className: "kit-msg kit-msg--" + m.role
  }, m.role === "ai" && /*#__PURE__*/React.createElement("span", {
    className: "kit-msg__av"
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "sparkles"
  })), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    className: "kit-bubble",
    dangerouslySetInnerHTML: {
      __html: m.text
    }
  }), m.action && /*#__PURE__*/React.createElement("div", {
    className: "kit-action"
  }, /*#__PURE__*/React.createElement("span", {
    className: "kit-action__ico"
  }, /*#__PURE__*/React.createElement(Icon, {
    name: m.action.icon
  })), /*#__PURE__*/React.createElement("div", {
    className: "kit-action__main"
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-action__title"
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "check"
  }), m.action.title), /*#__PURE__*/React.createElement("div", {
    className: "kit-action__meta"
  }, m.action.meta)), /*#__PURE__*/React.createElement("span", {
    className: "kit-action__cta",
    onClick: () => goAction(m.action.screen)
  }, m.action.cta))))), typing && /*#__PURE__*/React.createElement("div", {
    className: "kit-msg kit-msg--ai"
  }, /*#__PURE__*/React.createElement("span", {
    className: "kit-msg__av"
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "sparkles"
  })), /*#__PURE__*/React.createElement("div", {
    className: "kit-bubble",
    style: {
      padding: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-typing"
  }, /*#__PURE__*/React.createElement("i", null), /*#__PURE__*/React.createElement("i", null), /*#__PURE__*/React.createElement("i", null))))), /*#__PURE__*/React.createElement("div", {
    className: "kit-chat__suggest"
  }, suggestions.map(s => /*#__PURE__*/React.createElement("span", {
    key: s,
    className: "kit-suggest",
    onClick: () => send(s)
  }, s))), /*#__PURE__*/React.createElement("div", {
    className: "kit-composer"
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-composer__box"
  }, /*#__PURE__*/React.createElement("textarea", {
    rows: "1",
    value: input,
    placeholder: "Ask or tell your assistant\u2026",
    onChange: e => setInput(e.target.value),
    onKeyDown: e => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        send();
      }
    }
  }), /*#__PURE__*/React.createElement(IconButton, {
    label: "Voice",
    variant: "ghost",
    size: "sm"
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "mic"
  }))), /*#__PURE__*/React.createElement(IconButton, {
    label: "Send",
    variant: "solid",
    onClick: () => send()
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "arrow-up"
  })))));
}
window.ChatPanel = ChatPanel;
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/scuffed-os/ChatPanel.jsx", error: String((e && e.message) || e) }); }

// ui_kits/scuffed-os/DashboardScreen.jsx
try { (() => {
/* Scuffed OS — Dashboard (home overview) */
function DashboardScreen({
  tasks,
  onToggleTask,
  voiceNotes
}) {
  const agenda = [{
    time: "09:00",
    title: "Deep work — Q3 planning",
    meta: "Focus block",
    active: true
  }, {
    time: "11:30",
    title: "Standup with design",
    meta: "Google Meet",
    icon: "video",
    active: true
  }, {
    time: "13:00",
    title: "Lunch — log it!",
    meta: "Assistant reminder",
    icon: "utensils",
    active: false
  }, {
    time: "16:00",
    title: "Dentist",
    meta: "12 Oak Street",
    icon: "map-pin",
    active: false
  }];
  const txns = [{
    title: "Whole Foods",
    sub: "Groceries · 8:42am",
    amt: "-$64.20",
    cat: "var(--clay-600)"
  }, {
    title: "Salary",
    sub: "Acme Inc · deposit",
    amt: "+$3,200",
    cat: "var(--green-600)",
    pos: true
  }, {
    title: "Spotify",
    sub: "Subscriptions",
    amt: "-$11.99",
    cat: "var(--plum-600)"
  }];
  return /*#__PURE__*/React.createElement("div", {
    className: "kit-grid kit-grid--dash"
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-col"
  }, /*#__PURE__*/React.createElement(Card, {
    eyebrow: "Tuesday \xB7 June 8",
    title: "Today's agenda",
    action: /*#__PURE__*/React.createElement(IconButton, {
      label: "Open calendar",
      size: "sm"
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "arrow-up-right"
    }))
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-agenda"
  }, agenda.map((a, i) => /*#__PURE__*/React.createElement("div", {
    key: i,
    className: `kit-agenda__item ${a.active ? "" : "kit-agenda__item--muted"}`
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-agenda__time"
  }, a.time), /*#__PURE__*/React.createElement("div", {
    className: "kit-agenda__body"
  }, /*#__PURE__*/React.createElement("p", {
    className: "kit-agenda__title"
  }, a.title), /*#__PURE__*/React.createElement("p", {
    className: "kit-agenda__meta"
  }, a.icon && /*#__PURE__*/React.createElement(Icon, {
    name: a.icon
  }), a.meta)))))), /*#__PURE__*/React.createElement(Card, {
    title: "Finance snapshot",
    action: /*#__PURE__*/React.createElement(Badge, {
      color: "green",
      dot: true
    }, "On budget")
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-spread",
    style: {
      marginBottom: 18
    }
  }, /*#__PURE__*/React.createElement(Stat, {
    label: "Balance",
    value: "$4,820",
    delta: "+3.2% this week",
    trend: "up"
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      maxWidth: 230
    }
  }, /*#__PURE__*/React.createElement(ProgressBar, {
    label: "June spending",
    meta: "$1,840 / $2,400",
    value: 1840,
    max: 2400,
    color: "clay"
  }))), txns.map((t, i) => /*#__PURE__*/React.createElement("div", {
    className: "kit-row",
    key: i
  }, /*#__PURE__*/React.createElement("span", {
    className: "kit-cat",
    style: {
      background: t.cat
    }
  }), /*#__PURE__*/React.createElement("div", {
    className: "kit-row__main"
  }, /*#__PURE__*/React.createElement("p", {
    className: "kit-row__title"
  }, t.title), /*#__PURE__*/React.createElement("p", {
    className: "kit-row__sub"
  }, t.sub)), /*#__PURE__*/React.createElement("span", {
    className: `kit-row__amt ${t.pos ? "kit-amt--pos" : "kit-amt--neg"}`
  }, t.amt))))), /*#__PURE__*/React.createElement("div", {
    className: "kit-col"
  }, /*#__PURE__*/React.createElement(Card, {
    eyebrow: "Captured 4 min ago",
    title: "Your assistant noticed",
    action: /*#__PURE__*/React.createElement(Icon, {
      name: "sparkles"
    })
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-insight"
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-insight__icon"
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "lightbulb"
  })), /*#__PURE__*/React.createElement("p", null, "You've skipped logging ", /*#__PURE__*/React.createElement("strong", null, "lunch"), " twice this week. Want me to set a gentle 1pm reminder and pre-fill your usual?")), /*#__PURE__*/React.createElement("div", {
    className: "kit-inline",
    style: {
      marginTop: 14
    }
  }, /*#__PURE__*/React.createElement(Button, {
    variant: "soft",
    size: "sm",
    iconLeft: /*#__PURE__*/React.createElement(Icon, {
      name: "check"
    })
  }, "Yes, do it"), /*#__PURE__*/React.createElement(Button, {
    variant: "ghost",
    size: "sm"
  }, "Not now"))), /*#__PURE__*/React.createElement(Card, {
    title: "Tasks",
    action: /*#__PURE__*/React.createElement("span", {
      className: "kit-muted"
    }, tasks.filter(t => !t.done).length, " left")
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-stack",
    style: {
      gap: 4
    }
  }, tasks.map(t => /*#__PURE__*/React.createElement("div", {
    key: t.id,
    style: {
      padding: "7px 0"
    }
  }, /*#__PURE__*/React.createElement(Checkbox, {
    checked: t.done,
    strikeWhenChecked: true,
    label: t.label,
    onChange: () => onToggleTask(t.id)
  }))))), /*#__PURE__*/React.createElement(Card, {
    title: "Nutrition",
    variant: "sunken"
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-rings"
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-ring-cell"
  }, /*#__PURE__*/React.createElement(ProgressRing, {
    value: 1840,
    max: 2100,
    size: 78,
    color: "green",
    label: "1840",
    sublabel: "kcal"
  }), /*#__PURE__*/React.createElement("span", {
    className: "kit-ring-cell__lab"
  }, "Calories")), /*#__PURE__*/React.createElement("div", {
    className: "kit-ring-cell"
  }, /*#__PURE__*/React.createElement(ProgressRing, {
    value: 138,
    max: 160,
    size: 78,
    color: "clay",
    label: "138g",
    sublabel: "protein"
  }), /*#__PURE__*/React.createElement("span", {
    className: "kit-ring-cell__lab"
  }, "Protein")), /*#__PURE__*/React.createElement("div", {
    className: "kit-ring-cell"
  }, /*#__PURE__*/React.createElement(ProgressRing, {
    value: 5,
    max: 8,
    size: 78,
    color: "sky",
    label: "5/8",
    sublabel: "cups"
  }), /*#__PURE__*/React.createElement("span", {
    className: "kit-ring-cell__lab"
  }, "Water"))))));
}
window.DashboardScreen = DashboardScreen;
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/scuffed-os/DashboardScreen.jsx", error: String((e && e.message) || e) }); }

// ui_kits/scuffed-os/EmailScreen.jsx
try { (() => {
/* Scuffed OS — Email triage & response drafting */
function EmailScreen() {
  const emails = [{
    id: 1,
    from: "Priya Anand",
    time: "8:24am",
    cat: "Needs reply",
    unread: true,
    tint: "sky",
    subject: "Lighthouse timeline — can we confirm the 30th?",
    snippet: "Wanted to lock the new ship date before I update the roadmap…",
    summary: ["Priya wants to confirm the June 30 ship date.", "She needs it before updating the public roadmap.", "Asking you to loop in design review by the 20th."],
    drafts: {
      Friendly: "Hi Priya,\n\nThe 30th works on my end — let's lock it in. I'll get design review scheduled before the 20th and send you the calendar invite today.\n\nThanks for keeping this moving!\nSam",
      Brief: "Hi Priya — 30th works. I'll set up design review before the 20th and send the invite today. — Sam",
      Formal: "Hi Priya,\n\nConfirming June 30 works. I'll arrange the design review ahead of the 20th and forward an invitation shortly.\n\nBest,\nSam"
    }
  }, {
    id: 2,
    from: "Oak St. Realty",
    time: "Yesterday",
    cat: "Needs reply",
    unread: true,
    tint: "honey",
    subject: "Lease renewal — action needed by Jun 25",
    snippet: "Your lease is up for renewal. Please confirm whether you intend to…",
    summary: ["Lease renews; they need your decision by Jun 25.", "Rent stays at $1,450 if you renew for 12 months.", "Month-to-month would increase to $1,610."],
    drafts: {
      Friendly: "Hi,\n\nThanks for the heads up — I'd like to renew for another 12 months at the current rate. Happy to sign whenever the paperwork's ready.\n\nBest,\nSam",
      Brief: "Hi — I'll renew for 12 months at $1,450. Send the paperwork whenever. — Sam",
      Formal: "Hello,\n\nI would like to renew for a 12-month term at the current rate of $1,450. Please send the renewal documents at your convenience.\n\nRegards,\nSam"
    }
  }, {
    id: 3,
    from: "Jordan Lee",
    time: "Tue",
    cat: "Needs reply",
    unread: false,
    tint: "green",
    subject: "Dinner this weekend?",
    snippet: "It's been ages! Free Saturday for that ramen place we talked about?",
    summary: ["Jordan's inviting you to dinner Saturday.", "Suggesting the ramen place you'd discussed.", "It's been a while since you caught up."],
    drafts: {
      Friendly: "Yes!! Saturday's perfect — I've been craving that ramen. 7pm? Can't wait to catch up.\n\n— Sam",
      Brief: "Saturday works — 7pm at the ramen place? — Sam",
      Formal: "Hi Jordan,\n\nSaturday works well. Shall we say 7pm at the ramen restaurant?\n\nBest,\nSam"
    }
  }, {
    id: 4,
    from: "Vanguard",
    time: "Jun 5",
    cat: "FYI",
    unread: false,
    tint: "clay",
    subject: "Your June statement is ready",
    snippet: "Your account statement for the period ending May 31 is now available…",
    summary: ["Monthly statement is available.", "Portfolio up 0.9% for the period.", "No action required."]
  }, {
    id: 5,
    from: "Figma",
    time: "Jun 4",
    cat: "FYI",
    unread: false,
    tint: "plum",
    subject: "What's new this month",
    snippet: "New cursor chat, dev mode updates, and more in this month's roundup…",
    summary: ["Product newsletter — feature roundup.", "Highlights: cursor chat, dev mode updates.", "No action required."]
  }];
  const [selId, setSelId] = React.useState(1);
  const [tone, setTone] = React.useState("Friendly");
  const sel = emails.find(e => e.id === selId);
  const cats = ["Needs reply", "FYI"];
  return /*#__PURE__*/React.createElement("div", {
    className: "kit-grid",
    style: {
      gridTemplateColumns: "1fr 1.15fr"
    }
  }, /*#__PURE__*/React.createElement(Card, {
    title: "Inbox",
    eyebrow: "12 new \xB7 I triaged & cleared 8",
    action: /*#__PURE__*/React.createElement(Badge, {
      color: "green",
      dot: true
    }, "4 need you")
  }, cats.map(c => /*#__PURE__*/React.createElement("div", {
    key: c
  }, /*#__PURE__*/React.createElement("p", {
    className: "sa-card__eyebrow",
    style: {
      margin: "12px 0 4px"
    }
  }, c), emails.filter(e => e.cat === c).map(e => /*#__PURE__*/React.createElement("div", {
    key: e.id,
    className: "kit-mail" + (e.id === selId ? " is-active" : ""),
    onClick: () => {
      setSelId(e.id);
      setTone("Friendly");
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "kit-mail__dot" + (e.unread ? "" : " read")
  }), /*#__PURE__*/React.createElement("div", {
    className: "kit-mail__main"
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-mail__top"
  }, /*#__PURE__*/React.createElement("span", {
    className: "kit-mail__from"
  }, e.from), /*#__PURE__*/React.createElement("span", {
    className: "kit-mail__time"
  }, e.time)), /*#__PURE__*/React.createElement("p", {
    className: "kit-mail__subj"
  }, e.subject), /*#__PURE__*/React.createElement("p", {
    className: "kit-mail__snip"
  }, e.snippet))))))), /*#__PURE__*/React.createElement("div", {
    className: "kit-col"
  }, /*#__PURE__*/React.createElement(Card, {
    eyebrow: sel.from,
    title: sel.subject,
    action: /*#__PURE__*/React.createElement(IconButton, {
      label: "Archive"
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "archive"
    }))
  }, /*#__PURE__*/React.createElement("p", {
    className: "sa-card__eyebrow",
    style: {
      display: "flex",
      alignItems: "center",
      gap: 6,
      marginBottom: 10
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "sparkles",
    style: {
      width: 13,
      height: 13
    }
  }), "AI summary"), /*#__PURE__*/React.createElement("div", {
    className: "kit-bullets"
  }, sel.summary.map((b, i) => /*#__PURE__*/React.createElement("div", {
    className: "kit-bullet",
    key: i
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "check"
  }), b)))), sel.drafts ? /*#__PURE__*/React.createElement(Card, {
    title: "Suggested reply",
    action: /*#__PURE__*/React.createElement("div", {
      className: "kit-cal__seg",
      style: {
        marginLeft: 0
      }
    }, ["Friendly", "Brief", "Formal"].map(t => /*#__PURE__*/React.createElement("button", {
      key: t,
      className: tone === t ? "is-on" : "",
      onClick: () => setTone(t)
    }, t)))
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-draft"
  }, sel.drafts[tone]), /*#__PURE__*/React.createElement("div", {
    className: "kit-inline",
    style: {
      marginTop: 14
    }
  }, /*#__PURE__*/React.createElement(Button, {
    variant: "primary",
    iconLeft: /*#__PURE__*/React.createElement(Icon, {
      name: "send"
    })
  }, "Send"), /*#__PURE__*/React.createElement(Button, {
    variant: "secondary",
    iconLeft: /*#__PURE__*/React.createElement(Icon, {
      name: "pen-line"
    })
  }, "Edit"), /*#__PURE__*/React.createElement(Button, {
    variant: "ghost",
    iconLeft: /*#__PURE__*/React.createElement(Icon, {
      name: "refresh-cw"
    })
  }, "Regenerate"))) : /*#__PURE__*/React.createElement(Card, {
    variant: "sunken"
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-insight"
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-insight__icon"
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "check-check"
  })), /*#__PURE__*/React.createElement("p", null, "No reply needed \u2014 I've filed this as ", /*#__PURE__*/React.createElement("strong", null, "FYI"), ". Archive it or keep for later.")), /*#__PURE__*/React.createElement("div", {
    className: "kit-inline",
    style: {
      marginTop: 12
    }
  }, /*#__PURE__*/React.createElement(Button, {
    variant: "soft",
    size: "sm",
    iconLeft: /*#__PURE__*/React.createElement(Icon, {
      name: "archive"
    })
  }, "Archive")))));
}
window.EmailScreen = EmailScreen;
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/scuffed-os/EmailScreen.jsx", error: String((e && e.message) || e) }); }

// ui_kits/scuffed-os/FinanceScreen.jsx
try { (() => {
/* Scuffed OS — Finance tracker */
function FinanceScreen() {
  const cats = [{
    name: "Groceries",
    spent: 320,
    budget: 400,
    color: "clay"
  }, {
    name: "Rent & bills",
    spent: 1450,
    budget: 1450,
    color: "honey"
  }, {
    name: "Dining out",
    spent: 186,
    budget: 250,
    color: "plum"
  }, {
    name: "Transport",
    spent: 64,
    budget: 150,
    color: "sky"
  }, {
    name: "Savings",
    spent: 600,
    budget: 600,
    color: "green"
  }];
  const txns = [{
    title: "Acme Inc",
    sub: "Salary · Jun 1",
    amt: "+$3,200.00",
    cat: "var(--green-600)",
    pos: true
  }, {
    title: "Whole Foods",
    sub: "Groceries · Jun 8",
    amt: "-$64.20",
    cat: "var(--clay-600)"
  }, {
    title: "Oak St. Realty",
    sub: "Rent · Jun 3",
    amt: "-$1,450.00",
    cat: "var(--honey-600)"
  }, {
    title: "Vanguard",
    sub: "Auto-invest · Jun 5",
    amt: "-$500.00",
    cat: "var(--sky-600)"
  }];
  // net worth breakdown
  const nw = [{
    name: "Investments",
    val: 86200,
    color: "var(--green-600)"
  }, {
    name: "Retirement",
    val: 21400,
    color: "var(--sky-600)"
  }, {
    name: "Cash",
    val: 18050,
    color: "var(--honey-600)"
  }, {
    name: "Crypto",
    val: 3400,
    color: "var(--plum-600)"
  }];
  const nwTotal = nw.reduce((s, x) => s + x.val, 0);
  const holdings = [{
    sym: "VTI",
    name: "Total Market ETF",
    val: "$48,200",
    chg: "+1.2%",
    up: true,
    tint: "green"
  }, {
    sym: "AAPL",
    name: "Apple Inc.",
    val: "$22,640",
    chg: "+0.6%",
    up: true,
    tint: "sky"
  }, {
    sym: "401k",
    name: "Retirement",
    val: "$21,400",
    chg: "+0.9%",
    up: true,
    tint: "honey"
  }, {
    sym: "BTC",
    name: "Bitcoin",
    val: "$3,400",
    chg: "−2.4%",
    up: false,
    tint: "plum"
  }];
  const subs = [{
    name: "Netflix",
    price: "$15.49",
    cycle: "monthly",
    renews: "Jun 12",
    soon: true,
    color: "var(--clay-600)",
    letter: "N"
  }, {
    name: "Spotify",
    price: "$11.99",
    cycle: "monthly",
    renews: "Jun 18",
    color: "var(--green-600)",
    letter: "S"
  }, {
    name: "iCloud+",
    price: "$2.99",
    cycle: "monthly",
    renews: "Jun 24",
    color: "var(--sky-600)",
    letter: "i"
  }, {
    name: "Notion",
    price: "$96.00",
    cycle: "yearly",
    renews: "Jul 2",
    soon: true,
    color: "var(--plum-600)",
    letter: "N"
  }, {
    name: "ChatGPT",
    price: "$20.00",
    cycle: "monthly",
    renews: "Jun 28",
    color: "var(--honey-600)",
    letter: "G"
  }];
  const bills = [{
    name: "Rent",
    sub: "Oak St. Realty",
    amt: "$1,450",
    due: "Due Jul 1",
    auto: true,
    icon: "house",
    tint: "honey"
  }, {
    name: "Electric",
    sub: "ConEd",
    amt: "$82",
    due: "Due Jun 14",
    auto: true,
    icon: "zap",
    tint: "clay"
  }, {
    name: "Internet",
    sub: "Verizon Fios",
    amt: "$70",
    due: "Due Jun 16",
    auto: true,
    icon: "wifi",
    tint: "sky"
  }, {
    name: "Phone",
    sub: "Mint Mobile",
    amt: "$30",
    due: "Due Jun 20",
    auto: false,
    icon: "smartphone",
    tint: "plum"
  }];
  return /*#__PURE__*/React.createElement("div", {
    className: "kit-stack",
    style: {
      gap: "var(--gutter)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-grid",
    style: {
      gridTemplateColumns: "repeat(3, 1fr)"
    }
  }, /*#__PURE__*/React.createElement(Card, null, /*#__PURE__*/React.createElement(Stat, {
    label: "Balance",
    value: "$4,820",
    unit: ".50",
    delta: "+3.2%",
    trend: "up",
    icon: /*#__PURE__*/React.createElement(Icon, {
      name: "wallet"
    })
  })), /*#__PURE__*/React.createElement(Card, null, /*#__PURE__*/React.createElement(Stat, {
    label: "Income \xB7 June",
    value: "$3,200",
    delta: "on track",
    trend: "flat",
    icon: /*#__PURE__*/React.createElement(Icon, {
      name: "arrow-down-left"
    })
  })), /*#__PURE__*/React.createElement(Card, null, /*#__PURE__*/React.createElement(Stat, {
    label: "Spent \xB7 June",
    value: "$1,840",
    delta: "\u221212% vs May",
    trend: "down",
    icon: /*#__PURE__*/React.createElement(Icon, {
      name: "arrow-up-right"
    })
  }))), /*#__PURE__*/React.createElement("div", {
    className: "kit-grid",
    style: {
      gridTemplateColumns: "1.15fr 1fr"
    }
  }, /*#__PURE__*/React.createElement(Card, {
    eyebrow: "Net worth",
    title: "$129,050",
    action: /*#__PURE__*/React.createElement(Badge, {
      color: "green",
      dot: true
    }, "+2.1% this month")
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-nwbar",
    style: {
      marginTop: 4
    }
  }, nw.map((s, i) => /*#__PURE__*/React.createElement("i", {
    key: i,
    style: {
      width: s.val / nwTotal * 100 + "%",
      background: s.color
    }
  }))), /*#__PURE__*/React.createElement("div", {
    className: "kit-nwleg",
    style: {
      marginTop: 14
    }
  }, nw.map((s, i) => /*#__PURE__*/React.createElement("div", {
    className: "kit-nwleg__item",
    key: i
  }, /*#__PURE__*/React.createElement("span", {
    className: "kit-nwleg__dot",
    style: {
      background: s.color
    }
  }), /*#__PURE__*/React.createElement("span", {
    className: "kit-muted",
    style: {
      color: "var(--text-body)"
    }
  }, s.name), /*#__PURE__*/React.createElement("span", {
    className: "kit-nwleg__val"
  }, "$", (s.val / 1000).toFixed(1), "k"))))), /*#__PURE__*/React.createElement(Card, {
    title: "Investments",
    action: /*#__PURE__*/React.createElement(Stat, {
      label: "Today",
      value: "+$640",
      trend: "up",
      delta: "+0.5%"
    })
  }, holdings.map((h, i) => /*#__PURE__*/React.createElement("div", {
    className: "kit-hold",
    key: i
  }, /*#__PURE__*/React.createElement("span", {
    className: "kit-hold__sym",
    style: {
      background: `var(--${h.tint}-100)`,
      color: `var(--${h.tint}-600)`
    }
  }, h.sym.length > 3 ? h.sym.slice(0, 3) : h.sym), /*#__PURE__*/React.createElement("div", {
    className: "kit-row__main"
  }, /*#__PURE__*/React.createElement("p", {
    className: "kit-row__title"
  }, h.name), /*#__PURE__*/React.createElement("p", {
    className: "kit-row__sub"
  }, h.sym)), /*#__PURE__*/React.createElement("div", {
    style: {
      textAlign: "right"
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-row__amt"
  }, h.val), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: 11,
      color: h.up ? "var(--green-600)" : "var(--clay-600)"
    }
  }, h.chg)))))), /*#__PURE__*/React.createElement("div", {
    className: "kit-grid",
    style: {
      gridTemplateColumns: "1fr 1.2fr"
    }
  }, /*#__PURE__*/React.createElement(Card, {
    title: "Budgets",
    eyebrow: "June",
    action: /*#__PURE__*/React.createElement(IconButton, {
      label: "Edit budgets",
      size: "sm"
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "sliders-horizontal"
    }))
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-stack",
    style: {
      marginTop: 4
    }
  }, cats.map((c, i) => /*#__PURE__*/React.createElement(ProgressBar, {
    key: i,
    label: c.name,
    value: c.spent,
    max: c.budget,
    color: c.color,
    meta: `$${c.spent.toLocaleString()} / $${c.budget.toLocaleString()}`
  }))), /*#__PURE__*/React.createElement("div", {
    className: "kit-insight",
    style: {
      marginTop: 18
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-insight__icon"
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "trending-up"
  })), /*#__PURE__*/React.createElement("p", null, "You're ", /*#__PURE__*/React.createElement("strong", null, "$120 under"), " your dining budget. Roll it into savings?"))), /*#__PURE__*/React.createElement(Card, {
    title: "Recent transactions",
    action: /*#__PURE__*/React.createElement(Button, {
      variant: "ghost",
      size: "sm",
      iconRight: /*#__PURE__*/React.createElement(Icon, {
        name: "arrow-right"
      })
    }, "All")
  }, txns.map((t, i) => /*#__PURE__*/React.createElement("div", {
    className: "kit-row",
    key: i
  }, /*#__PURE__*/React.createElement("span", {
    className: "kit-cat",
    style: {
      background: t.cat
    }
  }), /*#__PURE__*/React.createElement("div", {
    className: "kit-row__main"
  }, /*#__PURE__*/React.createElement("p", {
    className: "kit-row__title"
  }, t.title), /*#__PURE__*/React.createElement("p", {
    className: "kit-row__sub"
  }, t.sub)), /*#__PURE__*/React.createElement("span", {
    className: `kit-row__amt ${t.pos ? "kit-amt--pos" : "kit-amt--neg"}`
  }, t.amt))))), /*#__PURE__*/React.createElement("div", {
    className: "kit-grid",
    style: {
      gridTemplateColumns: "1fr 1fr"
    }
  }, /*#__PURE__*/React.createElement(Card, {
    title: "Subscriptions",
    eyebrow: "$58 / mo \xB7 $96 / yr",
    action: /*#__PURE__*/React.createElement(Badge, {
      color: "honey",
      dot: true
    }, "2 renew soon")
  }, subs.map((s, i) => /*#__PURE__*/React.createElement("div", {
    className: "kit-sub",
    key: i
  }, /*#__PURE__*/React.createElement("span", {
    className: "kit-sub__logo",
    style: {
      background: s.color
    }
  }, s.letter), /*#__PURE__*/React.createElement("div", {
    className: "kit-sub__main"
  }, /*#__PURE__*/React.createElement("p", {
    className: "kit-row__title"
  }, s.name), /*#__PURE__*/React.createElement("p", {
    className: "kit-row__sub"
  }, s.price, " \xB7 ", s.cycle)), s.soon ? /*#__PURE__*/React.createElement(Badge, {
    color: "honey",
    icon: /*#__PURE__*/React.createElement(Icon, {
      name: "bell"
    })
  }, "Renews ", s.renews) : /*#__PURE__*/React.createElement("span", {
    className: "kit-row__sub",
    style: {
      fontFamily: "var(--font-mono)"
    }
  }, "Renews ", s.renews)))), /*#__PURE__*/React.createElement(Card, {
    title: "Bills & recurring",
    eyebrow: "June",
    action: /*#__PURE__*/React.createElement("span", {
      className: "kit-muted"
    }, "$1,632 due")
  }, bills.map((b, i) => /*#__PURE__*/React.createElement("div", {
    className: "kit-sub",
    key: i
  }, /*#__PURE__*/React.createElement("span", {
    className: "kit-workout__ico",
    style: {
      width: 38,
      height: 38,
      background: `var(--${b.tint}-100)`,
      color: `var(--${b.tint}-600)`
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: b.icon
  })), /*#__PURE__*/React.createElement("div", {
    className: "kit-sub__main"
  }, /*#__PURE__*/React.createElement("p", {
    className: "kit-row__title"
  }, b.name), /*#__PURE__*/React.createElement("p", {
    className: "kit-row__sub"
  }, b.sub, " \xB7 ", b.due)), /*#__PURE__*/React.createElement("div", {
    style: {
      textAlign: "right",
      display: "flex",
      flexDirection: "column",
      alignItems: "flex-end",
      gap: 3
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "kit-row__amt"
  }, b.amt), b.auto ? /*#__PURE__*/React.createElement(Badge, {
    color: "green"
  }, "Autopay") : /*#__PURE__*/React.createElement(Badge, {
    color: "clay"
  }, "Manual")))))));
}
window.FinanceScreen = FinanceScreen;
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/scuffed-os/FinanceScreen.jsx", error: String((e && e.message) || e) }); }

// ui_kits/scuffed-os/FitnessScreen.jsx
try { (() => {
/* Scuffed OS — Fitness & workout log (syncs with Whoop) */
function FitnessScreen() {
  const vitals = [{
    lab: "HRV",
    val: "68",
    unit: "ms",
    icon: "activity",
    tint: "green",
    delta: "+6"
  }, {
    lab: "Resting HR",
    val: "52",
    unit: "bpm",
    icon: "heart",
    tint: "clay",
    delta: "−2"
  }, {
    lab: "Respiratory",
    val: "14.2",
    unit: "rpm",
    icon: "wind",
    tint: "sky",
    delta: ""
  }, {
    lab: "Sleep",
    val: "7:38",
    unit: "hrs",
    icon: "moon",
    tint: "plum",
    delta: "+0:24"
  }];
  const workouts = [{
    name: "Morning run",
    when: "Today · 6:10am",
    icon: "footprints",
    tint: "green",
    strain: "9.4",
    dur: "32 min",
    cal: "318",
    hr: "148"
  }, {
    name: "Strength — push",
    when: "Yesterday · 7:05pm",
    icon: "dumbbell",
    tint: "clay",
    strain: "11.2",
    dur: "48 min",
    cal: "286",
    hr: "121"
  }, {
    name: "Cycling",
    when: "Mon · 6:30am",
    icon: "bike",
    tint: "sky",
    strain: "13.1",
    dur: "1:05",
    cal: "540",
    hr: "139"
  }, {
    name: "Yoga & mobility",
    when: "Sun · 8:00am",
    icon: "flower-2",
    tint: "plum",
    strain: "4.8",
    dur: "25 min",
    cal: "96",
    hr: "92"
  }];
  const week = [{
    d: "M",
    v: 0.62
  }, {
    d: "T",
    v: 0.74
  }, {
    d: "W",
    v: 0.45
  }, {
    d: "T",
    v: 0.83
  }, {
    d: "F",
    v: 0.68
  }, {
    d: "S",
    v: 0.91
  }, {
    d: "S",
    v: 0.5,
    hi: true
  }];
  return /*#__PURE__*/React.createElement("div", {
    className: "kit-stack",
    style: {
      gap: "var(--gutter)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-grid",
    style: {
      gridTemplateColumns: "1.3fr 1fr"
    }
  }, /*#__PURE__*/React.createElement(Card, {
    eyebrow: "Synced with Whoop \xB7 6:42am",
    title: "Today",
    action: /*#__PURE__*/React.createElement(Badge, {
      color: "green",
      dot: true
    }, "Recovered")
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-rings",
    style: {
      justifyContent: "space-around",
      marginTop: 6
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-ring-cell"
  }, /*#__PURE__*/React.createElement(ProgressRing, {
    value: 82,
    max: 100,
    size: 108,
    thickness: 12,
    color: "green",
    label: "82%",
    sublabel: "recovery"
  }), /*#__PURE__*/React.createElement("span", {
    className: "kit-ring-cell__lab"
  }, "Recovery")), /*#__PURE__*/React.createElement("div", {
    className: "kit-ring-cell"
  }, /*#__PURE__*/React.createElement(ProgressRing, {
    value: 14.2,
    max: 21,
    size: 108,
    thickness: 12,
    color: "sky",
    label: "14.2",
    sublabel: "of 21"
  }), /*#__PURE__*/React.createElement("span", {
    className: "kit-ring-cell__lab"
  }, "Day strain")), /*#__PURE__*/React.createElement("div", {
    className: "kit-ring-cell"
  }, /*#__PURE__*/React.createElement(ProgressRing, {
    value: 91,
    max: 100,
    size: 108,
    thickness: 12,
    color: "plum",
    label: "91%",
    sublabel: "quality"
  }), /*#__PURE__*/React.createElement("span", {
    className: "kit-ring-cell__lab"
  }, "Sleep")))), /*#__PURE__*/React.createElement(Card, {
    title: "Vitals",
    action: /*#__PURE__*/React.createElement(IconButton, {
      label: "History",
      size: "sm"
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "chart-line"
    }))
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-statgrid",
    style: {
      marginTop: 4
    }
  }, vitals.map((v, i) => /*#__PURE__*/React.createElement("div", {
    className: "kit-statline",
    key: i
  }, /*#__PURE__*/React.createElement("span", {
    className: "kit-statline__ico",
    style: {
      background: `var(--${v.tint}-100)`,
      color: `var(--${v.tint}-600)`
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: v.icon
  })), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    className: "kit-statline__lab"
  }, v.lab), /*#__PURE__*/React.createElement("div", {
    className: "kit-statline__val"
  }, v.val, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 11,
      color: "var(--text-faint)"
    }
  }, " ", v.unit), v.delta && /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-sans)",
      fontSize: 11,
      fontWeight: 600,
      color: "var(--green-600)",
      marginLeft: 6
    }
  }, v.delta)))))))), /*#__PURE__*/React.createElement("div", {
    className: "kit-grid",
    style: {
      gridTemplateColumns: "1.3fr 1fr"
    }
  }, /*#__PURE__*/React.createElement(Card, {
    title: "Workouts",
    action: /*#__PURE__*/React.createElement(Button, {
      variant: "soft",
      size: "sm",
      iconLeft: /*#__PURE__*/React.createElement(Icon, {
        name: "plus"
      })
    }, "Log workout")
  }, workouts.map((w, i) => /*#__PURE__*/React.createElement("div", {
    className: "kit-row",
    key: i
  }, /*#__PURE__*/React.createElement("span", {
    className: "kit-workout__ico",
    style: {
      background: `var(--${w.tint}-100)`,
      color: `var(--${w.tint}-600)`
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: w.icon
  })), /*#__PURE__*/React.createElement("div", {
    className: "kit-row__main"
  }, /*#__PURE__*/React.createElement("p", {
    className: "kit-row__title"
  }, w.name), /*#__PURE__*/React.createElement("p", {
    className: "kit-row__sub"
  }, w.when, " \xB7 ", w.dur, " \xB7 ", w.cal, " cal \xB7 ", w.hr, " bpm")), /*#__PURE__*/React.createElement(Badge, {
    color: "sky"
  }, w.strain)))), /*#__PURE__*/React.createElement(Card, {
    title: "Weekly strain",
    variant: "sunken",
    action: /*#__PURE__*/React.createElement("span", {
      className: "kit-muted"
    }, "avg 8.9")
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-chart"
  }, week.map((c, i) => /*#__PURE__*/React.createElement("div", {
    className: "kit-chart__col",
    key: i
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-chart__bar" + (c.hi ? " kit-chart__bar--hi" : ""),
    style: {
      height: c.v * 100 + "%"
    }
  }), /*#__PURE__*/React.createElement("span", {
    className: "kit-chart__lab"
  }, c.d)))), /*#__PURE__*/React.createElement("div", {
    className: "kit-insight",
    style: {
      marginTop: 14
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-insight__icon"
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "sparkles"
  })), /*#__PURE__*/React.createElement("p", null, "Recovery is high \u2014 a good day for a ", /*#__PURE__*/React.createElement("strong", null, "hard session"), ". Want me to schedule one?")))));
}
window.FitnessScreen = FitnessScreen;
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/scuffed-os/FitnessScreen.jsx", error: String((e && e.message) || e) }); }

// ui_kits/scuffed-os/HabitsScreen.jsx
try { (() => {
/* Scuffed OS — Habit tracker */
function HabitsScreen() {
  const DOW = ["M", "T", "W", "T", "F", "S", "S"];
  const TODAY = 1; // Tuesday
  const [habits, setHabits] = React.useState([{
    id: 1,
    name: "Meditate",
    icon: "flower-2",
    tint: "green",
    streak: 12,
    days: [true, true, false, false, false, false, false]
  }, {
    id: 2,
    name: "Read 30 min",
    icon: "book-open",
    tint: "sky",
    streak: 5,
    days: [true, true, false, false, false, false, false]
  }, {
    id: 3,
    name: "Workout",
    icon: "dumbbell",
    tint: "clay",
    streak: 3,
    days: [true, false, false, false, false, false, false]
  }, {
    id: 4,
    name: "No phone after 10",
    icon: "moon",
    tint: "plum",
    streak: 8,
    days: [true, true, false, false, false, false, false]
  }, {
    id: 5,
    name: "Drink 8 cups water",
    icon: "droplet",
    tint: "honey",
    streak: 2,
    days: [true, false, false, false, false, false, false]
  }]);
  const toggle = (hid, day) => setHabits(hs => hs.map(h => h.id === hid ? {
    ...h,
    days: h.days.map((d, i) => i === day ? !d : d)
  } : h));
  const doneToday = habits.filter(h => h.days[TODAY]).length;
  const bestStreak = Math.max.apply(null, habits.map(h => h.streak));
  return /*#__PURE__*/React.createElement("div", {
    className: "kit-grid",
    style: {
      gridTemplateColumns: "1.5fr 1fr"
    }
  }, /*#__PURE__*/React.createElement(Card, {
    title: "This week",
    eyebrow: "Tap to mark complete",
    action: /*#__PURE__*/React.createElement(Button, {
      variant: "soft",
      size: "sm",
      iconLeft: /*#__PURE__*/React.createElement(Icon, {
        name: "plus"
      })
    }, "New habit")
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-habits"
  }, /*#__PURE__*/React.createElement("div", null), DOW.map((d, i) => /*#__PURE__*/React.createElement("div", {
    className: "kit-habits__dow",
    key: i,
    style: i === TODAY ? {
      color: "var(--accent-text)"
    } : null
  }, d)), habits.map(h => /*#__PURE__*/React.createElement(React.Fragment, {
    key: h.id
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-habits__name"
  }, /*#__PURE__*/React.createElement("span", {
    className: "kit-habits__ico",
    style: {
      background: `var(--${h.tint}-100)`,
      color: `var(--${h.tint}-600)`
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: h.icon
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-habits__title"
  }, h.name), /*#__PURE__*/React.createElement("div", {
    className: "kit-habits__streak"
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "flame"
  }), h.streak, " day streak"))), h.days.map((done, di) => /*#__PURE__*/React.createElement("div", {
    key: di,
    className: "kit-hcell" + (done ? " is-done" : "") + (di === TODAY ? " is-today" : ""),
    style: done ? {
      background: `var(--${h.tint}-600)`
    } : null,
    onClick: () => toggle(h.id, di)
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "check"
  }))))))), /*#__PURE__*/React.createElement("div", {
    className: "kit-col"
  }, /*#__PURE__*/React.createElement(Card, {
    title: "Today",
    variant: "sunken"
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: 18
    }
  }, /*#__PURE__*/React.createElement(ProgressRing, {
    value: doneToday,
    max: habits.length,
    size: 92,
    thickness: 11,
    color: "green",
    label: `${doneToday}/${habits.length}`,
    sublabel: "done"
  }), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("p", {
    className: "kit-row__title",
    style: {
      fontSize: "var(--text-md)"
    }
  }, doneToday === habits.length ? "All done — nice!" : `${habits.length - doneToday} to go`), /*#__PURE__*/React.createElement("p", {
    className: "kit-muted",
    style: {
      marginTop: 4
    }
  }, "Keep your streaks alive before midnight.")))), /*#__PURE__*/React.createElement(Card, {
    title: "Streaks"
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-spread",
    style: {
      marginBottom: 14
    }
  }, /*#__PURE__*/React.createElement(Stat, {
    label: "Best streak",
    value: bestStreak,
    unit: "days",
    icon: /*#__PURE__*/React.createElement(Icon, {
      name: "flame"
    })
  }), /*#__PURE__*/React.createElement(Stat, {
    label: "This week",
    value: "68%",
    trend: "up",
    delta: "+9%"
  })), /*#__PURE__*/React.createElement("div", {
    className: "kit-insight"
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-insight__icon"
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "sparkles"
  })), /*#__PURE__*/React.createElement("p", null, "You're most consistent in the ", /*#__PURE__*/React.createElement("strong", null, "morning"), ". Want me to stack \u201CRead\u201D right after \u201CMeditate\u201D?")))));
}
window.HabitsScreen = HabitsScreen;
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/scuffed-os/HabitsScreen.jsx", error: String((e && e.message) || e) }); }

// ui_kits/scuffed-os/MemoryScreen.jsx
try { (() => {
/* Scuffed OS — Second Brain (AI memory) */
function MemoryScreen({
  voiceNotes
}) {
  const memories = [{
    text: "Mom's birthday is March 14 — she mentioned wanting that ceramics class.",
    src: "voice note",
    tags: ["family", "gifts"],
    color: "plum"
  }, {
    text: "Prefer morning workouts; energy dips after 8pm. Schedule deep work before noon.",
    src: "learned",
    tags: ["health", "routine"],
    color: "green"
  }, {
    text: "Project Lighthouse deadline moved to June 30. Loop in Priya before the 20th.",
    src: "telegram",
    tags: ["work"],
    color: "sky"
  }, {
    text: "Trying to cut dining out to twice a week. Cook salmon more often.",
    src: "voice note",
    tags: ["finance", "nutrition"],
    color: "clay"
  }];
  const tagColor = {
    family: "plum",
    gifts: "plum",
    health: "green",
    routine: "green",
    work: "sky",
    finance: "clay",
    nutrition: "honey"
  };
  return /*#__PURE__*/React.createElement("div", {
    className: "kit-grid",
    style: {
      gridTemplateColumns: "1.5fr 1fr"
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-col"
  }, /*#__PURE__*/React.createElement(Card, null, /*#__PURE__*/React.createElement("div", {
    className: "kit-inline",
    style: {
      gap: 12
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "kit-insight__icon",
    style: {
      width: 42,
      height: 42
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "sparkles"
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1
    }
  }, /*#__PURE__*/React.createElement("input", {
    className: "kit-search",
    style: {
      width: "100%",
      border: "none",
      boxShadow: "none",
      background: "transparent",
      padding: 0,
      fontSize: "var(--text-md)",
      color: "var(--text-strong)"
    },
    placeholder: "Ask anything \u2014 \u201Cwhat did I say about the Lighthouse deadline?\u201D"
  })), /*#__PURE__*/React.createElement(Button, {
    variant: "primary",
    size: "sm",
    iconRight: /*#__PURE__*/React.createElement(Icon, {
      name: "corner-down-left"
    })
  }, "Ask"))), /*#__PURE__*/React.createElement(Card, {
    title: "Recent memories",
    eyebrow: "142 stored",
    action: /*#__PURE__*/React.createElement(Badge, {
      color: "green",
      dot: true
    }, "Learning")
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-stack"
  }, memories.map((m, i) => /*#__PURE__*/React.createElement("div", {
    className: "kit-memory",
    key: i
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-memory__top"
  }, /*#__PURE__*/React.createElement("span", {
    className: "kit-cat",
    style: {
      background: `var(--${m.color}-600)`
    }
  }), /*#__PURE__*/React.createElement(Badge, {
    color: m.color
  }, m.src), /*#__PURE__*/React.createElement("span", {
    className: "kit-memory__src"
  }, "2 days ago")), /*#__PURE__*/React.createElement("p", null, m.text), /*#__PURE__*/React.createElement("div", {
    className: "kit-tags"
  }, m.tags.map(t => /*#__PURE__*/React.createElement(Badge, {
    key: t,
    color: tagColor[t] || "neutral"
  }, "#", t)))))))), /*#__PURE__*/React.createElement("div", {
    className: "kit-col"
  }, /*#__PURE__*/React.createElement(Card, {
    eyebrow: "Telegram",
    title: "Voice inbox",
    action: /*#__PURE__*/React.createElement(IconButton, {
      label: "Record",
      variant: "solid",
      size: "sm"
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "mic"
    }))
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-voice kit-voice--idle",
    style: {
      marginBottom: 14
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "kit-insight__icon",
    style: {
      background: "var(--green-600)",
      color: "#fff"
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "mic"
  })), /*#__PURE__*/React.createElement("div", {
    className: "kit-voice__wave"
  }, Array.from({
    length: 22
  }).map((_, i) => /*#__PURE__*/React.createElement("i", {
    key: i,
    style: {
      height: 6 + i % 5 * 4,
      animationDelay: i * 0.05 + "s"
    }
  }))), /*#__PURE__*/React.createElement("div", {
    className: "kit-voice__label"
  }, /*#__PURE__*/React.createElement("b", null, "Send from anywhere"), "@scuffed_os_bot")), voiceNotes.map((v, i) => /*#__PURE__*/React.createElement("div", {
    className: "kit-row",
    key: i
  }, /*#__PURE__*/React.createElement("span", {
    className: "kit-meal__ico",
    style: {
      width: 34,
      height: 34,
      background: "var(--green-100)",
      color: "var(--green-700)"
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "audio-lines"
  })), /*#__PURE__*/React.createElement("div", {
    className: "kit-row__main"
  }, /*#__PURE__*/React.createElement("p", {
    className: "kit-row__title",
    style: {
      fontWeight: 500,
      fontSize: "var(--text-sm)"
    }
  }, v.text), /*#__PURE__*/React.createElement("p", {
    className: "kit-row__sub"
  }, v.time, " \xB7 ", v.len)), v.done && /*#__PURE__*/React.createElement(Icon, {
    name: "check-check"
  })))), /*#__PURE__*/React.createElement(Card, {
    title: "Connections",
    variant: "sunken"
  }, /*#__PURE__*/React.createElement("p", {
    className: "kit-muted",
    style: {
      marginBottom: 12
    }
  }, "Topics your brain links most"), /*#__PURE__*/React.createElement("div", {
    className: "kit-tags"
  }, [["nutrition", "honey", 28], ["work", "sky", 41], ["family", "plum", 12], ["health", "green", 33], ["finance", "clay", 19]].map(([t, c, n]) => /*#__PURE__*/React.createElement(Badge, {
    key: t,
    color: c
  }, "#", t, " ", /*#__PURE__*/React.createElement("span", {
    style: {
      opacity: 0.6,
      fontFamily: "var(--font-mono)"
    }
  }, n)))))));
}
window.MemoryScreen = MemoryScreen;
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/scuffed-os/MemoryScreen.jsx", error: String((e && e.message) || e) }); }

// ui_kits/scuffed-os/NutritionScreen.jsx
try { (() => {
/* Scuffed OS — Nutrition tracker */
function NutritionScreen() {
  const meals = [{
    ico: "egg",
    tint: "honey",
    name: "Greek yogurt & berries",
    time: "Breakfast · 8:10am",
    kcal: 320,
    p: 24
  }, {
    ico: "sandwich",
    tint: "clay",
    name: "Chicken & avocado wrap",
    time: "Lunch · 1:05pm",
    kcal: 540,
    p: 38
  }, {
    ico: "apple",
    tint: "green",
    name: "Apple + almonds",
    time: "Snack · 3:30pm",
    kcal: 210,
    p: 7
  }, {
    ico: "utensils",
    tint: "plum",
    name: "Salmon, rice & greens",
    time: "Dinner · 7:20pm",
    kcal: 620,
    p: 45
  }];
  const week = [{
    d: "M",
    v: 0.82
  }, {
    d: "T",
    v: 0.94
  }, {
    d: "W",
    v: 0.71
  }, {
    d: "T",
    v: 0.88
  }, {
    d: "F",
    v: 1.0
  }, {
    d: "S",
    v: 0.64
  }, {
    d: "S",
    v: 0.87,
    hi: true
  }];
  return /*#__PURE__*/React.createElement("div", {
    className: "kit-stack",
    style: {
      gap: "var(--gutter)"
    }
  }, /*#__PURE__*/React.createElement(Card, {
    title: "Today's goals",
    eyebrow: "2,100 kcal target"
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-rings",
    style: {
      justifyContent: "space-between"
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-ring-cell"
  }, /*#__PURE__*/React.createElement(ProgressRing, {
    value: 1690,
    max: 2100,
    size: 104,
    thickness: 11,
    color: "green",
    label: "1690",
    sublabel: "of 2100 kcal"
  }), /*#__PURE__*/React.createElement("span", {
    className: "kit-ring-cell__lab"
  }, "Calories")), /*#__PURE__*/React.createElement("div", {
    className: "kit-ring-cell"
  }, /*#__PURE__*/React.createElement(ProgressRing, {
    value: 114,
    max: 160,
    size: 104,
    thickness: 11,
    color: "clay",
    label: "114g",
    sublabel: "of 160g"
  }), /*#__PURE__*/React.createElement("span", {
    className: "kit-ring-cell__lab"
  }, "Protein")), /*#__PURE__*/React.createElement("div", {
    className: "kit-ring-cell"
  }, /*#__PURE__*/React.createElement(ProgressRing, {
    value: 148,
    max: 210,
    size: 104,
    thickness: 11,
    color: "honey",
    label: "148g",
    sublabel: "of 210g"
  }), /*#__PURE__*/React.createElement("span", {
    className: "kit-ring-cell__lab"
  }, "Carbs")), /*#__PURE__*/React.createElement("div", {
    className: "kit-ring-cell"
  }, /*#__PURE__*/React.createElement(ProgressRing, {
    value: 52,
    max: 70,
    size: 104,
    thickness: 11,
    color: "sky",
    label: "52g",
    sublabel: "of 70g"
  }), /*#__PURE__*/React.createElement("span", {
    className: "kit-ring-cell__lab"
  }, "Fat")))), /*#__PURE__*/React.createElement("div", {
    className: "kit-grid",
    style: {
      gridTemplateColumns: "1.4fr 1fr"
    }
  }, /*#__PURE__*/React.createElement(Card, {
    title: "Meals",
    action: /*#__PURE__*/React.createElement(Button, {
      variant: "soft",
      size: "sm",
      iconLeft: /*#__PURE__*/React.createElement(Icon, {
        name: "plus"
      })
    }, "Log meal")
  }, meals.map((m, i) => /*#__PURE__*/React.createElement("div", {
    className: "kit-meal",
    key: i
  }, /*#__PURE__*/React.createElement("span", {
    className: "kit-meal__ico",
    style: {
      background: `var(--${m.tint}-100)`,
      color: `var(--${m.tint}-600)`
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: m.ico
  })), /*#__PURE__*/React.createElement("div", {
    className: "kit-row__main"
  }, /*#__PURE__*/React.createElement("p", {
    className: "kit-row__title"
  }, m.name), /*#__PURE__*/React.createElement("p", {
    className: "kit-row__sub"
  }, m.time)), /*#__PURE__*/React.createElement("div", {
    style: {
      textAlign: "right"
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-row__amt"
  }, m.kcal, /*#__PURE__*/React.createElement("span", {
    style: {
      color: "var(--text-faint)",
      fontSize: 12
    }
  }, " kcal")), /*#__PURE__*/React.createElement("div", {
    className: "kit-muted",
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: 11
    }
  }, m.p, "g protein"))))), /*#__PURE__*/React.createElement("div", {
    className: "kit-col"
  }, /*#__PURE__*/React.createElement(Card, {
    title: "Water",
    action: /*#__PURE__*/React.createElement(Badge, {
      color: "sky"
    }, "5 / 8 cups")
  }, /*#__PURE__*/React.createElement(ProgressBar, {
    value: 5,
    max: 8,
    color: "sky",
    meta: "3 cups to go"
  }), /*#__PURE__*/React.createElement("div", {
    className: "kit-inline",
    style: {
      marginTop: 14
    }
  }, /*#__PURE__*/React.createElement(Button, {
    variant: "secondary",
    size: "sm",
    iconLeft: /*#__PURE__*/React.createElement(Icon, {
      name: "plus"
    })
  }, "Add a cup"))), /*#__PURE__*/React.createElement(Card, {
    title: "This week",
    variant: "sunken"
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-chart"
  }, week.map((c, i) => /*#__PURE__*/React.createElement("div", {
    className: "kit-chart__col",
    key: i
  }, /*#__PURE__*/React.createElement("div", {
    className: `kit-chart__bar ${c.hi ? "kit-chart__bar--hi" : ""}`,
    style: {
      height: c.v * 100 + "%"
    }
  }), /*#__PURE__*/React.createElement("span", {
    className: "kit-chart__lab"
  }, c.d)))), /*#__PURE__*/React.createElement("p", {
    className: "kit-muted",
    style: {
      marginTop: 10
    }
  }, "Avg ", /*#__PURE__*/React.createElement("strong", {
    style: {
      color: "var(--text-strong)"
    }
  }, "1,940 kcal"), " \xB7 goal met 5 / 7 days")))));
}
window.NutritionScreen = NutritionScreen;
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/scuffed-os/NutritionScreen.jsx", error: String((e && e.message) || e) }); }

// ui_kits/scuffed-os/Sidebar.jsx
try { (() => {
/* Scuffed OS — Sidebar nav */
function Sidebar({
  active,
  onNavigate
}) {
  const sections = [{
    items: [{
      id: "home",
      label: "Home",
      icon: "house"
    }, {
      id: "calendar",
      label: "Calendar",
      icon: "calendar",
      badge: "3"
    }, {
      id: "tasks",
      label: "Tasks",
      icon: "circle-check-big",
      badge: "5"
    }, {
      id: "habits",
      label: "Habits",
      icon: "repeat"
    }]
  }, {
    label: "Health",
    items: [{
      id: "nutrition",
      label: "Nutrition",
      icon: "apple"
    }, {
      id: "fitness",
      label: "Fitness",
      icon: "activity"
    }]
  }, {
    label: "Money",
    items: [{
      id: "finance",
      label: "Finance",
      icon: "wallet"
    }]
  }, {
    label: "Inbox & people",
    items: [{
      id: "email",
      label: "Email",
      icon: "mail",
      badge: "4"
    }, {
      id: "people",
      label: "People",
      icon: "users"
    }]
  }, {
    label: "Intelligence",
    items: [{
      id: "memory",
      label: "Second Brain",
      icon: "brain"
    }]
  }];
  const Item = it => /*#__PURE__*/React.createElement("button", {
    key: it.id,
    className: `kit-navitem ${active === it.id ? "kit-navitem--active" : ""}`,
    onClick: () => onNavigate(it.id)
  }, /*#__PURE__*/React.createElement(Icon, {
    name: it.icon
  }), /*#__PURE__*/React.createElement("span", null, it.label), it.badge && /*#__PURE__*/React.createElement("span", {
    className: "kit-navitem__badge"
  }, it.badge));
  return /*#__PURE__*/React.createElement("nav", {
    className: "kit-sidebar"
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-sidebar__logo"
  }, /*#__PURE__*/React.createElement("img", {
    src: "../../assets/logo-mark.svg",
    alt: ""
  }), /*#__PURE__*/React.createElement("span", {
    className: "kit-sidebar__word"
  }, "Scuffed ", /*#__PURE__*/React.createElement("span", null, "OS"))), /*#__PURE__*/React.createElement("div", {
    className: "kit-sidebar__nav"
  }, sections.map((s, i) => /*#__PURE__*/React.createElement(React.Fragment, {
    key: i
  }, s.label && /*#__PURE__*/React.createElement("div", {
    className: "kit-navlabel"
  }, s.label), s.items.map(Item)))), /*#__PURE__*/React.createElement("button", {
    className: "kit-navitem",
    onClick: () => onNavigate("settings")
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "settings"
  }), /*#__PURE__*/React.createElement("span", null, "Settings")), /*#__PURE__*/React.createElement("div", {
    className: "kit-sidebar__user"
  }, /*#__PURE__*/React.createElement(Avatar, {
    name: "Sam Rivera",
    size: "sm",
    tint: "green"
  }), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    className: "nm"
  }, "Sam Rivera"), /*#__PURE__*/React.createElement("div", {
    className: "sub"
  }, "Synced \xB7 just now"))));
}
window.Sidebar = Sidebar;
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/scuffed-os/Sidebar.jsx", error: String((e && e.message) || e) }); }

// ui_kits/scuffed-os/TaskDetail.jsx
try { (() => {
/* Scuffed OS — Task detail drawer */
const TASK_LISTS = [{
  name: "Work",
  color: "sky"
}, {
  name: "Health",
  color: "green"
}, {
  name: "Finance",
  color: "honey"
}, {
  name: "Personal",
  color: "plum"
}];
function fileIcon(name) {
  const ext = (name.split(".").pop() || "").toLowerCase();
  if (["png", "jpg", "jpeg", "gif", "webp", "svg", "heic"].includes(ext)) return {
    icon: "image",
    tint: "plum"
  };
  if (["pdf"].includes(ext)) return {
    icon: "file-text",
    tint: "clay"
  };
  if (["doc", "docx", "txt", "md", "pages"].includes(ext)) return {
    icon: "file-text",
    tint: "sky"
  };
  if (["xls", "xlsx", "csv", "numbers"].includes(ext)) return {
    icon: "table",
    tint: "green"
  };
  if (["mp3", "wav", "m4a", "ogg"].includes(ext)) return {
    icon: "audio-lines",
    tint: "honey"
  };
  return {
    icon: "file",
    tint: "green"
  };
}
function fmtSize(bytes) {
  if (bytes == null) return "";
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(0) + " KB";
  return (bytes / 1024 / 1024).toFixed(1) + " MB";
}
function TaskDetail({
  task,
  onUpdate,
  onClose
}) {
  const [subInput, setSubInput] = React.useState("");
  const [remInput, setRemInput] = React.useState("");
  const [addingRem, setAddingRem] = React.useState(false);
  const fileRef = React.useRef(null);
  React.useEffect(() => {
    const onKey = e => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  const patch = p => onUpdate(task.id, p);
  const subs = task.subtasks || [];
  const reminders = task.reminders || [];
  const files = task.files || [];
  const subsDone = subs.filter(s => s.done).length;
  const addSub = () => {
    if (!subInput.trim()) return;
    patch({
      subtasks: [...subs, {
        id: Date.now(),
        label: subInput.trim(),
        done: false
      }]
    });
    setSubInput("");
  };
  const toggleSub = id => patch({
    subtasks: subs.map(s => s.id === id ? {
      ...s,
      done: !s.done
    } : s)
  });
  const delSub = id => patch({
    subtasks: subs.filter(s => s.id !== id)
  });
  const addRem = () => {
    if (remInput.trim()) patch({
      reminders: [...reminders, remInput.trim()]
    });
    setRemInput("");
    setAddingRem(false);
  };
  const presetRems = ["1 hour before", "9:00am", "Tonight"];
  const onFiles = e => {
    const picked = Array.from(e.target.files || []).map(f => ({
      id: Date.now() + Math.random(),
      name: f.name,
      size: f.size
    }));
    if (picked.length) patch({
      files: [...files, ...picked]
    });
    e.target.value = "";
  };
  const delFile = id => patch({
    files: files.filter(f => f.id !== id)
  });
  const PRIOS = [["low", "Low", "var(--green-500)"], ["med", "Medium", "var(--honey-600)"], ["high", "High", "var(--clay-600)"]];
  return /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("div", {
    className: "kit-scrim",
    onClick: onClose
  }), /*#__PURE__*/React.createElement("aside", {
    className: "kit-drawer",
    role: "dialog",
    "aria-label": "Task details"
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-drawer__head"
  }, /*#__PURE__*/React.createElement(Badge, {
    color: task.listColor || "neutral"
  }, task.list), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1
    }
  }), /*#__PURE__*/React.createElement(IconButton, {
    label: "Close",
    size: "sm",
    onClick: onClose
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "x"
  }))), /*#__PURE__*/React.createElement("div", {
    className: "kit-drawer__body"
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-dtitle" + (task.done ? " kit-dtitle--done" : "")
  }, /*#__PURE__*/React.createElement(Checkbox, {
    checked: task.done,
    onChange: () => patch({
      done: !task.done
    })
  }), /*#__PURE__*/React.createElement("input", {
    value: task.label,
    onChange: e => patch({
      label: e.target.value
    }),
    placeholder: "Task name"
  })), /*#__PURE__*/React.createElement("div", {
    className: "kit-field"
  }, /*#__PURE__*/React.createElement("span", {
    className: "kit-field__label"
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "align-left"
  }), "Description"), /*#__PURE__*/React.createElement("textarea", {
    className: "kit-desc",
    value: task.description || "",
    placeholder: "Add more detail\u2026",
    onChange: e => patch({
      description: e.target.value
    })
  })), /*#__PURE__*/React.createElement("div", {
    className: "kit-field"
  }, /*#__PURE__*/React.createElement("span", {
    className: "kit-field__label"
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "folder"
  }), "List"), /*#__PURE__*/React.createElement("div", {
    className: "kit-chips"
  }, TASK_LISTS.map(l => {
    const on = task.list === l.name;
    return /*#__PURE__*/React.createElement("span", {
      key: l.name,
      className: "kit-pick" + (on ? " is-on" : ""),
      style: on ? {
        background: `var(--${l.color}-100)`,
        borderColor: `var(--${l.color}-300, var(--border-soft))`
      } : undefined,
      onClick: () => patch({
        list: l.name,
        listColor: l.color
      })
    }, /*#__PURE__*/React.createElement("span", {
      className: "kit-pick__dot",
      style: {
        background: `var(--${l.color}-600)`
      }
    }), l.name, on && /*#__PURE__*/React.createElement(Icon, {
      name: "check"
    }));
  }))), /*#__PURE__*/React.createElement("div", {
    className: "kit-field"
  }, /*#__PURE__*/React.createElement("span", {
    className: "kit-field__label"
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "list-checks"
  }), "Subtasks ", subs.length > 0 && /*#__PURE__*/React.createElement("span", {
    style: {
      color: "var(--text-disabled)",
      fontWeight: 600
    }
  }, "\xB7 ", subsDone, "/", subs.length)), /*#__PURE__*/React.createElement("div", null, subs.map(s => /*#__PURE__*/React.createElement("div", {
    className: "kit-subtask" + (s.done ? " kit-subtask--done" : ""),
    key: s.id
  }, /*#__PURE__*/React.createElement(Checkbox, {
    checked: s.done,
    onChange: () => toggleSub(s.id)
  }), /*#__PURE__*/React.createElement("span", {
    className: "kit-subtask__txt"
  }, s.label), /*#__PURE__*/React.createElement("span", {
    className: "kit-subtask__del",
    onClick: () => delSub(s.id)
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "trash-2"
  }))))), /*#__PURE__*/React.createElement("div", {
    className: "kit-addrow"
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "plus"
  }), /*#__PURE__*/React.createElement("input", {
    value: subInput,
    onChange: e => setSubInput(e.target.value),
    onKeyDown: e => e.key === "Enter" && addSub(),
    placeholder: "Add a subtask\u2026"
  }))), /*#__PURE__*/React.createElement("div", {
    className: "kit-field"
  }, /*#__PURE__*/React.createElement("span", {
    className: "kit-field__label"
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "flag"
  }), "Priority"), /*#__PURE__*/React.createElement("div", {
    className: "kit-seg"
  }, PRIOS.map(([val, lbl, col]) => /*#__PURE__*/React.createElement("button", {
    key: val,
    className: task.prio === val ? "is-on" : "",
    onClick: () => patch({
      prio: val
    })
  }, /*#__PURE__*/React.createElement("span", {
    className: "kit-prio",
    style: {
      background: col
    }
  }), lbl)))), /*#__PURE__*/React.createElement("div", {
    className: "kit-field"
  }, /*#__PURE__*/React.createElement("span", {
    className: "kit-field__label"
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "calendar"
  }), "Deadline"), /*#__PURE__*/React.createElement("div", {
    className: "kit-deadline"
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "calendar-days"
  }), /*#__PURE__*/React.createElement("input", {
    type: "date",
    value: task.deadline || "",
    onChange: e => patch({
      deadline: e.target.value
    })
  }))), /*#__PURE__*/React.createElement("div", {
    className: "kit-field"
  }, /*#__PURE__*/React.createElement("span", {
    className: "kit-field__label"
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "bell"
  }), "Reminders"), /*#__PURE__*/React.createElement("div", {
    className: "kit-chips"
  }, reminders.map((r, i) => /*#__PURE__*/React.createElement("span", {
    className: "kit-chip",
    key: i
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "bell"
  }), r, /*#__PURE__*/React.createElement("span", {
    className: "kit-chip__x",
    onClick: () => patch({
      reminders: reminders.filter((_, j) => j !== i)
    })
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "x"
  })))), addingRem ? /*#__PURE__*/React.createElement("span", {
    className: "kit-chip"
  }, /*#__PURE__*/React.createElement("input", {
    autoFocus: true,
    value: remInput,
    onChange: e => setRemInput(e.target.value),
    onKeyDown: e => e.key === "Enter" && addRem(),
    onBlur: addRem,
    placeholder: "When?",
    style: {
      border: "none",
      outline: "none",
      background: "transparent",
      font: "inherit",
      width: 90
    }
  })) : /*#__PURE__*/React.createElement("span", {
    className: "kit-chip kit-chip__add",
    onClick: () => setAddingRem(true)
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "plus"
  }), "Add")), reminders.length === 0 && !addingRem && /*#__PURE__*/React.createElement("div", {
    className: "kit-chips"
  }, presetRems.map(r => /*#__PURE__*/React.createElement("span", {
    className: "kit-chip kit-chip__add",
    key: r,
    onClick: () => patch({
      reminders: [...reminders, r]
    })
  }, r)))), /*#__PURE__*/React.createElement("div", {
    className: "kit-field"
  }, /*#__PURE__*/React.createElement("span", {
    className: "kit-field__label"
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "paperclip"
  }), "Files ", files.length > 0 && /*#__PURE__*/React.createElement("span", {
    style: {
      color: "var(--text-disabled)",
      fontWeight: 600
    }
  }, "\xB7 ", files.length)), files.length > 0 && /*#__PURE__*/React.createElement("div", {
    className: "kit-files"
  }, files.map(f => {
    const fi = fileIcon(f.name);
    return /*#__PURE__*/React.createElement("div", {
      className: "kit-file",
      key: f.id
    }, /*#__PURE__*/React.createElement("span", {
      className: "kit-file__ico",
      style: {
        background: `var(--${fi.tint}-100)`,
        color: `var(--${fi.tint}-600)`
      }
    }, /*#__PURE__*/React.createElement(Icon, {
      name: fi.icon
    })), /*#__PURE__*/React.createElement("div", {
      className: "kit-file__main"
    }, /*#__PURE__*/React.createElement("div", {
      className: "kit-file__name"
    }, f.name), /*#__PURE__*/React.createElement("div", {
      className: "kit-file__size"
    }, fmtSize(f.size))), /*#__PURE__*/React.createElement("span", {
      className: "kit-file__del",
      onClick: () => delFile(f.id)
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "x"
    })));
  })), /*#__PURE__*/React.createElement("div", {
    className: "kit-dropzone",
    onClick: () => fileRef.current && fileRef.current.click()
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "upload"
  }), "Attach a file"), /*#__PURE__*/React.createElement("input", {
    ref: fileRef,
    type: "file",
    multiple: true,
    onChange: onFiles,
    style: {
      display: "none"
    }
  }))), /*#__PURE__*/React.createElement("div", {
    className: "kit-drawer__foot"
  }, /*#__PURE__*/React.createElement("span", {
    className: "kit-muted",
    style: {
      display: "inline-flex",
      alignItems: "center",
      gap: 6
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "check-check"
  }), task.done ? "Completed" : "In progress"), /*#__PURE__*/React.createElement(Button, {
    variant: "primary",
    size: "sm",
    onClick: onClose
  }, "Done"))));
}
window.TaskDetail = TaskDetail;
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/scuffed-os/TaskDetail.jsx", error: String((e && e.message) || e) }); }

// ui_kits/scuffed-os/TasksScreen.jsx
try { (() => {
/* Scuffed OS — Task manager */
function TasksScreen() {
  const LIST_COLOR = {
    Work: "sky",
    Health: "green",
    Finance: "honey",
    Personal: "plum"
  };
  const [tasks, setTasks] = React.useState([{
    id: 1,
    label: "Reply to Priya about Lighthouse",
    group: "Today",
    due: "11:00am",
    deadline: "2026-06-08",
    prio: "high",
    list: "Work",
    description: "She asked about the moved deadline — confirm the 30th works and loop in the design review.",
    subtasks: [{
      id: 11,
      label: "Check calendar for the 30th",
      done: true
    }, {
      id: 12,
      label: "Draft reply",
      done: false
    }],
    reminders: ["1 hour before"],
    files: [{
      id: 101,
      name: "lighthouse-brief.pdf",
      size: 248000
    }]
  }, {
    id: 2,
    label: "Log lunch",
    group: "Today",
    due: "1:00pm",
    deadline: "2026-06-08",
    prio: "low",
    list: "Health",
    description: "",
    subtasks: [],
    labels: ["nutrition"],
    reminders: ["1:00pm"]
  }, {
    id: 3,
    label: "Book dentist follow-up",
    group: "Today",
    due: "Overdue",
    late: true,
    deadline: "2026-06-06",
    prio: "med",
    list: "Health",
    description: "Call Oak Street Dental — ask for an early-morning slot.",
    subtasks: [],
    labels: [],
    reminders: []
  }, {
    id: 4,
    label: "Move $120 to savings",
    group: "Today",
    due: "Today",
    deadline: "2026-06-08",
    prio: "med",
    list: "Finance",
    description: "Roll over the dining-budget surplus.",
    subtasks: [],
    labels: ["savings"],
    reminders: []
  }, {
    id: 5,
    label: "Pay rent",
    group: "Today",
    due: "Done 8:02am",
    deadline: "2026-06-08",
    prio: "high",
    list: "Finance",
    done: true,
    description: "",
    subtasks: [],
    labels: [],
    reminders: []
  }, {
    id: 6,
    label: "Draft Q3 planning doc",
    group: "Upcoming",
    due: "Tomorrow",
    deadline: "2026-06-09",
    prio: "high",
    list: "Work",
    description: "Outline goals, headcount, and the roadmap themes.",
    subtasks: [{
      id: 61,
      label: "Goals",
      done: false
    }, {
      id: 62,
      label: "Roadmap themes",
      done: false
    }],
    labels: ["planning"],
    reminders: []
  }, {
    id: 7,
    label: "Order mom's birthday gift",
    group: "Upcoming",
    due: "Jun 12",
    deadline: "2026-06-12",
    prio: "med",
    list: "Personal",
    description: "The ceramics class she mentioned in a voice note.",
    subtasks: [],
    reminders: ["Jun 11, 9:00am"],
    files: [{
      id: 701,
      name: "ceramics-studio.png",
      size: 1340000
    }, {
      id: 702,
      name: "gift-ideas.txt",
      size: 1200
    }]
  }, {
    id: 8,
    label: "Meal prep for the week",
    group: "Upcoming",
    due: "Sun",
    deadline: "2026-06-14",
    prio: "low",
    list: "Health",
    description: "",
    subtasks: [],
    labels: [],
    reminders: []
  }, {
    id: 9,
    label: "Renew gym membership",
    group: "Someday",
    prio: "low",
    list: "Health",
    description: "",
    subtasks: [],
    labels: [],
    reminders: []
  }, {
    id: 10,
    label: "Read 'Deep Work'",
    group: "Someday",
    prio: "low",
    list: "Personal",
    description: "",
    subtasks: [],
    labels: ["reading"],
    reminders: []
  }].map(t => ({
    done: false,
    subtasks: [],
    reminders: [],
    files: [],
    description: "",
    ...t,
    listColor: LIST_COLOR[t.list]
  })));
  const [openId, setOpenId] = React.useState(null);
  const toggle = id => setTasks(ts => ts.map(t => t.id === id ? {
    ...t,
    done: !t.done
  } : t));
  const update = (id, patch) => setTasks(ts => ts.map(t => t.id === id ? {
    ...t,
    ...patch
  } : t));
  const lists = [{
    name: "Work",
    color: "sky"
  }, {
    name: "Health",
    color: "green"
  }, {
    name: "Finance",
    color: "honey"
  }, {
    name: "Personal",
    color: "plum"
  }];
  const groups = ["Today", "Upcoming", "Someday"];
  const openCount = tasks.filter(t => !t.done).length;
  const doneToday = tasks.filter(t => t.done).length;
  const openTask = tasks.find(t => t.id === openId);
  const TaskRow = t => {
    const subs = t.subtasks || [];
    const subsDone = subs.filter(s => s.done).length;
    return /*#__PURE__*/React.createElement("div", {
      className: "kit-task" + (t.done ? " kit-task--done" : ""),
      key: t.id,
      onClick: () => setOpenId(t.id)
    }, /*#__PURE__*/React.createElement("span", {
      onClick: e => e.stopPropagation(),
      style: {
        display: "inline-flex"
      }
    }, /*#__PURE__*/React.createElement(Checkbox, {
      checked: t.done,
      onChange: () => toggle(t.id)
    })), /*#__PURE__*/React.createElement("div", {
      className: "kit-task__main"
    }, /*#__PURE__*/React.createElement("p", {
      className: "kit-task__title"
    }, t.label), /*#__PURE__*/React.createElement("div", {
      className: "kit-task__meta"
    }, /*#__PURE__*/React.createElement("span", {
      className: "kit-prio",
      style: {
        background: t.prio === "high" ? "var(--clay-600)" : t.prio === "med" ? "var(--honey-600)" : "var(--green-500)"
      }
    }), t.due && /*#__PURE__*/React.createElement("span", {
      className: "kit-task__due" + (t.late ? " is-late" : "")
    }, /*#__PURE__*/React.createElement(Icon, {
      name: t.late ? "alarm-clock" : "clock"
    }), t.due), /*#__PURE__*/React.createElement(Badge, {
      color: t.listColor || "neutral"
    }, t.list), subs.length > 0 && /*#__PURE__*/React.createElement("span", {
      className: "kit-task__due"
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "list-checks"
    }), subsDone, "/", subs.length), (t.files || []).length > 0 && /*#__PURE__*/React.createElement("span", {
      className: "kit-task__due"
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "paperclip"
    }), t.files.length))), /*#__PURE__*/React.createElement("span", {
      className: "kit-task__chev"
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "chevron-right"
    })));
  };
  return /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("div", {
    className: "kit-grid",
    style: {
      gridTemplateColumns: "1fr 280px"
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-col"
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-quickadd"
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "plus"
  }), /*#__PURE__*/React.createElement("input", {
    placeholder: "Add a task \u2014 or say it as a voice note\u2026"
  }), /*#__PURE__*/React.createElement(Badge, {
    color: "green",
    icon: /*#__PURE__*/React.createElement(Icon, {
      name: "mic"
    })
  }, "Voice")), groups.map(g => {
    const rows = tasks.filter(t => t.group === g);
    if (!rows.length) return null;
    return /*#__PURE__*/React.createElement(Card, {
      key: g,
      title: g,
      action: /*#__PURE__*/React.createElement("span", {
        className: "kit-muted"
      }, rows.filter(t => !t.done).length, " open")
    }, /*#__PURE__*/React.createElement("div", {
      className: "kit-tasklist"
    }, rows.map(TaskRow)));
  })), /*#__PURE__*/React.createElement("div", {
    className: "kit-col"
  }, /*#__PURE__*/React.createElement(Card, {
    title: "Progress",
    variant: "sunken"
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-spread",
    style: {
      marginBottom: 14
    }
  }, /*#__PURE__*/React.createElement(Stat, {
    label: "Open",
    value: openCount
  }), /*#__PURE__*/React.createElement(Stat, {
    label: "Done today",
    value: doneToday,
    trend: "up",
    delta: "+2"
  })), /*#__PURE__*/React.createElement(ProgressBar, {
    label: "Today",
    value: doneToday,
    max: doneToday + tasks.filter(t => t.group === "Today" && !t.done).length,
    color: "green",
    meta: `${doneToday} done`
  })), /*#__PURE__*/React.createElement(Card, {
    title: "Lists"
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-stack",
    style: {
      gap: 0
    }
  }, lists.map(l => /*#__PURE__*/React.createElement("div", {
    className: "kit-listrow",
    key: l.name
  }, /*#__PURE__*/React.createElement("span", {
    className: "kit-listrow__dot",
    style: {
      background: `var(--${l.color}-600)`
    }
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: "var(--text-base)",
      fontWeight: 600,
      color: "var(--text-strong)"
    }
  }, l.name), /*#__PURE__*/React.createElement("span", {
    className: "kit-listrow__count"
  }, tasks.filter(t => t.list === l.name && !t.done).length)))), /*#__PURE__*/React.createElement("div", {
    className: "kit-divider",
    style: {
      margin: "10px 0"
    }
  }), /*#__PURE__*/React.createElement(Button, {
    variant: "ghost",
    size: "sm",
    iconLeft: /*#__PURE__*/React.createElement(Icon, {
      name: "plus"
    })
  }, "New list")), /*#__PURE__*/React.createElement(Card, {
    title: "Assistant",
    eyebrow: "Suggestion"
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-insight"
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-insight__icon"
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "sparkles"
  })), /*#__PURE__*/React.createElement("p", null, "3 tasks are ", /*#__PURE__*/React.createElement("strong", null, "overdue or due today"), ". Want me to reschedule the rest to this evening?")), /*#__PURE__*/React.createElement("div", {
    className: "kit-inline",
    style: {
      marginTop: 12
    }
  }, /*#__PURE__*/React.createElement(Button, {
    variant: "soft",
    size: "sm"
  }, "Reschedule"), /*#__PURE__*/React.createElement(Button, {
    variant: "ghost",
    size: "sm"
  }, "No thanks"))))), openTask && /*#__PURE__*/React.createElement(TaskDetail, {
    task: openTask,
    onUpdate: update,
    onClose: () => setOpenId(null)
  }));
}
window.TasksScreen = TasksScreen;
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/scuffed-os/TasksScreen.jsx", error: String((e && e.message) || e) }); }

// ui_kits/scuffed-os/TopBar.jsx
try { (() => {
/* Scuffed OS — Top bar (greeting + search + record) */
function TopBar({
  title,
  subtitle,
  recording,
  onToggleRecord
}) {
  return /*#__PURE__*/React.createElement("header", {
    className: "kit-topbar"
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-greeting"
  }, /*#__PURE__*/React.createElement("h1", null, title), /*#__PURE__*/React.createElement("p", null, subtitle)), /*#__PURE__*/React.createElement("div", {
    className: "kit-topbar__actions"
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-search"
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "search"
  }), /*#__PURE__*/React.createElement("input", {
    placeholder: "Ask your second brain\u2026"
  })), /*#__PURE__*/React.createElement(IconButton, {
    label: "Notifications",
    variant: "ghost"
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "bell"
  })), /*#__PURE__*/React.createElement(Button, {
    variant: recording ? "secondary" : "primary",
    iconLeft: /*#__PURE__*/React.createElement(Icon, {
      name: recording ? "square" : "mic"
    }),
    onClick: onToggleRecord
  }, recording ? "Stop" : "Voice note")));
}
window.TopBar = TopBar;
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/scuffed-os/TopBar.jsx", error: String((e && e.message) || e) }); }

// ui_kits/scuffed-os/app.jsx
try { (() => {
/* Scuffed OS — App shell + state */
const SCREENS = {
  home: {
    title: "Good morning, Sam",
    sub: "Tuesday, June 9 · 4 things need you today"
  },
  nutrition: {
    title: "Nutrition",
    sub: "1,690 of 2,100 kcal · 410 to go"
  },
  fitness: {
    title: "Fitness",
    sub: "82% recovered · ready for a hard session"
  },
  finance: {
    title: "Finance",
    sub: "$129,050 net worth · on budget for June"
  },
  memory: {
    title: "Second Brain",
    sub: "142 memories · learning from your notes"
  },
  calendar: {
    title: "Calendar",
    sub: "3 events today"
  },
  tasks: {
    title: "Tasks",
    sub: "5 open · 2 done today"
  },
  habits: {
    title: "Habits",
    sub: "2 of 5 done · keep your streaks alive"
  },
  people: {
    title: "People",
    sub: "142 contacts · 2 to reach out to"
  },
  email: {
    title: "Email",
    sub: "12 new · 4 need a reply"
  },
  settings: {
    title: "Settings",
    sub: "Preferences & connections"
  }
};
function Placeholder({
  icon,
  name
}) {
  return /*#__PURE__*/React.createElement(Card, {
    variant: "flat",
    style: {
      textAlign: "center",
      padding: "56px 24px"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "inline-flex",
      width: 56,
      height: 56,
      borderRadius: "var(--radius-lg)",
      background: "var(--accent-soft)",
      color: "var(--accent-text)",
      alignItems: "center",
      justifyContent: "center",
      marginBottom: 14
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: icon
  })), /*#__PURE__*/React.createElement("h3", {
    style: {
      fontFamily: "var(--font-display)",
      fontSize: "var(--text-xl)",
      color: "var(--text-strong)",
      margin: "0 0 6px"
    }
  }, name), /*#__PURE__*/React.createElement("p", {
    className: "kit-muted",
    style: {
      maxWidth: 360,
      margin: "0 auto"
    }
  }, "This surface isn't part of the current design-system sample. The Home, Nutrition, Finance and Second Brain screens are fully built out."));
}
function App() {
  const [screen, setScreen] = React.useState("home");
  const [recording, setRecording] = React.useState(false);
  const [tasks, setTasks] = React.useState([{
    id: 1,
    label: "Pay rent",
    done: true
  }, {
    id: 2,
    label: "Reply to Priya about Lighthouse",
    done: false
  }, {
    id: 3,
    label: "Log lunch",
    done: false
  }, {
    id: 4,
    label: "Book dentist follow-up",
    done: false
  }, {
    id: 5,
    label: "Move $120 to savings",
    done: false
  }]);
  const voiceNotes = [{
    text: "“Remind me to call mom about the ceramics class”",
    time: "8:10am",
    len: "0:06",
    done: true
  }, {
    text: "“Lighthouse deadline moved to the 30th”",
    time: "Yesterday",
    len: "0:11",
    done: true
  }, {
    text: "“Cut dining out to twice a week”",
    time: "Yesterday",
    len: "0:04",
    done: true
  }];
  const [assistantOpen, setAssistantOpen] = React.useState(false);
  const toggleTask = id => setTasks(ts => ts.map(t => t.id === id ? {
    ...t,
    done: !t.done
  } : t));
  const addTask = label => setTasks(ts => [{
    id: Date.now(),
    label,
    done: false
  }, ...ts]);
  const meta = SCREENS[screen] || SCREENS.home;
  let body;
  if (screen === "home") body = /*#__PURE__*/React.createElement(DashboardScreen, {
    tasks: tasks,
    onToggleTask: toggleTask,
    voiceNotes: voiceNotes
  });else if (screen === "nutrition") body = /*#__PURE__*/React.createElement(NutritionScreen, null);else if (screen === "finance") body = /*#__PURE__*/React.createElement(FinanceScreen, null);else if (screen === "memory") body = /*#__PURE__*/React.createElement(MemoryScreen, {
    voiceNotes: voiceNotes
  });else if (screen === "calendar") body = /*#__PURE__*/React.createElement(CalendarScreen, null);else if (screen === "tasks") body = /*#__PURE__*/React.createElement(TasksScreen, null);else if (screen === "fitness") body = /*#__PURE__*/React.createElement(FitnessScreen, null);else if (screen === "habits") body = /*#__PURE__*/React.createElement(HabitsScreen, null);else if (screen === "people") body = /*#__PURE__*/React.createElement(CRMScreen, null);else if (screen === "email") body = /*#__PURE__*/React.createElement(EmailScreen, null);else body = /*#__PURE__*/React.createElement(Placeholder, {
    icon: {
      settings: "settings"
    }[screen] || "sparkles",
    name: meta.title
  });
  return /*#__PURE__*/React.createElement("div", {
    className: "kit"
  }, /*#__PURE__*/React.createElement(Sidebar, {
    active: screen,
    onNavigate: setScreen
  }), /*#__PURE__*/React.createElement("main", {
    className: "kit-main"
  }, /*#__PURE__*/React.createElement(TopBar, {
    title: meta.title,
    subtitle: meta.sub,
    recording: recording,
    onToggleRecord: () => setRecording(r => !r)
  }), /*#__PURE__*/React.createElement("div", {
    className: "kit-page"
  }, recording && /*#__PURE__*/React.createElement("div", {
    className: "kit-voice",
    style: {
      marginBottom: "var(--gutter)"
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "kit-insight__icon",
    style: {
      background: "var(--green-600)",
      color: "#fff"
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "mic"
  })), /*#__PURE__*/React.createElement("div", {
    className: "kit-voice__wave"
  }, Array.from({
    length: 30
  }).map((_, i) => /*#__PURE__*/React.createElement("i", {
    key: i,
    style: {
      height: 6 + i % 6 * 3,
      animationDelay: i * 0.04 + "s"
    }
  }))), /*#__PURE__*/React.createElement("div", {
    className: "kit-voice__label"
  }, /*#__PURE__*/React.createElement("b", null, "Listening\u2026"), "Speak \u2014 I'll file it into your second brain"), /*#__PURE__*/React.createElement(Button, {
    variant: "secondary",
    size: "sm",
    onClick: () => setRecording(false)
  }, "Done")), body)), !assistantOpen && /*#__PURE__*/React.createElement("button", {
    className: "kit-fab",
    onClick: () => setAssistantOpen(true)
  }, /*#__PURE__*/React.createElement("span", {
    className: "kit-fab__pulse"
  }), /*#__PURE__*/React.createElement(Icon, {
    name: "sparkles"
  }), "Assistant"), assistantOpen && /*#__PURE__*/React.createElement(ChatPanel, {
    onClose: () => setAssistantOpen(false),
    onNavigate: setScreen,
    onCreateTask: addTask
  }));
}
ReactDOM.createRoot(document.getElementById("root")).render(/*#__PURE__*/React.createElement(App, null));
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/scuffed-os/app.jsx", error: String((e && e.message) || e) }); }

// ui_kits/scuffed-os/assistant-logic.js
try { (() => {
/* Scuffed OS — shared assistant logic (plain JS, no JSX).
   Used by both the desktop ChatPanel and the iOS MobileAssistant.
   Exposes window.ScuffedAssistant.reply(text) -> { text, action? }. */
(function () {
  function cleanTitle(text) {
    var t = text.replace(/^(hey |hi |ok |please |can you |could you |would you |i need to |i want to )+/i, "");
    t = t.replace(/^(add (a )?(task|reminder|to-?do)( to)?:?\s*|remind me to\s*|create (a )?task( to)?:?\s*|new task:?\s*|to-?do:?\s*|set a reminder to\s*)+/i, "");
    t = t.replace(/[.?!]+$/, "").trim();
    return t.charAt(0).toUpperCase() + t.slice(1);
  }
  function cleanEvent(text) {
    var t = text.replace(/^(hey |hi |ok |please |can you |could you )+/i, "");
    t = t.replace(/^(schedule|book|set up|add|create|put in)( a| an| my)?( meeting| event| call| appointment)?( for| with| on| about)?:?\s*/i, "");
    t = t.replace(/[.?!]+$/, "").trim();
    return t.charAt(0).toUpperCase() + t.slice(1) || "New event";
  }
  function reply(text) {
    var t = text.toLowerCase();
    if (/plan (my|the) day|my day|what('?s| is) (on |up )?today|^agenda|brief me/.test(t)) {
      return {
        text: "Here's your day: <strong>4 tasks</strong>, a design standup at 11:30, and a dentist visit at 4. You're $120 under your dining budget and 410 kcal from your goal. Want me to block focus time this morning?",
        action: {
          icon: "layout-dashboard",
          title: "Day planned",
          meta: "Focus block held · 9:00–10:30",
          cta: "Open home",
          screen: "home"
        }
      };
    }
    // explicit task phrasing wins over category keywords (e.g. "add a task to water the plants")
    if (/\b(add a task|task to|new task|remind me|to-?do|follow up)\b/.test(t)) {
      var et = cleanTitle(text);
      return {
        text: "Done — I've added <strong>" + et + "</strong> to your Tasks for today.",
        action: {
          icon: "circle-check-big",
          title: "Added to Tasks",
          meta: "Today · tap to set a due date",
          cta: "View tasks",
          screen: "tasks",
          makeTask: et
        }
      };
    }
    if (/move|transfer|roll(\s|-)?over|put.*savings|into savings/.test(t) && /saving|dining|budget|\$|money/.test(t)) {
      return {
        text: "Moved <strong>$120</strong> from Dining to Savings. You're still comfortably on budget for June.",
        action: {
          icon: "wallet",
          title: "Transfer complete",
          meta: "$120 → Savings",
          cta: "View finance",
          screen: "finance"
        }
      };
    }
    if (/spend|spent|budget|afford|cost|how much|finance|expense/.test(t)) {
      return {
        text: "You've spent <strong>$1,840</strong> in June — 12% less than May. Dining is your biggest discretionary category at <strong>$186</strong> of $250.",
        action: {
          icon: "wallet",
          title: "June spending",
          meta: "$1,840 / $2,400 budget",
          cta: "View finance",
          screen: "finance"
        }
      };
    }
    if (/schedule|meeting|calendar|book|appointment|event|invite/.test(t)) {
      var ev = cleanEvent(text);
      return {
        text: "Scheduled <strong>" + ev + "</strong>. I found a free slot tomorrow afternoon and sent the invite.",
        action: {
          icon: "calendar",
          title: "Event created",
          meta: ev + " · Tue 2:00pm",
          cta: "Open calendar",
          screen: "calendar"
        }
      };
    }
    if (/log|ate|eat|breakfast|lunch|dinner|meal|calorie|protein|snack|water|drank/.test(t)) {
      return {
        text: "Logged it. You're at <strong>1,910 kcal</strong> today and <strong>132g</strong> protein — 190 calories from your goal.",
        action: {
          icon: "apple",
          title: "Meal logged",
          meta: "+220 kcal · 18g protein",
          cta: "View nutrition",
          screen: "nutrition"
        }
      };
    }
    if (/remind|task|to-?do|todo|add|call|email|pay|renew|follow up|pick up|buy|order|book a/.test(t)) {
      var ti = cleanTitle(text);
      return {
        text: "Done — I've added <strong>" + ti + "</strong> to your Tasks for today.",
        action: {
          icon: "circle-check-big",
          title: "Added to Tasks",
          meta: "Today · tap to set a due date",
          cta: "View tasks",
          screen: "tasks",
          makeTask: ti
        }
      };
    }
    if (/remember|note|memory|second brain|where did|what did i say/.test(t)) {
      return {
        text: "Saved to your second brain. I'll surface it when it's relevant — and you can ask me about it anytime.",
        action: {
          icon: "brain",
          title: "Stored in memory",
          meta: "Tagged automatically",
          cta: "Open brain",
          screen: "memory"
        }
      };
    }
    return {
      text: "I can manage your tasks, calendar, finances and nutrition, or pull anything from your second brain. Tell me what you'd like — for example, “add a task to call the dentist” or “how much did I spend on dining?”"
    };
  }
  window.ScuffedAssistant = {
    reply: reply,
    cleanTitle: cleanTitle,
    cleanEvent: cleanEvent
  };
})();
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/scuffed-os/assistant-logic.js", error: String((e && e.message) || e) }); }

// ui_kits/scuffed-os/ui.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/* Scuffed OS UI kit — primitives (mirror the design-system components 1:1). */

function _pascal(name) {
  return String(name).split("-").map(s => s.charAt(0).toUpperCase() + s.slice(1)).join("");
}
/* Renders a Lucide icon by injecting the SVG into a React-owned <span> via a
   ref. React never reconciles the svg children, so lucide's DOM never fights
   React's virtual DOM (which otherwise corrupts sibling className updates). */
function Icon({
  name,
  size
}) {
  const ref = React.useRef(null);
  React.useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.innerHTML = "";
    const node = window.lucide && window.lucide.icons && window.lucide.icons[_pascal(name)];
    if (node) {
      const svg = window.lucide.createElement(node);
      if (size) {
        svg.setAttribute("width", size);
        svg.setAttribute("height", size);
      }
      el.appendChild(svg);
    }
  }, [name, size]);
  return /*#__PURE__*/React.createElement("span", {
    ref: ref,
    style: {
      display: "inline-flex",
      lineHeight: 0
    }
  });
}
function Button({
  variant = "primary",
  size = "md",
  iconLeft,
  iconRight,
  fullWidth,
  children,
  ...rest
}) {
  return /*#__PURE__*/React.createElement("button", _extends({
    className: `sa-btn sa-btn--${variant} sa-btn--${size}${fullWidth ? " sa-btn--full" : ""}`
  }, rest), iconLeft && /*#__PURE__*/React.createElement("span", {
    className: "sa-btn__icon"
  }, iconLeft), children && /*#__PURE__*/React.createElement("span", null, children), iconRight && /*#__PURE__*/React.createElement("span", {
    className: "sa-btn__icon"
  }, iconRight));
}
function IconButton({
  variant = "ghost",
  size = "md",
  label,
  children,
  ...rest
}) {
  return /*#__PURE__*/React.createElement("button", _extends({
    className: `sa-iconbtn sa-iconbtn--${variant} sa-iconbtn--${size}`,
    "aria-label": label,
    title: label
  }, rest), children);
}
function Card({
  variant = "default",
  title,
  eyebrow,
  action,
  className = "",
  children,
  ...rest
}) {
  const hasHead = title || eyebrow || action;
  return /*#__PURE__*/React.createElement("div", _extends({
    className: `sa-card ${variant !== "default" ? "sa-card--" + variant : ""} ${className}`
  }, rest), hasHead && /*#__PURE__*/React.createElement("div", {
    className: "sa-card__head"
  }, /*#__PURE__*/React.createElement("div", null, eyebrow && /*#__PURE__*/React.createElement("p", {
    className: "sa-card__eyebrow"
  }, eyebrow), title && /*#__PURE__*/React.createElement("h3", {
    className: "sa-card__title"
  }, title)), action), children);
}
function Badge({
  color = "neutral",
  dot,
  icon,
  children,
  ...rest
}) {
  return /*#__PURE__*/React.createElement("span", _extends({
    className: `sa-badge sa-badge--${color}`
  }, rest), dot && /*#__PURE__*/React.createElement("span", {
    className: "sa-badge__dot"
  }), icon, children);
}
const AV_TINTS = {
  green: ["var(--green-200)", "var(--green-800)"],
  clay: ["var(--clay-100)", "#97432c"],
  honey: ["var(--honey-100)", "#8d6320"],
  sky: ["var(--sky-100)", "#2c556d"],
  plum: ["var(--plum-100)", "#5f4267"]
};
function Avatar({
  name = "",
  src,
  size = "md",
  tint = "green",
  ...rest
}) {
  const initials = name.split(/\s+/).filter(Boolean).slice(0, 2).map(w => w[0]).join("").toUpperCase();
  const [bg, fg] = AV_TINTS[tint] || AV_TINTS.green;
  return /*#__PURE__*/React.createElement("span", _extends({
    className: `sa-avatar sa-avatar--${size}`,
    style: src ? undefined : {
      background: bg,
      color: fg
    }
  }, rest), src ? /*#__PURE__*/React.createElement("img", {
    src: src,
    alt: name
  }) : initials || "?");
}
function Stat({
  label,
  value,
  unit,
  icon,
  delta,
  trend = "up"
}) {
  return /*#__PURE__*/React.createElement("div", {
    className: "sa-stat"
  }, label && /*#__PURE__*/React.createElement("span", {
    className: "sa-stat__label"
  }, icon, label), /*#__PURE__*/React.createElement("span", {
    className: "sa-stat__value"
  }, value, unit && /*#__PURE__*/React.createElement("span", {
    className: "sa-stat__unit"
  }, unit)), delta != null && /*#__PURE__*/React.createElement("span", {
    className: `sa-stat__delta sa-stat__delta--${trend}`
  }, /*#__PURE__*/React.createElement("svg", {
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: "2.5",
    strokeLinecap: "round",
    strokeLinejoin: "round"
  }, trend === "down" ? /*#__PURE__*/React.createElement("polyline", {
    points: "6 9 12 15 18 9"
  }) : trend === "flat" ? /*#__PURE__*/React.createElement("line", {
    x1: "5",
    y1: "12",
    x2: "19",
    y2: "12"
  }) : /*#__PURE__*/React.createElement("polyline", {
    points: "6 15 12 9 18 15"
  })), delta));
}
const BAR_COLORS = {
  green: "var(--green-600)",
  clay: "var(--clay-600)",
  honey: "var(--honey-600)",
  sky: "var(--sky-600)",
  plum: "var(--plum-600)"
};
function ProgressBar({
  value = 0,
  max = 100,
  label,
  meta,
  color = "green",
  size = "md"
}) {
  const pct = Math.max(0, Math.min(100, value / max * 100));
  return /*#__PURE__*/React.createElement("div", {
    className: `sa-progress sa-progress--${size}`
  }, (label || meta) && /*#__PURE__*/React.createElement("div", {
    className: "sa-progress__top"
  }, label && /*#__PURE__*/React.createElement("span", {
    className: "sa-progress__label"
  }, label), meta && /*#__PURE__*/React.createElement("span", {
    className: "sa-progress__meta"
  }, meta)), /*#__PURE__*/React.createElement("div", {
    className: "sa-progress__track"
  }, /*#__PURE__*/React.createElement("div", {
    className: "sa-progress__fill",
    style: {
      width: pct + "%",
      background: BAR_COLORS[color]
    }
  })));
}
function ProgressRing({
  value = 0,
  max = 100,
  size = 72,
  thickness = 9,
  color = "green",
  trackColor = "var(--paper-300)",
  label,
  sublabel
}) {
  const pct = Math.max(0, Math.min(1, value / max));
  const r = (size - thickness) / 2;
  const c = 2 * Math.PI * r;
  return /*#__PURE__*/React.createElement("div", {
    style: {
      position: "relative",
      width: size,
      height: size
    }
  }, /*#__PURE__*/React.createElement("svg", {
    width: size,
    height: size,
    style: {
      transform: "rotate(-90deg)"
    }
  }, /*#__PURE__*/React.createElement("circle", {
    cx: size / 2,
    cy: size / 2,
    r: r,
    fill: "none",
    stroke: trackColor,
    strokeWidth: thickness
  }), /*#__PURE__*/React.createElement("circle", {
    cx: size / 2,
    cy: size / 2,
    r: r,
    fill: "none",
    stroke: BAR_COLORS[color],
    strokeWidth: thickness,
    strokeDasharray: c,
    strokeDashoffset: c * (1 - pct),
    strokeLinecap: "round",
    style: {
      transition: "stroke-dashoffset var(--dur-slow) var(--ease-out)"
    }
  })), (label || sublabel) && /*#__PURE__*/React.createElement("div", {
    style: {
      position: "absolute",
      inset: 0,
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      justifyContent: "center",
      textAlign: "center"
    }
  }, label && /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: size * 0.25,
      fontWeight: 600,
      color: "var(--text-strong)",
      lineHeight: 1
    }
  }, label), sublabel && /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: size * 0.13,
      color: "var(--text-faint)",
      marginTop: 2
    }
  }, sublabel)));
}
function Checkbox({
  checked,
  onChange,
  label,
  strikeWhenChecked
}) {
  return /*#__PURE__*/React.createElement("label", {
    className: `sa-check ${strikeWhenChecked && checked ? "sa-check--done" : ""}`
  }, /*#__PURE__*/React.createElement("input", {
    type: "checkbox",
    checked: checked,
    onChange: onChange
  }), /*#__PURE__*/React.createElement("span", {
    className: "sa-check__box"
  }, /*#__PURE__*/React.createElement("svg", {
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: "3.5",
    strokeLinecap: "round",
    strokeLinejoin: "round"
  }, /*#__PURE__*/React.createElement("polyline", {
    points: "20 6 9 17 4 12"
  }))), label && /*#__PURE__*/React.createElement("span", null, label));
}
function Switch({
  checked,
  onChange,
  label
}) {
  return /*#__PURE__*/React.createElement("label", {
    className: "sa-switch"
  }, /*#__PURE__*/React.createElement("input", {
    type: "checkbox",
    checked: checked,
    onChange: onChange
  }), /*#__PURE__*/React.createElement("span", {
    className: "sa-switch__track"
  }, /*#__PURE__*/React.createElement("span", {
    className: "sa-switch__thumb"
  })), label && /*#__PURE__*/React.createElement("span", null, label));
}
Object.assign(window, {
  Icon,
  Button,
  IconButton,
  Card,
  Badge,
  Avatar,
  Stat,
  ProgressBar,
  ProgressRing,
  Checkbox,
  Switch
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/scuffed-os/ui.jsx", error: String((e && e.message) || e) }); }

__ds_ns.Button = __ds_scope.Button;

__ds_ns.IconButton = __ds_scope.IconButton;

__ds_ns.Avatar = __ds_scope.Avatar;

__ds_ns.Badge = __ds_scope.Badge;

__ds_ns.Card = __ds_scope.Card;

__ds_ns.ProgressBar = __ds_scope.ProgressBar;

__ds_ns.ProgressRing = __ds_scope.ProgressRing;

__ds_ns.Stat = __ds_scope.Stat;

__ds_ns.Checkbox = __ds_scope.Checkbox;

__ds_ns.Input = __ds_scope.Input;

__ds_ns.Switch = __ds_scope.Switch;

})();
