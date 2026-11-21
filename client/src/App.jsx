import { useEffect, useRef, useSyncExternalStore } from 'react'
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
        : 'Still heading to the grocery store? Choose Keep going, Show directions, or Ask Maya for help.'
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
      <footer><span className="footer-mark">A little support. More independence.</span><span>Demo only · No location tracking or real calls</span></footer>
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
  const response = state.checkIn?.response
  return <>
    <div className="page-heading"><div><p className="eyebrow">YOUR DAY, AT YOUR PACE</p><h1>Good morning, {demoData.person.firstName}.</h1><p>One thing at a time. You’ve got this.</p></div><div className="date-block"><Icon name="sun" /><span>{demoData.day}<strong>{demoData.date}</strong></span></div></div>
    {state.checkIn && <section className="check-in" aria-labelledby="check-in-title">
      <div className="check-in-heading"><span className="icon-tile"><Icon name="heart" /></span><div><p className="eyebrow">A QUICK CHECK-IN</p><h2 id="check-in-title">Still heading to the grocery store?</h2></div></div>
      <p>You can carry on, see the way, or ask your daughter Maya to get in touch.</p>
      <div className="check-in-actions">
        <button className="button primary" onClick={() => demoStore.respond('continue')}><Icon name="check" />Keep going</button>
        <button className="button secondary" onClick={() => demoStore.respond('directions')}><Icon name="pin" />Show directions</button>
        <button className="button secondary" onClick={() => demoStore.respond('contact')}><Icon name="phone" />Ask Maya for help</button>
      </div>
      <p className="response" role="status">{response === 'contact' ? 'Maya has a simulated request to call you. No real call was placed.' : response === 'continue' ? 'Okay. Enjoy your walk — take your time.' : response === 'directions' ? 'Your walking directions are below.' : ''}</p>
      {response === 'directions' && <WalkingDirections />}
    </section>}
    <div className="today-layout"><div>
      <section className="next-card" aria-labelledby="next-title">
        <div className="card-top">
          <span className="pill">UP NEXT</span>
          <span className="activity-illustration"><Icon name="walk" width="42" height="42" /></span>
        </div>
        <h2 id="next-title">A walk to the grocery store</h2>
        <time className="next-time" dateTime="10:30">10:30 AM</time>
        <p>A little fresh air, a few things for home.</p>
        <div className="destination">
          <Icon name="pin" />
          <div>
            <strong>Maple Market</strong>
            <span>120 Maple Street · About 10 minutes away</span>
            <a className="directions-link" href="#market-directions">Get directions</a>
          </div>
        </div>
        <div id="market-directions" tabIndex={-1}><WalkingDirections /></div>
        <div className="shopping-note"><span>YOUR LITTLE LIST</span><p>Bread, apples, and milk</p></div>
      </section>
      <div className="reassurance"><Icon name="heart" /><p>There’s no rush.<br /><strong>Your day is yours to enjoy.</strong></p></div>
    </div><aside className="day-plan" aria-labelledby="plan-title"><div className="section-title"><h2 id="plan-title">The rest of today</h2><span>A gentle plan</span></div><ol className="timeline">{demoData.activities.map(item => <li key={item.title} className={item.done ? 'completed' : ''}><span className="timeline-icon"><Icon name={item.icon} /></span><div><span className="activity-time">{item.time}{item.done && ' · Done'}</span><h3>{item.title}</h3><p>{item.detail}</p></div></li>)}</ol><div className="support-card"><span className="avatar" aria-hidden="true">M</span><div><strong>Maya is in your corner</strong><p>Your daughter, a little closer.</p></div></div></aside></div>
  </>
}

function Family({ state }) {
  const pending = state.contactRequest
  return <>
    <div className="page-heading"><div><p className="eyebrow">CONNECTED, WITH CARE</p><h1>A little peace of mind.</h1><p>Welcome, Maya. Here’s {demoData.person.firstName}’s day at a glance.</p></div><span className="family-badge"><Icon name="heart" /> Family dashboard</span></div>
    <div className="family-grid"><section className="panel person-panel"><div className="person-heading"><span className="avatar large">E</span><div><h2>{demoData.person.name}</h2><p>Your mother · Fictional profile</p></div></div><div className="person-status"><span className="status-dot" /><strong>{state.checkIn ? 'A gentle check-in was sent' : 'A familiar day ahead'}</strong></div><p>{state.checkIn ? 'Eleanor can choose what feels right for her.' : 'Today’s plan is ready, with room to go at her own pace.'}</p><div className="mini-next"><Icon name="walk" /><div><span>ON THE PLAN · 10:30 AM</span><strong>Walk to Maple Market</strong></div></div></section>
    <section className={`panel contact-panel ${pending ? 'has-request' : ''}`} aria-labelledby="contact-title"><div className="section-title"><h2 id="contact-title">Contact requests</h2><Icon name="phone" /></div><div>{pending ? <div className="contact-request"><span className="pill">SIMULATED REQUEST</span><h3>Eleanor would like a call.</h3><p>She selected “Ask Maya for help” on her Today board.</p><p className="request-time">Requested at {new Date(pending.createdAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</p></div> : <div className="empty-contact"><span className="icon-tile"><Icon name="heart" /></span><h3>All quiet here.</h3><p>If Eleanor asks to connect, you’ll see it here.</p></div>}</div><p className="fine-print">This demo does not place calls or send notifications.</p></section>
    <section className="panel family-plan"><div className="section-title"><h2>Today’s plan</h2><span>{demoData.date}</span></div>{demoData.activities.map(item => <div className="plan-row" key={item.title}><Icon name={item.icon} /><div><strong>{item.title}</strong><span>{item.detail}</span></div><span>{item.time}</span></div>)}</section>
    <section className="panel demo-controls"><p className="eyebrow">TRY THE DEMO</p><h2>A gentle nudge, when it helps.</h2><p>Simulate a walk away from the planned route. Eleanor’s Today board will offer a simple check-in.</p><button className="button primary" onClick={state.checkIn ? undefined : demoStore.simulateOffRoute} aria-disabled={Boolean(state.checkIn)}><Icon name="walk" />Simulate off-route walk</button><p className="simulation-status">{state.checkIn ? `Check-in sent to Today.${state.checkIn.response ? ` ${demoData.responses[state.checkIn.response]}` : ' Waiting for Eleanor’s choice.'}` : 'Ready to simulate. Open Today in another tab.'}</p><button className="text-button" onClick={demoStore.reset}>Reset demo</button><p className="fine-print">Reset clears the check-in and contact request in both tabs.</p></section></div>
  </>
}

export default App
