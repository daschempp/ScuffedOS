Icon-only button for toolbars, card headers, and the voice-note composer.

```jsx
<IconButton label="Record voice note" variant="solid"><i data-lucide="mic" /></IconButton>
<IconButton label="More" variant="ghost"><i data-lucide="more-horizontal" /></IconButton>
```

Variants: `ghost` (default), `soft`, `solid` (green). Sizes `sm`/`md`/`lg`. Always pass `label` — it sets aria-label + tooltip. Children should be a single icon node (Lucide `<i data-lucide>` or inline svg).
