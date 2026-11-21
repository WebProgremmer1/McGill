import { useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { demoData, demoStore } from './data/demoStore.js'
import './App.css'

function Icon({ name, ...props }) {
  const paths = {
    sun: <><circle cx="12" cy="12" r="4" /><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5" /></>,
    walk: <><circle cx="14" cy="4" r="2" /><path d="m7 21 3-7 3 3v4M6 11l4-4 4 1 3 5h3M10 7l-1 7 6 2" /></>,
    check: <path d="m5 12 4 4L19 6" />,
    phone: <path d="M7 3H3v3c0 8 7 15 15 15h3v-4l-5-2-2 2a15 15 0 0 1-7-7l2-2-2-5Z" />,
    pin: <><path d="M20 10c0 6-8 12-8 12S4 16 4 10a8 8 0 1 1 16 0Z" /><circle cx="12" cy="10" r="2.5" /></>,
    heart: <path d="M12 21 3 12C-3 4 7-2 12 5c5-7 15-1 9 7Z" />,
    cup: <><path d="M4 8h13v7a5 5 0 0 1-5 5H9a5 5 0 0 1-5-5ZM17 9h2a3 3 0 0 1 0 6h-2M7 2v3m5-3v3" /></>,
  }
  return <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>{paths[name]}</svg>
}

const CHECK_IN_QUESTION = 'Still heading to Maple Market?'

function App() {
  const state = useSyncExternalStore(demoStore.subscribe, demoStore.getSnapshot)
  const family = window.location.pathname.replace(/\/$/, '') === '/manage'
  const announcement = useRef(null)
  const announced = useRef(null)

  useEffect(() => {
    document.title = `${family ? 'Family dashboard' : 'Today'} · What’s Next?`
  }, [family])

  const eventId = family ? state.contactRequest?.createdAt : state.checkIn?.id
  useEffect(() => {
    if (announced.current === eventId) return
    announced.current = eventId
    let message = ''
    if (eventId) {
      message = family
        ? 'New simulated contact request. Eleanor asked Maya for help.'
        : CHECK_IN_QUESTION
    }
    announcement.current.textContent = message
  }, [eventId, family])

  return (
    <>
      <a className="skip-link" href="#main">Skip to content</a>
      <header className="site-header">
        <a className="brand" href="/" aria-label="What’s Next? home"><span className="brand-symbol"><Icon name="sun" /></span>what’s next<span className="brand-question">?</span></a>
        <nav aria-label="Main navigation"><a href="/" aria-current={!family ? 'page' : undefined}>Today</a><a href="/manage" aria-current={family ? 'page' : undefined}>Family dashboard</a></nav>
        <span className="demo-label">Fictional demo</span>
      </header>
      <main id="main" className={family ? 'page family-page' : 'page today-page'}>
        {state.storageError && <p role="alert" className="error-banner">Browser storage is unavailable. Please allow local storage to sync this demo between tabs.</p>}
        {family ? <Family state={state} /> : <Today state={state} />}
      </main>
      <footer><span>Demo only · No location tracking or real calls</span></footer>
      <div ref={announcement} className="sr-only" role="status" aria-live="polite" aria-atomic="true" />
    </>
  )
}

function WalkingDirections() {
  return (
    <div className="directions">
      <h3>Your way to Maple Market</h3>
      <ol>{demoData.directions.map(step => <li key={step}>{step}</li>)}</ol>
      <p>Fictional route for this demo.</p>
    </div>
  )
}

function Today({ state }) {
  const [tripDirectionsOpen, setTripDirectionsOpen] = useState(false)
  const checkIn = state.checkIn
  const directionsOpen = checkIn ? checkIn.response === 'directions' : tripDirectionsOpen

  function showDirections() {
    if (checkIn) demoStore.respond('directions')
    else setTripDirectionsOpen(true)
  }

  return (
    <section className={checkIn ? 'trip-card check-in' : 'trip-card next-card'} aria-labelledby="trip-title">
      {!checkIn && <p className="eyebrow">YOUR NEXT WALK</p>}
      <h1 id="trip-title">{checkIn ? CHECK_IN_QUESTION : 'Maple Market'}</h1>
      {!checkIn && (
        <>
          <time className="next-time" dateTime="10:30">10:30 AM</time>
          <p>120 Maple Street · About a 10-minute walk</p>
        </>
      )}
      <div className="check-in-actions">
        {checkIn && (
          <button className="button primary" onClick={() => demoStore.respond('continue')}>
            <Icon name="check" />Keep going
          </button>
        )}
        <button className={checkIn ? 'button secondary' : 'button primary'} onClick={showDirections}
          aria-expanded={directionsOpen} aria-controls="trip-directions">
          <Icon name="pin" />{checkIn ? 'Show directions' : 'Get directions'}
        </button>
        {checkIn && (
          <button className="button secondary" onClick={() => demoStore.respond('contact')}>
            <Icon name="phone" />Ask Maya for help
          </button>
        )}
      </div>
      <p className="response" role="status">
        {checkIn?.response === 'continue' && 'Okay. Enjoy your walk to Maple Market.'}
      </p>
      <p className="response" role="status">
        {state.contactRequest && 'Your simulated help request was sent to Maya.'}
      </p>
      <div id="trip-directions" hidden={!directionsOpen}><WalkingDirections /></div>
    </section>
  )
}

function Family({ state }) {
  const { checkIn, contactRequest } = state
  return (
    <>
      <div className="page-heading">
        <div><h1>Family dashboard</h1><p>{demoData.person.name} · {demoData.day}, {demoData.date}</p></div>
      </div>
      <section className={contactRequest ? 'panel help-panel has-request' : 'panel help-panel'} aria-labelledby="help-title">
        <h2 id="help-title">{contactRequest ? 'Eleanor asked Maya for help' : 'Help requests'}</h2>
        {contactRequest ? (
          <p>Simulated request received at {new Date(contactRequest.createdAt).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}.</p>
        ) : <p>No help requests today.</p>}
      </section>
      <div className="family-grid">
        <section className="panel family-plan">
          <h2>Today’s schedule</h2>
          {demoData.activities.map(item => (
            <div className="plan-row" key={item.title}>
              <Icon name={item.icon} />
              <div><strong>{item.title}</strong><span>{item.detail}</span></div>
              <span>{item.time}{item.done && ' · Done'}</span>
            </div>
          ))}
        </section>
        <section className="panel demo-controls">
          <h2>Demo controls</h2>
          <button className="button primary" onClick={checkIn ? undefined : demoStore.simulateOffRoute} aria-disabled={Boolean(checkIn)}>
            <Icon name="walk" />Simulate off-route walk
          </button>
          <p className="simulation-status">
            {checkIn ? demoData.responses[checkIn.response] ?? 'Check-in sent. Waiting for Eleanor’s choice.' : 'Open Today in another tab to see the check-in.'}
          </p>
          <button className="text-button" onClick={demoStore.reset}>Reset demo</button>
          <p className="fine-print">Reset clears the check-in and help request in both tabs.</p>
        </section>
      </div>
    </>
  )
}

export default App
