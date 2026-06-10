import * as React from "react";

/** Round avatar — image or auto-generated initials with a warm tint. */
export interface AvatarProps extends React.HTMLAttributes<HTMLSpanElement> {
  /** Full name — used for initials and alt text. */
  name?: string;
  /** Image URL; falls back to initials when absent. */
  src?: string;
  /** Size. @default "md" */
  size?: "xs" | "sm" | "md" | "lg";
  /** Tint when showing initials. @default "green" */
  tint?: "green" | "clay" | "honey" | "sky" | "plum";
}

export function Avatar(props: AvatarProps): JSX.Element;
