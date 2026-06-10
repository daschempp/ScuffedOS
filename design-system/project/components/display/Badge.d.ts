import * as React from "react";

/** Small pill label for status, categories and counts. */
export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  /** Color tint. @default "neutral" */
  color?: "neutral" | "green" | "clay" | "honey" | "sky" | "plum" | "solid";
  /** Show a leading status dot. @default false */
  dot?: boolean;
  /** Optional leading icon node. */
  icon?: React.ReactNode;
  children?: React.ReactNode;
}

export function Badge(props: BadgeProps): JSX.Element;
