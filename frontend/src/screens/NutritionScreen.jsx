/* Scuffed OS — Nutrition tracker.
   A view over the shared nutrition state (useNutrition() in App.jsx, passed
   down as the `nutrition` prop). day/week are null until loaded (or with the
   backend down) — the screen keeps its structure and renders zeros. */
import React from 'react'
import { Card, Button, ProgressRing, ProgressBar, Badge } from '../components/ui.jsx'
import { Icon } from '../lib/Icon.jsx'

const SLOTS = ['Breakfast', 'Lunch', 'Snack', 'Dinner']
const EMPTY_TOTALS = { kcal: 0, protein_g: 0, carbs_g: 0, fat_g: 0 }
const EMPTY_TARGETS = { calories: 0, protein_g: 0, carbs_g: 0, fat_g: 0 }
const EMPTY_FORM = { name: '', slot: 'Breakfast', kcal: '', protein: '' }

const localIso = (d) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`

export function NutritionScreen({ nutrition }) {
  const day = nutrition?.day
  const week = nutrition?.week
  const totals = day?.totals || EMPTY_TOTALS
  const targets = day?.targets || EMPTY_TARGETS
  const meals = day?.meals || []
  const water = day?.water || { cups: 0, goal: 0 }
  const weekDays = week?.days || Array.from({ length: 7 }, () => ({ date: '', dow: '', kcal: 0, frac: 0 }))
  const todayIso = localIso(new Date())

  const [logging, setLogging] = React.useState(false)
  const [form, setForm] = React.useState(EMPTY_FORM)
  const setField = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }))

  const submitMeal = () => {
    if (!form.name.trim() || !form.kcal) return
    // kcal is an int server-side — a fractional entry would 422 and the
    // .catch-swallowing hook would silently drop the meal.
    nutrition.logMeal({ name: form.name.trim(), slot: form.slot, kcal: Math.round(+form.kcal) || 0, protein_g: +form.protein || 0 })
    setForm(EMPTY_FORM)
    setLogging(false)
  }
  const onFormKey = (e) => {
    if (e.key === 'Enter') submitMeal()
    else if (e.key === 'Escape') { setForm(EMPTY_FORM); setLogging(false) }
  }

  const macros = [
    { lab: 'Calories', color: 'green', value: totals.kcal, max: targets.calories, label: `${totals.kcal}`, sub: `of ${targets.calories} kcal` },
    { lab: 'Protein', color: 'clay', value: totals.protein_g, max: targets.protein_g, label: `${totals.protein_g}g`, sub: `of ${targets.protein_g}g` },
    { lab: 'Carbs', color: 'honey', value: totals.carbs_g, max: targets.carbs_g, label: `${totals.carbs_g}g`, sub: `of ${targets.carbs_g}g` },
    { lab: 'Fat', color: 'sky', value: totals.fat_g, max: targets.fat_g, label: `${totals.fat_g}g`, sub: `of ${targets.fat_g}g` },
  ]

  const selectStyle = {
    padding: '8px 11px', borderRadius: 'var(--radius-sm)', background: 'var(--surface-sunken)',
    border: 'none', outline: 'none', fontFamily: 'var(--font-sans)', fontSize: 'var(--text-sm)',
    color: 'var(--text-strong)', cursor: 'pointer',
  }

  return (
    <div className="kit-stack" style={{ gap: 'var(--gutter)' }}>
      <Card title="Today's goals" eyebrow={`${(targets.calories || 0).toLocaleString()} kcal target`}>
        <div className="kit-rings" style={{ justifyContent: 'space-between' }}>
          {macros.map((m) => (
            <div className="kit-ring-cell" key={m.lab}>
              <ProgressRing value={m.value} max={m.max || 1} size={104} thickness={11} color={m.color} label={m.label} sublabel={m.sub} />
              <span className="kit-ring-cell__lab">{m.lab}</span>
            </div>
          ))}
        </div>
      </Card>

      <div className="kit-grid" style={{ gridTemplateColumns: '1.4fr 1fr' }}>
        <Card title="Meals" action={<Button variant="soft" size="sm" iconLeft={<Icon name="plus" />} onClick={() => setLogging((v) => !v)}>Log meal</Button>}>
          {logging && (
            <div className="kit-stack" style={{ gap: 8, marginBottom: 12 }}>
              <div className="kit-addrow" style={{ marginTop: 0 }}>
                <Icon name="utensils" />
                <input autoFocus placeholder="What did you eat?" value={form.name} onChange={setField('name')} onKeyDown={onFormKey} />
              </div>
              <div className="kit-inline" style={{ gap: 8 }}>
                <select value={form.slot} onChange={setField('slot')} style={selectStyle}>
                  {SLOTS.map((s) => <option key={s}>{s}</option>)}
                </select>
                <div className="kit-addrow" style={{ marginTop: 0, flex: 1 }}>
                  <input type="number" placeholder="kcal" value={form.kcal} onChange={setField('kcal')} onKeyDown={onFormKey} />
                </div>
                <div className="kit-addrow" style={{ marginTop: 0, flex: 1 }}>
                  <input type="number" placeholder="protein (g)" value={form.protein} onChange={setField('protein')} onKeyDown={onFormKey} />
                </div>
                <Button variant="soft" size="sm" onClick={submitMeal}>Add</Button>
              </div>
            </div>
          )}
          {meals.map((m) => (
            <div className="kit-meal" key={m.id}>
              <span className="kit-meal__ico" style={{ background: `var(--${m.tint}-100)`, color: `var(--${m.tint}-600)` }}><Icon name={m.icon} /></span>
              <div className="kit-row__main">
                <p className="kit-row__title">{m.name}</p>
                <p className="kit-row__sub">{m.time}</p>
              </div>
              <div style={{ textAlign: 'right' }}>
                <div className="kit-row__amt">{m.kcal}<span style={{ color: 'var(--text-faint)', fontSize: 12 }}> kcal</span></div>
                <div className="kit-muted" style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>{m.protein_g}g protein</div>
              </div>
            </div>
          ))}
          {meals.length === 0 && !logging && <p className="kit-muted">Nothing logged yet today.</p>}
        </Card>

        <div className="kit-col">
          <Card title="Water" action={<Badge color="sky">{water.cups} / {water.goal} cups</Badge>}>
            <ProgressBar value={water.cups} max={water.goal || 1} color="sky" meta={`${Math.max(0, water.goal - water.cups)} cups to go`} />
            <div className="kit-inline" style={{ marginTop: 14 }}>
              <Button variant="secondary" size="sm" iconLeft={<Icon name="plus" />} onClick={() => nutrition.addWater()}>Add a cup</Button>
            </div>
          </Card>
          <Card title="This week" variant="sunken">
            <div className="kit-chart">
              {weekDays.map((c, i) => (
                <div className="kit-chart__col" key={i}>
                  <div className={`kit-chart__bar ${c.date === todayIso ? 'kit-chart__bar--hi' : ''}`} style={{ height: (Math.max(0, Math.min(1, c.frac || 0)) * 100) + '%' }} />
                  <span className="kit-chart__lab">{c.dow}</span>
                </div>
              ))}
            </div>
            <p className="kit-muted" style={{ marginTop: 10 }}>Avg <strong style={{ color: 'var(--text-strong)' }}>{(week?.avg_kcal ?? 0).toLocaleString()} kcal</strong> · goal met {week?.days_met ?? 0} / 7 days</p>
          </Card>
        </div>
      </div>
    </div>
  )
}
