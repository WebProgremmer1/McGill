import { useEffect } from 'react'
import Icon from './Icon.jsx'

// Match the page language so the date doesn't switch languages mid-header.
const today = () =>
  new Date().toLocaleDateString(document.documentElement.lang || 'en', { weekday: 'long', month: 'long', day: 'numeric' })

// Each dashboard is its own screen. The role comes only from the URL it was opened at.
export default function Shell({ family, heading, plainBrand = false, pageTitle, nav, action, footer, children }) {
  const title = heading || (family ? 'Care dashboard' : 'Patient dashboard')

  useEffect(() => {
    document.title = pageTitle || title
  }, [pageTitle, title])

  return (
    <>
      <a className="skip-link" href="#main">Skip to content</a>
      <header className="site-header app-bar">
        <span className="app-mark" aria-hidden="true"><Icon name="sun" /></span>
        <div className="app-title">
          {plainBrand
            ? <p className="brand person-name">What’s Next?</p>
            : <h1 className="brand person-name">{title}</h1>}
          <p className="app-subtitle">{plainBrand ? title : `What’s Next? · ${today()}`}</p>
        </div>
        {nav}
        {action && <div className="header-action">{action}</div>}
      </header>
      <main id="main" className={family ? 'page family-page' : 'page today-page'}>{children}</main>
      {footer && <footer>{footer}</footer>}
    </>
  )
}
