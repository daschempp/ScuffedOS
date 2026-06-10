import * as React from "react";

/** Circular progress ring — the nutrition tracker's signature widget. */
export interface ProgressRingProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Current value. @default 0 */
  value?: number;
  /** Max value. @default 100 */
  max?: number;
  /** Diameter in px. @default 72 */
  size?: number;
  /** Ring stroke width in px. @default 9 */
  thickness?: number;
  /** Ring color. @default "green" */
  color?: "green" | "clay" | "honey" | "sky" | "plum";
  /** Track (unfilled) color. @default warm inset */
  trackColor?: string;
  /** Big center label (e.g. "82%"). */
  label?: React.ReactNode;
  /** Small label under the center value. */
  sublabel?: React.ReactNode;
}

export function ProgressRing(props: ProgressRingProps): JSX.Element;
