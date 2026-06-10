/* Scuffed OS — Nutrition tracker */
import { Card, Button, ProgressRing, ProgressBar, Badge } from '../components/ui.jsx'
import { Icon } from '../lib/Icon.jsx'

export function NutritionScreen() {
  const meals = [
    { ico: 'egg', tint: 'honey', name: 'Greek yogurt & berries', time: 'Breakfast · 8:10am', kcal: 320, p: 24 },
    { ico: 'sandwich', tint: 'clay', name: 'Chicken & avocado wrap', time: 'Lunch · 1:05pm', kcal: 540, p: 38 },
    { ico: 'apple', tint: 'green', name: 'Apple + almonds', time: 'Snack · 3:30pm', kcal: 210, p: 7 },
    { ico: 'utensils', tint: 'plum', name: 'Salmon, rice & greens', time: 'Dinner · 7:20pm', kcal: 620, p: 45 },
  ]
  const week = [
    { d: 'M', v: 0.82 }, { d: 'T', v: 0.94 }, { d: 'W', v: 0.71 }, { d: 'T', v: 0.88 },
    { d: 'F', v: 1.0 }, { d: 'S', v: 0.64 }, { d: 'S', v: 0.87, hi: true },
  ]
  return (
    <div className="kit-stack" style={{ gap: 'var(--gutter)' }}>
      <Card title="Today's goals" eyebrow="2,100 kcal target">
        <div className="kit-rings" style={{ justifyContent: 'space-between' }}>
          <div className="kit-ring-cell"><ProgressRing value={1690} max={2100} size={104} thickness={11} color="green" label="1690" sublabel="of 2100 kcal" /><span className="kit-ring-cell__lab">Calories</span></div>
          <div className="kit-ring-cell"><ProgressRing value={114} max={160} size={104} thickness={11} color="clay" label="114g" sublabel="of 160g" /><span className="kit-ring-cell__lab">Protein</span></div>
          <div className="kit-ring-cell"><ProgressRing value={148} max={210} size={104} thickness={11} color="honey" label="148g" sublabel="of 210g" /><span className="kit-ring-cell__lab">Carbs</span></div>
          <div className="kit-ring-cell"><ProgressRing value={52} max={70} size={104} thickness={11} color="sky" label="52g" sublabel="of 70g" /><span className="kit-ring-cell__lab">Fat</span></div>
        </div>
      </Card>

      <div className="kit-grid" style={{ gridTemplateColumns: '1.4fr 1fr' }}>
        <Card title="Meals" action={<Button variant="soft" size="sm" iconLeft={<Icon name="plus" />}>Log meal</Button>}>
          {meals.map((m, i) => (
            <div className="kit-meal" key={i}>
              <span className="kit-meal__ico" style={{ background: `var(--${m.tint}-100)`, color: `var(--${m.tint}-600)` }}><Icon name={m.ico} /></span>
              <div className="kit-row__main">
                <p className="kit-row__title">{m.name}</p>
                <p className="kit-row__sub">{m.time}</p>
              </div>
              <div style={{ textAlign: 'right' }}>
                <div className="kit-row__amt">{m.kcal}<span style={{ color: 'var(--text-faint)', fontSize: 12 }}> kcal</span></div>
                <div className="kit-muted" style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>{m.p}g protein</div>
              </div>
            </div>
          ))}
        </Card>

        <div className="kit-col">
          <Card title="Water" action={<Badge color="sky">5 / 8 cups</Badge>}>
            <ProgressBar value={5} max={8} color="sky" meta="3 cups to go" />
            <div className="kit-inline" style={{ marginTop: 14 }}>
              <Button variant="secondary" size="sm" iconLeft={<Icon name="plus" />}>Add a cup</Button>
            </div>
          </Card>
          <Card title="This week" variant="sunken">
            <div className="kit-chart">
              {week.map((c, i) => (
                <div className="kit-chart__col" key={i}>
                  <div className={`kit-chart__bar ${c.hi ? 'kit-chart__bar--hi' : ''}`} style={{ height: (c.v * 100) + '%' }} />
                  <span className="kit-chart__lab">{c.d}</span>
                </div>
              ))}
            </div>
            <p className="kit-muted" style={{ marginTop: 10 }}>Avg <strong style={{ color: 'var(--text-strong)' }}>1,940 kcal</strong> · goal met 5 / 7 days</p>
          </Card>
        </div>
      </div>
    </div>
  )
}
