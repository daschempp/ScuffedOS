import * as React from "react";

/**
 * Square icon-only button for toolbars, cards, and composers.
 */
export interface IconButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  /** Visual style. @default "ghost" */
  variant?: "ghost" | "soft" | "solid";
  /** Size. @default "md" */
  size?: "sm" | "md" | "lg";
  /** Accessible label (also used as tooltip). Required for icon-only buttons. */
  label: string;
  /** Icon node — a Lucide <i data-lucide> or inline <svg>. */
  children?: React.ReactNode;
}

export function IconButton(props: IconButtonProps): JSX.Element;
