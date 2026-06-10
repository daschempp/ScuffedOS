Text input with label, leading icon, hint and error states.

```jsx
<Input label="Account" placeholder="Search transactions" icon={<i data-lucide="search" />} />
<Input label="Email" defaultValue="sam@" error="That doesn't look right" />
```

Pass `icon` a Lucide `<i>` for a leading glyph; `hint` for helper text; `error` to flag invalid (turns border clay). Forwards all native `<input>` props.
