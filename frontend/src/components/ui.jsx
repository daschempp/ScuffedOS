/* Scuffed OS — UI primitives (the design-system components, 1:1).
   Pure, presentational, styled entirely via the .sa-* classes in kit.css and the
   token custom properties. No CSS-in-JS, no extra deps. */

export function Button({ variant = 'primary', size = 'md', iconLeft, iconRight, fullWidth, children, ...rest }) {
  return (
    <button className={`sa-btn sa-btn--${variant} sa-btn--${size}${fullWidth ? ' sa-btn--full' : ''}`} {...rest}>
      {iconLeft && <span className="sa-btn__icon">{iconLeft}</span>}
      {children && <span>{children}</span>}
      {iconRight && <span className="sa-btn__icon">{iconRight}</span>}
    </button>
  )
}

export function IconButton({ variant = 'ghost', size = 'md', label, children, ...rest }) {
  return (
    <button className={`sa-iconbtn sa-iconbtn--${variant} sa-iconbtn--${size}`} aria-label={label} title={label} {...rest}>
      {children}
    </button>
  )
}

export function Card({ variant = 'default', title, eyebrow, action, className = '', children, ...rest }) {
  const hasHead = title || eyebrow || action
  return (
    <div className={`sa-card ${variant !== 'default' ? 'sa-card--' + variant : ''} ${className}`} {...rest}>
      {hasHead && (
        <div className="sa-card__head">
          <div>
            {eyebrow && <p className="sa-card__eyebrow">{eyebrow}</p>}
            {title && <h3 className="sa-card__title">{title}</h3>}
          </div>
          {action}
        </div>
      )}
      {children}
    </div>
  )
}

export function Badge({ color = 'neutral', dot, icon, children, ...rest }) {
  return (
    <span className={`sa-badge sa-badge--${color}`} {...rest}>
      {dot && <span className="sa-badge__dot" />}
      {icon}
      {children}
    </span>
  )
}

const AV_TINTS = {
  green: ['var(--green-200)', 'var(--green-800)'],
  clay: ['var(--clay-100)', '#97432c'],
  honey: ['var(--honey-100)', '#8d6320'],
  sky: ['var(--sky-100)', '#2c556d'],
  plum: ['var(--plum-100)', '#5f4267'],
}
export function Avatar({ name = '', src, size = 'md', tint = 'green', ...rest }) {
  const initials = name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join('').toUpperCase()
  const [bg, fg] = AV_TINTS[tint] || AV_TINTS.green
  return (
    <span className={`sa-avatar sa-avatar--${size}`} style={src ? undefined : { background: bg, color: fg }} {...rest}>
      {src ? <img src={src} alt={name} /> : initials || '?'}
    </span>
  )
}

export function Stat({ label, value, unit, icon, delta, trend = 'up' }) {
  return (
    <div className="sa-stat">
      {label && <span className="sa-stat__label">{icon}{label}</span>}
      <span className="sa-stat__value">{value}{unit && <span className="sa-stat__unit">{unit}</span>}</span>
      {delta != null && (
        <span className={`sa-stat__delta sa-stat__delta--${trend}`}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            {trend === 'down' ? <polyline points="6 9 12 15 18 9" /> : trend === 'flat' ? <line x1="5" y1="12" x2="19" y2="12" /> : <polyline points="6 15 12 9 18 15" />}
          </svg>
          {delta}
        </span>
      )}
    </div>
  )
}

const BAR_COLORS = { green: 'var(--green-600)', clay: 'var(--clay-600)', honey: 'var(--honey-600)', sky: 'var(--sky-600)', plum: 'var(--plum-600)' }
export function ProgressBar({ value = 0, max = 100, label, meta, color = 'green', size = 'md' }) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100))
  return (
    <div className={`sa-progress sa-progress--${size}`}>
      {(label || meta) && (
        <div className="sa-progress__top">
          {label && <span className="sa-progress__label">{label}</span>}
          {meta && <span className="sa-progress__meta">{meta}</span>}
        </div>
      )}
      <div className="sa-progress__track"><div className="sa-progress__fill" style={{ width: pct + '%', background: BAR_COLORS[color] }} /></div>
    </div>
  )
}

export function ProgressRing({ value = 0, max = 100, size = 72, thickness = 9, color = 'green', trackColor = 'var(--paper-300)', label, sublabel }) {
  const pct = Math.max(0, Math.min(1, value / max))
  const r = (size - thickness) / 2
  const c = 2 * Math.PI * r
  return (
    <div style={{ position: 'relative', width: size, height: size }}>
      <svg width={size} height={size} style={{ transform: 'rotate(-90deg)' }}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={trackColor} strokeWidth={thickness} />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={BAR_COLORS[color]} strokeWidth={thickness} strokeDasharray={c} strokeDashoffset={c * (1 - pct)} strokeLinecap="round" style={{ transition: 'stroke-dashoffset var(--dur-slow) var(--ease-out)' }} />
      </svg>
      {(label || sublabel) && (
        <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', textAlign: 'center' }}>
          {label && <span style={{ fontFamily: 'var(--font-mono)', fontSize: size * 0.25, fontWeight: 600, color: 'var(--text-strong)', lineHeight: 1 }}>{label}</span>}
          {sublabel && <span style={{ fontSize: size * 0.13, color: 'var(--text-faint)', marginTop: 2 }}>{sublabel}</span>}
        </div>
      )}
    </div>
  )
}

export function Checkbox({ checked, onChange, label, strikeWhenChecked, disabled }) {
  return (
    <label className={`sa-check ${strikeWhenChecked && checked ? 'sa-check--done' : ''} ${disabled ? 'sa-check--disabled' : ''}`}>
      <input type="checkbox" checked={checked} onChange={onChange} disabled={disabled} readOnly={disabled} />
      <span className="sa-check__box"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12" /></svg></span>
      {label && <span>{label}</span>}
    </label>
  )
}

export function Switch({ checked, onChange, label }) {
  return (
    <label className="sa-switch">
      <input type="checkbox" checked={checked} onChange={onChange} />
      <span className="sa-switch__track"><span className="sa-switch__thumb" /></span>
      {label && <span>{label}</span>}
    </label>
  )
}
