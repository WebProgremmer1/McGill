import { useEffect } from 'react'

// Each dashboard is its own screen. The role comes only from the URL it was opened at.
export default function Shell({ family, heading, plainBrand = false, action, footer, children }) {
  const title = heading || (family ? 'Care dashboard' : 'Today')

  useEffect(() => {
    document.title = title
  }, [title])

  return (
    <>
      <a className="skip-link" href="#main">Skip to content</a>
      <header className="site-header">
        {plainBrand
          ? <p className="brand person-name">What’s Next?</p>
          : <h1 className="brand person-name">{title}</h1>}
        {action && <div className="header-action">{action}</div>}
      </header>
      <main id="main" className={family ? 'page family-page' : 'page today-page'}>{children}</main>
      {footer && <footer>{footer}</footer>}
    </>
  )
}
