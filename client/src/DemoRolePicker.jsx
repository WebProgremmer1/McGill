import { useEffect } from 'react'
import Icon from './Icon.jsx'
import './DemoRolePicker.css'

// Plain links: the URL is the role, so no session, account, or browser setting is created.
const roles = [
  { href: '/manage', label: 'I’m a caregiver', opens: 'Opens Care dashboard', icon: 'users' },
  { href: '/', label: 'I’m signing up for myself', opens: 'Opens Patient dashboard', icon: 'person' },
]

export default function DemoRolePicker() {
  useEffect(() => {
    document.title = 'Choose your role · What’s Next?'
  }, [])

  return (
    <main className="role-picker">
      <picture className="role-picker-art">
        <source media="(prefers-reduced-motion: reduce)" srcSet="/hero-aesthetic-still.svg" />
        <img src="/hero-aesthetic.svg" alt="" />
      </picture>
      <h1 className="sr-only">Choose your role.</h1>
      <div className="role-picker-cards">
        {roles.map(role => (
          <a className="demo-role-card" href={role.href} key={role.href}>
            <Icon name={role.icon} className="demo-role-card-icon" />
            <span className="demo-role-card-label">{role.label}</span>
            <span className="demo-role-card-opens">{role.opens} <span aria-hidden="true">→</span></span>
          </a>
        ))}
      </div>
    </main>
  )
}
