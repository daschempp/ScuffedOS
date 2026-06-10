import React from "react";

const COLORS = {
  green: "var(--green-600)", clay: "var(--clay-600)", honey: "var(--honey-600)",
  sky: "var(--sky-600)", plum: "var(--plum-600)",
};

/** Concentric progress ring — the nutrition tracker's signature widget. */
export function ProgressRing({
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
  return (
    <div style={{ position: "relative", width: size, height: size, fontFamily: "var(--font-sans)" }} {...rest}>
      <svg width={size} height={size} style={{ transform: "rotate(-90deg)" }}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={trackColor} strokeWidth={thickness} />
        <circle
          cx={size / 2} cy={size / 2} r={r} fill="none" stroke={stroke} strokeWidth={thickness}
          strokelinecap="round" strokeDasharray={c} strokeDashoffset={c * (1 - pct)} strokeLinecap="round"
          style={{ transition: "stroke-dashoffset var(--dur-slow) var(--ease-out)" }}
        />
      </svg>
      {(label || sublabel) && (
        <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", textAlign: "center" }}>
          {label && <span style={{ fontFamily: "var(--font-mono)", fontSize: size * 0.26, fontWeight: 600, color: "var(--text-strong)", lineHeight: 1 }}>{label}</span>}
          {sublabel && <span style={{ fontSize: size * 0.13, color: "var(--text-faint)", marginTop: 2 }}>{sublabel}</span>}
        </div>
      )}
    </div>
  );
}
