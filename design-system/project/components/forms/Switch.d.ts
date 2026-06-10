import * as React from "react";

/**
 * Pill toggle switch for settings and quick on/off states.
 */
export interface SwitchProps extends Omit<React.InputHTMLAttributes<HTMLInputElement>, "type"> {
  /** Controlled checked state. */
  checked?: boolean;
  /** Uncontrolled initial state. */
  defaultChecked?: boolean;
  /** Optional trailing label. */
  label?: string;
  disabled?: boolean;
}

export function Switch(props: SwitchProps): JSX.Element;
