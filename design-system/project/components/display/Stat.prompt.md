A single metric with a big mono value and optional trend.

```jsx
<Stat label="Balance" value="$4,820" delta="+3.2%" trend="up" />
<Stat label="Protein" value="138" unit="g" icon={<i data-lucide="beef" />} delta="-12g" trend="down" />
```

`trend` (`up`/`down`/`flat`) colors the delta green/clay/muted and picks the arrow. Value renders in Spline Sans Mono.
