import * as React from "react";

/**
 * Primary call-to-action and secondary buttons for Scuffed OS.
 * @startingPoint section="Core" subtitle="Buttons: primary, secondary, soft, ghost, danger" viewport="700x150"
 */
export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  /** Visual style. @default "primary" */
  variant?: "primary" | "secondary" | "soft" | "ghost" | "danger";
  /** Size. @default "md" */
  size?: "sm" | "md" | "lg";
  /** Icon node rendered before the label (e.g. a Lucide <i> or inline svg). */
  iconLeft?: React.ReactNode;
  /** Icon node rendered after the label. */
  iconRight?: React.ReactNode;
  /** Stretch to fill container width. @default false */
  fullWidth?: boolean;
  /** Render as a different element, e.g. "a" for links. @default "button" */
  as?: "button" | "a";
  children?: React.ReactNode;
}

export function Button(props: ButtonProps): JSX.Element;
