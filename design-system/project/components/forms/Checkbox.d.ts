import * as React from "react";

/**
 * Checkbox with a green check — used heavily in the task manager.
 */
export interface CheckboxProps extends Omit<React.InputHTMLAttributes<HTMLInputElement>, "type"> {
  /** Controlled checked state. */
  checked?: boolean;
  /** Uncontrolled initial state. */
  defaultChecked?: boolean;
  /** Optional trailing label. */
  label?: string;
  /** Strike + fade the label when checked (task-list style). @default false */
  strikeWhenChecked?: boolean;
  disabled?: boolean;
}

export function Checkbox(props: CheckboxProps): JSX.Element;
