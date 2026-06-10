Floaty surface container — the primary content block. Soft shadow, 16px radius, no border.

```jsx
<Card eyebrow="Today" title="Agenda" action={<IconButton label="Add"><i data-lucide="plus" /></IconButton>}>
  …content…
</Card>
```

Variants: `default` (shadow-md), `flat` (hairline, no shadow), `raised` (shadow-lg), `sunken` (paper fill). Set `interactive` to lift on hover. `title` uses the display font; `eyebrow` is a small uppercase overline; `action` pins to the header's right.
