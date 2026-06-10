/* Scuffed OS — Top bar (greeting + search + record) */
import { Button, IconButton } from '../components/ui.jsx'
import { Icon } from '../lib/Icon.jsx'

export function TopBar({ title, subtitle, recording, onToggleRecord }) {
  return (
    <header className="kit-topbar">
      <div className="kit-greeting">
        <h1>{title}</h1>
        <p>{subtitle}</p>
      </div>
      <div className="kit-topbar__actions">
        <div className="kit-search">
          <Icon name="search" />
          <input placeholder="Ask your second brain…" />
        </div>
        <IconButton label="Notifications" variant="ghost"><Icon name="bell" /></IconButton>
        <Button variant={recording ? 'secondary' : 'primary'} iconLeft={<Icon name={recording ? 'square' : 'mic'} />} onClick={onToggleRecord}>
          {recording ? 'Stop' : 'Voice note'}
        </Button>
      </div>
    </header>
  )
}
