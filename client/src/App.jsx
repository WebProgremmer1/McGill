import { useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { demoData, demoStore } from './data/demoStore.js'
import AccessGate from './AccessGate.jsx'
import BackendDemo from './BackendDemo.jsx'
import { authRequired } from './data/accountApi.js'
import { careRoute } from './data/careRoutes.js'
import Icon from './Icon.jsx'
import Shell from './Shell.jsx'
import SignUp from './SignUp.jsx'
import './App.css'

const CHECK_IN_QUESTION = 'Still heading to Maple Market?'

function App() {
  if (window.location.pathname.replace(/\/$/, '') === '/signup') return <SignUp />
  // Auth mode has no mock or unscoped route, so React cannot show data before the server allows it.
  const accountRoute = /^\/(onboarding|test-session|c)(\/|$)/.test(window.location.pathname)
  return authRequired || accountRoute ? <AccessGate /> : <OpenDemo />
}

function OpenDemo() {
  const family = Boolean(careRoute(window.location.pathname))
  const mock = new URLSearchParams(window.location.search).get('mode') === 'mock'
  const roleLink = <a className="directions-link" href="/signup">Back to role selection</a>

  if (!mock) return <BackendDemo family={family} shell={{ footer: roleLink }} />
  return (
    <Shell family={family} plainBrand footer={
      <>
        <a className="directions-link" href={window.location.pathname}>Use backend demo</a>
        {roleLink}
      </>
    }>
      <MockDemo family={family} />
    </Shell>
  )
}

function MockDemo({ family }) {
  const state = useSyncExternalStore(demoStore.subscribe, demoStore.getSnapshot)
  const eventId = family ? state.contactRequest?.createdAt : state.checkIn?.id
  const region = useRef(null)
  const announced = useRef(null)
  useEffect(() => {
    if (announced.current === eventId) return
    announced.current = eventId
    region.current.textContent = eventId
      ? (family ? 'New simulated help request.' : CHECK_IN_QUESTION)
      : ''
  }, [eventId, family])
  return <>
    <div ref={region} className="sr-only" role="status" aria-live="polite" aria-atomic="true" />
    {state.storageError && <p role="alert" className="error-banner">Browser storage is unavailable. Please allow local storage to sync this demo between tabs.</p>}
    {family ? <Family state={state} /> : <Today state={state} />}
  </>
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
            <Icon name="help" />Get help
          </button>
        )}
      </div>
      <p className="response" role="status">
        {checkIn?.response === 'continue' && 'Okay. Enjoy your walk to Maple Market.'}
      </p>
      <p className="response" role="status">
        {state.contactRequest && 'Your simulated help request is on the care dashboard.'}
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
        <div><h1>Care dashboard</h1><p>{demoData.day}, {demoData.date}</p></div>
      </div>
      <section className={contactRequest ? 'panel help-panel has-request' : 'panel help-panel'} aria-labelledby="help-title">
        <h2 id="help-title">{contactRequest ? 'A help request is waiting.' : 'Help requests'}</h2>
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
            {checkIn ? demoData.responses[checkIn.response] ?? 'Check-in sent. Waiting for a response.' : 'Open Patient dashboard in another window to see the check-in.'}
          </p>
          <button className="text-button" onClick={demoStore.reset}>Reset demo</button>
          <p className="fine-print">Reset clears the check-in and help request in both tabs.</p>
        </section>
      </div>
    </>
  )
}

export default App
