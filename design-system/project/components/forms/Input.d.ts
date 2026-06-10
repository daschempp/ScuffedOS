import * as React from "react";

/**
 * Text input with optional label, leading icon, hint, and error states.
 * @startingPoint section="Core" subtitle="Form fields: input, switch, checkbox" viewport="700x260"
 */
export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  /** Field label rendered above the input. */
  label?: string;
  /** Helper text below the field. */
  hint?: string;
  /** Error message — also turns the border clay. */
  error?: string;
  /** Leading icon node (Lucide <i> or inline svg). */
  icon?: React.ReactNode;
}

export function Input(props: InputProps): JSX.Element;
