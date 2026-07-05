/* Scuffed OS — Sidebar nav */
import React from 'react'
import { Avatar } from '../components/ui.jsx'
import { Icon } from '../lib/Icon.jsx'

export function Sidebar({ active, onNavigate }) {
  const sections = [
    { items: [
      { id: 'home', label: 'Home', icon: 'house' },
      { id: 'calendar', label: 'Calendar', icon: 'calendar', badge: '3' },
      { id: 'tasks', label: 'Tasks', icon: 'circle-check-big', badge: '5' },
      { id: 'habits', label: 'Habits', icon: 'repeat' },
    ] },
    { label: 'Health', items: [
      { id: 'nutrition', label: 'Nutrition', icon: 'apple' },
      { id: 'fitness', label: 'Fitness', icon: 'activity' },
    ] },
    { label: 'Money', items: [
      { id: 'finance', label: 'Finance', icon: 'wallet' },
    ] },
    { label: 'Inbox & people', items: [
      { id: 'email', label: 'Email', icon: 'mail', badge: '4' },
      { id: 'people', label: 'People', icon: 'users' },
    ] },
    { label: 'Intelligence', items: [
      { id: 'memory', label: 'Second Brain', icon: 'brain' },
    ] },
    { label: 'School', items: [
      { id: 'school', label: 'School', icon: 'graduation-cap' },
    ] },
  ]
  const Item = (it) => (
    <button key={it.id} className={`kit-navitem ${active === it.id ? 'kit-navitem--active' : ''}`} onClick={() => onNavigate(it.id)}>
      <Icon name={it.icon} />
      <span>{it.label}</span>
      {it.badge && <span className="kit-navitem__badge">{it.badge}</span>}
    </button>
  )
  return (
    <nav className="kit-sidebar">
      <div className="kit-sidebar__logo">
        <img src="/assets/logo-mark.svg" alt="" />
        <span className="kit-sidebar__word">Scuffed <span>OS</span></span>
      </div>
      <div className="kit-sidebar__nav">
        {sections.map((s, i) => (
          <React.Fragment key={i}>
            {s.label && <div className="kit-navlabel">{s.label}</div>}
            {s.items.map(Item)}
          </React.Fragment>
        ))}
      </div>
      <button className="kit-navitem" onClick={() => onNavigate('settings')}>
        <Icon name="settings" /><span>Settings</span>
      </button>
      <div className="kit-sidebar__user">
        <Avatar name="Sam Rivera" size="sm" tint="green" />
        <div>
          <div className="nm">Sam Rivera</div>
          <div className="sub">Synced · just now</div>
        </div>
      </div>
    </nav>
  )
}
