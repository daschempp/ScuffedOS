/* Scuffed OS — Finance tracker */
import { Card, Stat, Badge, ProgressBar, IconButton, Button } from '../components/ui.jsx'
import { Icon } from '../lib/Icon.jsx'

export function FinanceScreen() {
  const cats = [
    { name: 'Groceries', spent: 320, budget: 400, color: 'clay' },
    { name: 'Rent & bills', spent: 1450, budget: 1450, color: 'honey' },
    { name: 'Dining out', spent: 186, budget: 250, color: 'plum' },
    { name: 'Transport', spent: 64, budget: 150, color: 'sky' },
    { name: 'Savings', spent: 600, budget: 600, color: 'green' },
  ]
  const txns = [
    { title: 'Acme Inc', sub: 'Salary · Jun 1', amt: '+$3,200.00', cat: 'var(--green-600)', pos: true },
    { title: 'Whole Foods', sub: 'Groceries · Jun 8', amt: '-$64.20', cat: 'var(--clay-600)' },
    { title: 'Oak St. Realty', sub: 'Rent · Jun 3', amt: '-$1,450.00', cat: 'var(--honey-600)' },
    { title: 'Vanguard', sub: 'Auto-invest · Jun 5', amt: '-$500.00', cat: 'var(--sky-600)' },
  ]
  // net worth breakdown
  const nw = [
    { name: 'Investments', val: 86200, color: 'var(--green-600)' },
    { name: 'Retirement', val: 21400, color: 'var(--sky-600)' },
    { name: 'Cash', val: 18050, color: 'var(--honey-600)' },
    { name: 'Crypto', val: 3400, color: 'var(--plum-600)' },
  ]
  const nwTotal = nw.reduce((s, x) => s + x.val, 0)
  const holdings = [
    { sym: 'VTI', name: 'Total Market ETF', val: '$48,200', chg: '+1.2%', up: true, tint: 'green' },
    { sym: 'AAPL', name: 'Apple Inc.', val: '$22,640', chg: '+0.6%', up: true, tint: 'sky' },
    { sym: '401k', name: 'Retirement', val: '$21,400', chg: '+0.9%', up: true, tint: 'honey' },
    { sym: 'BTC', name: 'Bitcoin', val: '$3,400', chg: '−2.4%', up: false, tint: 'plum' },
  ]
  const subs = [
    { name: 'Netflix', price: '$15.49', cycle: 'monthly', renews: 'Jun 12', soon: true, color: 'var(--clay-600)', letter: 'N' },
    { name: 'Spotify', price: '$11.99', cycle: 'monthly', renews: 'Jun 18', color: 'var(--green-600)', letter: 'S' },
    { name: 'iCloud+', price: '$2.99', cycle: 'monthly', renews: 'Jun 24', color: 'var(--sky-600)', letter: 'i' },
    { name: 'Notion', price: '$96.00', cycle: 'yearly', renews: 'Jul 2', soon: true, color: 'var(--plum-600)', letter: 'N' },
    { name: 'ChatGPT', price: '$20.00', cycle: 'monthly', renews: 'Jun 28', color: 'var(--honey-600)', letter: 'G' },
  ]
  const bills = [
    { name: 'Rent', sub: 'Oak St. Realty', amt: '$1,450', due: 'Due Jul 1', auto: true, icon: 'house', tint: 'honey' },
    { name: 'Electric', sub: 'ConEd', amt: '$82', due: 'Due Jun 14', auto: true, icon: 'zap', tint: 'clay' },
    { name: 'Internet', sub: 'Verizon Fios', amt: '$70', due: 'Due Jun 16', auto: true, icon: 'wifi', tint: 'sky' },
    { name: 'Phone', sub: 'Mint Mobile', amt: '$30', due: 'Due Jun 20', auto: false, icon: 'smartphone', tint: 'plum' },
  ]
  return (
    <div className="kit-stack" style={{ gap: 'var(--gutter)' }}>
      <div className="kit-grid" style={{ gridTemplateColumns: 'repeat(3, 1fr)' }}>
        <Card><Stat label="Balance" value="$4,820" unit=".50" delta="+3.2%" trend="up" icon={<Icon name="wallet" />} /></Card>
        <Card><Stat label="Income · June" value="$3,200" delta="on track" trend="flat" icon={<Icon name="arrow-down-left" />} /></Card>
        <Card><Stat label="Spent · June" value="$1,840" delta="−12% vs May" trend="down" icon={<Icon name="arrow-up-right" />} /></Card>
      </div>

      {/* Net worth + investments */}
      <div className="kit-grid" style={{ gridTemplateColumns: '1.15fr 1fr' }}>
        <Card eyebrow="Net worth" title="$129,050" action={<Badge color="green" dot>+2.1% this month</Badge>}>
          <div className="kit-nwbar" style={{ marginTop: 4 }}>
            {nw.map((s, i) => <i key={i} style={{ width: (s.val / nwTotal * 100) + '%', background: s.color }} />)}
          </div>
          <div className="kit-nwleg" style={{ marginTop: 14 }}>
            {nw.map((s, i) => (
              <div className="kit-nwleg__item" key={i}>
                <span className="kit-nwleg__dot" style={{ background: s.color }} />
                <span className="kit-muted" style={{ color: 'var(--text-body)' }}>{s.name}</span>
                <span className="kit-nwleg__val">${(s.val / 1000).toFixed(1)}k</span>
              </div>
            ))}
          </div>
        </Card>
        <Card title="Investments" action={<Stat label="Today" value="+$640" trend="up" delta="+0.5%" />}>
          {holdings.map((h, i) => (
            <div className="kit-hold" key={i}>
              <span className="kit-hold__sym" style={{ background: `var(--${h.tint}-100)`, color: `var(--${h.tint}-600)` }}>{h.sym.length > 3 ? h.sym.slice(0, 3) : h.sym}</span>
              <div className="kit-row__main">
                <p className="kit-row__title">{h.name}</p>
                <p className="kit-row__sub">{h.sym}</p>
              </div>
              <div style={{ textAlign: 'right' }}>
                <div className="kit-row__amt">{h.val}</div>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: h.up ? 'var(--green-600)' : 'var(--clay-600)' }}>{h.chg}</div>
              </div>
            </div>
          ))}
        </Card>
      </div>

      {/* Budgets + recent */}
      <div className="kit-grid" style={{ gridTemplateColumns: '1fr 1.2fr' }}>
        <Card title="Budgets" eyebrow="June" action={<IconButton label="Edit budgets" size="sm"><Icon name="sliders-horizontal" /></IconButton>}>
          <div className="kit-stack" style={{ marginTop: 4 }}>
            {cats.map((c, i) => (
              <ProgressBar key={i} label={c.name} value={c.spent} max={c.budget} color={c.color}
                meta={`$${c.spent.toLocaleString()} / $${c.budget.toLocaleString()}`} />
            ))}
          </div>
          <div className="kit-insight" style={{ marginTop: 18 }}>
            <div className="kit-insight__icon"><Icon name="trending-up" /></div>
            <p>You're <strong>$120 under</strong> your dining budget. Roll it into savings?</p>
          </div>
        </Card>

        <Card title="Recent transactions" action={<Button variant="ghost" size="sm" iconRight={<Icon name="arrow-right" />}>All</Button>}>
          {txns.map((t, i) => (
            <div className="kit-row" key={i}>
              <span className="kit-cat" style={{ background: t.cat }} />
              <div className="kit-row__main">
                <p className="kit-row__title">{t.title}</p>
                <p className="kit-row__sub">{t.sub}</p>
              </div>
              <span className={`kit-row__amt ${t.pos ? 'kit-amt--pos' : 'kit-amt--neg'}`}>{t.amt}</span>
            </div>
          ))}
        </Card>
      </div>

      {/* Subscriptions + Bills */}
      <div className="kit-grid" style={{ gridTemplateColumns: '1fr 1fr' }}>
        <Card title="Subscriptions" eyebrow="$58 / mo · $96 / yr" action={<Badge color="honey" dot>2 renew soon</Badge>}>
          {subs.map((s, i) => (
            <div className="kit-sub" key={i}>
              <span className="kit-sub__logo" style={{ background: s.color }}>{s.letter}</span>
              <div className="kit-sub__main">
                <p className="kit-row__title">{s.name}</p>
                <p className="kit-row__sub">{s.price} · {s.cycle}</p>
              </div>
              {s.soon
                ? <Badge color="honey" icon={<Icon name="bell" />}>Renews {s.renews}</Badge>
                : <span className="kit-row__sub" style={{ fontFamily: 'var(--font-mono)' }}>Renews {s.renews}</span>}
            </div>
          ))}
        </Card>

        <Card title="Bills & recurring" eyebrow="June" action={<span className="kit-muted">$1,632 due</span>}>
          {bills.map((b, i) => (
            <div className="kit-sub" key={i}>
              <span className="kit-workout__ico" style={{ width: 38, height: 38, background: `var(--${b.tint}-100)`, color: `var(--${b.tint}-600)` }}><Icon name={b.icon} /></span>
              <div className="kit-sub__main">
                <p className="kit-row__title">{b.name}</p>
                <p className="kit-row__sub">{b.sub} · {b.due}</p>
              </div>
              <div style={{ textAlign: 'right', display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 3 }}>
                <span className="kit-row__amt">{b.amt}</span>
                {b.auto ? <Badge color="green">Autopay</Badge> : <Badge color="clay">Manual</Badge>}
              </div>
            </div>
          ))}
        </Card>
      </div>
    </div>
  )
}
