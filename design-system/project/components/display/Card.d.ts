import * as React from "react";

/**
 * Floaty surface container — the primary content block in Scuffed OS.
 * @startingPoint section="Core" subtitle="Cards, badges, avatars, stats & progress" viewport="700x340"
 */
export interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Elevation/fill style. @default "default" */
  variant?: "default" | "flat" | "raised" | "sunken";
  /** Lift on hover (for clickable cards). @default false */
  interactive?: boolean;
  /** Card title (display font). */
  title?: React.ReactNode;
  /** Small uppercase eyebrow above the title. */
  eyebrow?: React.ReactNode;
  /** Node pinned to the top-right of the header (e.g. an IconButton). */
  action?: React.ReactNode;
  children?: React.ReactNode;
}

export function Card(props: CardProps): JSX.Element;
