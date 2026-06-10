import * as React from "react";

/** Horizontal progress bar with optional label + mono meta. */
export interface ProgressBarProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Current value. @default 0 */
  value?: number;
  /** Max value. @default 100 */
  max?: number;
  /** Label on the left. */
  label?: React.ReactNode;
  /** Mono meta on the right (e.g. "1,840 / 2,100"). */
  meta?: React.ReactNode;
  /** Fill color. @default "green" */
  color?: "green" | "clay" | "honey" | "sky" | "plum";
  /** Track height. @default "md" */
  size?: "sm" | "md" | "lg";
}

export function ProgressBar(props: ProgressBarProps): JSX.Element;
