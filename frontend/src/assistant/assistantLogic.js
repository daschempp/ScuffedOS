/* Scuffed OS — shared assistant logic (local fallback).
   This is the same intent engine the design prototype shipped, ported to an ES
   module. The backend (backend/app/assistant.py) mirrors it server-side; the
   frontend uses this only when the API is unreachable, so the assistant still
   "works" offline. Exposes reply(text) -> { text, action? }. */

export function cleanTitle(text) {
  let t = text.replace(/^(hey |hi |ok |please |can you |could you |would you |i need to |i want to )+/i, '')
  t = t.replace(/^(add (a )?(task|reminder|to-?do)( to)?:?\s*|remind me to\s*|create (a )?task( to)?:?\s*|new task:?\s*|to-?do:?\s*|set a reminder to\s*)+/i, '')
  t = t.replace(/[.?!]+$/, '').trim()
  return t.charAt(0).toUpperCase() + t.slice(1)
}

export function cleanEvent(text) {
  let t = text.replace(/^(hey |hi |ok |please |can you |could you )+/i, '')
  t = t.replace(/^(schedule|book|set up|add|create|put in)( a| an| my)?( meeting| event| call| appointment)?( for| with| on| about)?:?\s*/i, '')
  t = t.replace(/[.?!]+$/, '').trim()
  return (t.charAt(0).toUpperCase() + t.slice(1)) || 'New event'
}

export function reply(text) {
  const t = text.toLowerCase()
  if (/plan (my|the) day|my day|what('?s| is) (on |up )?today|^agenda|brief me/.test(t)) {
    return { text: "Here's your day: <strong>4 tasks</strong>, a design standup at 11:30, and a dentist visit at 4. You're $120 under your dining budget and 410 kcal from your goal. Want me to block focus time this morning?",
      action: { icon: 'layout-dashboard', title: 'Day planned', meta: 'Focus block held · 9:00–10:30', cta: 'Open home', screen: 'home' } }
  }
  // explicit task phrasing wins over category keywords (e.g. "add a task to water the plants")
  if (/\b(add a task|task to|new task|remind me|to-?do|follow up)\b/.test(t)) {
    const et = cleanTitle(text)
    return { text: "Done — I've added <strong>" + et + '</strong> to your Tasks for today.',
      action: { icon: 'circle-check-big', title: 'Added to Tasks', meta: 'Today · tap to set a due date', cta: 'View tasks', screen: 'tasks', makeTask: et } }
  }
  if (/move|transfer|roll(\s|-)?over|put.*savings|into savings/.test(t) && /saving|dining|budget|\$|money/.test(t)) {
    return { text: 'Moved <strong>$120</strong> from Dining to Savings. You\'re still comfortably on budget for June.',
      action: { icon: 'wallet', title: 'Transfer complete', meta: '$120 → Savings', cta: 'View finance', screen: 'finance' } }
  }
  if (/spend|spent|budget|afford|cost|how much|finance|expense/.test(t)) {
    return { text: "You've spent <strong>$1,840</strong> in June — 12% less than May. Dining is your biggest discretionary category at <strong>$186</strong> of $250.",
      action: { icon: 'wallet', title: 'June spending', meta: '$1,840 / $2,400 budget', cta: 'View finance', screen: 'finance' } }
  }
  if (/schedule|meeting|calendar|book|appointment|event|invite/.test(t)) {
    const ev = cleanEvent(text)
    return { text: 'Scheduled <strong>' + ev + '</strong>. I found a free slot tomorrow afternoon and sent the invite.',
      action: { icon: 'calendar', title: 'Event created', meta: ev + ' · Tue 2:00pm', cta: 'Open calendar', screen: 'calendar' } }
  }
  if (/log|ate|eat|breakfast|lunch|dinner|meal|calorie|protein|snack|water|drank/.test(t)) {
    return { text: "Logged it. You're at <strong>1,910 kcal</strong> today and <strong>132g</strong> protein — 190 calories from your goal.",
      action: { icon: 'apple', title: 'Meal logged', meta: '+220 kcal · 18g protein', cta: 'View nutrition', screen: 'nutrition' } }
  }
  if (/remind|task|to-?do|todo|add|call|email|pay|renew|follow up|pick up|buy|order|book a/.test(t)) {
    const ti = cleanTitle(text)
    return { text: "Done — I've added <strong>" + ti + '</strong> to your Tasks for today.',
      action: { icon: 'circle-check-big', title: 'Added to Tasks', meta: 'Today · tap to set a due date', cta: 'View tasks', screen: 'tasks', makeTask: ti } }
  }
  if (/remember|note|memory|second brain|where did|what did i say/.test(t)) {
    return { text: "Saved to your second brain. I'll surface it when it's relevant — and you can ask me about it anytime.",
      action: { icon: 'brain', title: 'Stored in memory', meta: 'Tagged automatically', cta: 'Open brain', screen: 'memory' } }
  }
  return { text: "I can manage your tasks, calendar, finances and nutrition, or pull anything from your second brain. Tell me what you'd like — for example, “add a task to call the dentist” or “how much did I spend on dining?”" }
}
