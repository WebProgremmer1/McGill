import { carePath } from './data/careRoutes.js'
import Icon from './Icon.jsx'
import './CareNav.css'

export default function CareNav({ base, view, showMessages, unread, onNavigate }) {
  const link = (target, icon, label, extra = null) => (
    <a href={carePath(base, target)} aria-current={view === target ? 'page' : undefined} onClick={event => onNavigate(event, target)}>
      <Icon name={icon} />{label}{extra}
    </a>
  )
  return (
    <nav className="care-nav" aria-label="Care dashboard">
      {link('home', 'home', 'Home')}
      {showMessages && link('messages', 'message', 'Messages', unread > 0 && (
        <>
          <span className="care-nav-badge" aria-hidden="true" data-unread={unread}>{unread > 99 ? '99+' : unread}</span>
          <span className="sr-only">, {unread} unread</span>
        </>
      ))}
      {link('account', 'person', 'Account')}
    </nav>
  )
}
