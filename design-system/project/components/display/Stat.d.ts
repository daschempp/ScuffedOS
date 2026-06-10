import * as React from "react";

/** Single metric: label, big mono value, optional trend delta. */
export interface StatProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Uppercase label. */
  label?: React.ReactNode;
  /** The metric value (string or number). */
  value: React.ReactNode;
  /** Small trailing unit (e.g. "kcal", "g"). */
  unit?: string;
  /** Optional leading icon in the label. */
  icon?: React.ReactNode;
  /** Delta text (e.g. "+12%"). */
  delta?: React.ReactNode;
  /** Trend direction — sets color + arrow. @default "up" */
  trend?: "up" | "down" | "flat";
}

export function Stat(props: StatProps): JSX.Element;
