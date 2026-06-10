Primary action and secondary buttons — use for any clickable command in Scuffed OS.

```jsx
<Button variant="primary" iconLeft={<i data-lucide="plus" />}>Add task</Button>
<Button variant="secondary">Later</Button>
<Button variant="soft" size="sm">This week</Button>
<Button variant="ghost">Dismiss</Button>
```

Variants: `primary` (forest-green CTA with tinted glow), `secondary` (hairline outline on paper), `soft` (green tint pill-feel), `ghost` (text-only), `danger` (clay). Sizes: `sm` / `md` / `lg`. Pass `iconLeft` / `iconRight` a Lucide `<i>` or inline svg; `fullWidth` to stretch. Use exactly one `primary` per view.
