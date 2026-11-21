import { useState } from 'react'
import { firstName, initials, toTelHref } from './data/contacts.js'
import { directionSteps, HELP_ONLY_PLACE, locationText, savedPlaces } from './data/places.js'
import Icon from './Icon.jsx'
import JourneyMap from './JourneyMap.jsx'

function SectionHeading({ id, icon, headingRef, children }) {
  return (
    <h2 id={id} className="icon-heading" ref={headingRef} tabIndex={headingRef ? -1 : undefined}>
      <Icon name={icon} />{children}
    </h2>
  )
}

function Portrait({ person }) {
  const [failed, setFailed] = useState(false)
  if (person.photo_url && !failed) {
    return <img className="contact-photo" src={person.photo_url} alt="" onError={() => setFailed(true)} />
  }
  return <span className="contact-photo contact-initials" aria-hidden="true">{initials(person) || <Icon name="person" />}</span>
}

function CallLink({ person }) {
  const href = toTelHref(person?.phone)
  if (!href) return null
  return <a className="button primary" href={href}><Icon name="phone" />Call {firstName(person)}</a>
}

export function GetHelp({ label, onClick, busy }) {
  return (
    <button type="button" className="get-help" aria-disabled={busy} onClick={onClick}>
      <Icon name="help" />{label}
    </button>
  )
}

function JourneyDetails({ journey }) {
  return (
    <>
      <p className="journey-destination">Going to {journey.destination.name}</p>
      <div className="journey-panel">
        <JourneyMap journey={journey} />
        <div className="journey-strip">
          <p className="journey-fact"><span>Last known location</span><strong>{locationText(journey)}</strong></p>
        </div>
      </div>
    </>
  )
}

function TodayJourney({ journey, options, canTravel, busy, onStart, onEnd, headingRef, detailsRef }) {
  const choices = canTravel && options.length > 0 && (
    <ul className="destination-list">
      {options.map(option => (
        <li key={option.id}>
          <button type="button" className="button destination-button" aria-disabled={busy} onClick={() => onStart(option)}>
            <Icon name={option.icon} />{option.label}
          </button>
        </li>
      ))}
    </ul>
  )

  return (
    <section className="today-section" aria-labelledby="journey-title">
      <SectionHeading id="journey-title" icon="pin" headingRef={headingRef}>Journey</SectionHeading>
      {journey ? (
        <div id="journey-details" className="journey-details" ref={detailsRef} tabIndex={-1}>
          <JourneyDetails journey={journey} />
          <h3>Directions</h3>
          <p className="directions-note">Approximate, from the last known location.</p>
          <ol className="direction-steps">{directionSteps(journey).map(step => <li key={step}>{step}</li>)}</ol>
          {choices}
          {canTravel && (
            <div className="journey-actions">
              <button type="button" className="button primary" aria-disabled={busy} onClick={() => onEnd('complete')}>
                <Icon name="check" />I’ve arrived
              </button>
              <button type="button" className="button secondary" aria-disabled={busy} onClick={() => onEnd('cancel')}>
                <Icon name="stop" />Stop journey
              </button>
            </div>
          )}
        </div>
      ) : (
        <>
          <h3 className="journey-question">Where would you like to go?</h3>
          {choices || <p>No places are ready right now.</p>}
        </>
      )}
    </section>
  )
}

export function TodayScreen({
  checkIn, journey, help, reminder, sender, viewerIsRecipient, caregiver, helpLabel, confirmation, options, busy,
  controlsUnavailable, canTravel, canHelp, onKeepGoing, onAskForHelp, onStart, onEnd, remindersRef, journeyRef, detailsRef,
}) {
  const question = `Still heading to ${journey?.destination.name}?`
  const senderLine = sender?.relationship && viewerIsRecipient
    ? `${sender.name} · Your ${sender.relationship}`
    : sender?.name
  return (
    <div className="today-view">
      {checkIn && (
        <section className="check-in" aria-labelledby="check-in-title">
          <h2 id="check-in-title">{question}</h2>
          <div className="check-in-actions">
            <button className="button primary" aria-disabled={controlsUnavailable}
              onClick={controlsUnavailable ? undefined : onKeepGoing}><Icon name="check" />Keep going</button>
            <a className="button secondary" href="#journey-details"><Icon name="pin" />Show directions</a>
            {canHelp && (
              <button className="button secondary" aria-disabled={controlsUnavailable || Boolean(help)}
                onClick={controlsUnavailable || help ? undefined : onAskForHelp}><Icon name="help" />{helpLabel}</button>
            )}
          </div>
        </section>
      )}
      <div className="today-confirmation-wrap">
        <p className="response today-confirmation" role="status">{confirmation}</p>
        {help && <CallLink person={caregiver} />}
      </div>
      <section className="today-section" aria-labelledby="reminders-title">
        <SectionHeading id="reminders-title" icon="calendar" headingRef={remindersRef}>Reminders</SectionHeading>
        {reminder ? (
          <article className="sender-reminder">
            {sender && (
              <div className="reminder-from">
                <Portrait person={sender} />
                <p>{senderLine}</p>
              </div>
            )}
            <p className="reminder-message">{reminder}{sender ? ` — ${firstName(sender)}` : ''}</p>
          </article>
        ) : <p>No reminders right now.</p>}
      </section>
      <TodayJourney journey={journey} options={options} canTravel={canTravel} busy={busy}
        onStart={onStart} onEnd={onEnd} headingRef={journeyRef} detailsRef={detailsRef} />
    </div>
  )
}

function ReminderForm({ recipient, latest, sender, onSend }) {
  const [text, setText] = useState('')
  const [status, setStatus] = useState('')
  const [sending, setSending] = useState(false)
  const name = firstName(recipient)
  const senderLine = sender?.relationship && name ? `${sender.name} · ${name}’s ${sender.relationship}` : sender?.name

  async function submit(event) {
    event.preventDefault()
    if (sending) return
    if (!text.trim()) {
      setStatus('Write a reminder first.')
      return
    }
    setSending(true)
    setStatus('')
    try {
      await onSend(text.trim())
      setText('')
      setStatus(name ? `Sent to ${name}.` : 'Reminder sent.')
    } catch {
      setStatus('Your reminder didn’t send. Try again.')
    } finally {
      setSending(false)
    }
  }

  return (
    <section className="panel" aria-labelledby="family-reminders-title">
      <SectionHeading id="family-reminders-title" icon="calendar">Reminders</SectionHeading>
      <form className="reminder-form" onSubmit={submit}>
        <label htmlFor="reminder-text">{name ? `Send a reminder to ${name}` : 'Send a reminder'}</label>
        <textarea id="reminder-text" rows="3" maxLength="140" value={text}
          onChange={event => { setText(event.target.value); setStatus('') }} />
        <button type="submit" className="button primary" aria-disabled={sending}><Icon name="next" />{name ? `Send to ${name}` : 'Send reminder'}</button>
        <p className="form-status" role="status">{status}</p>
      </form>
      {latest && (
        <div className="latest-reminder">
          {sender && (
            <div className="reminder-from">
              <Portrait person={sender} />
              <p>{senderLine}</p>
            </div>
          )}
          <p>{latest}</p>
        </div>
      )}
    </section>
  )
}

function helpDetail(helpJourney) {
  if (!helpJourney || helpJourney.destination.name === HELP_ONLY_PLACE) return 'Not on a journey. Location not available.'
  return `On the way to ${helpJourney.destination.name}. ${locationText(helpJourney)}`
}

export function CaregiverDashboard({
  loaded, help, helpTitle, helpJourney, journey, reminder, sender, recipient, openDemo, showCareTasks, can, onSendReminder,
}) {
  const cardTitle = recipient ? `Caring for ${recipient.name}` : openDemo ? 'Demo care recipient' : 'No one is linked yet.'
  return (
    <div className="family-view">
      <section className="caring-card wide" aria-labelledby="caring-title">
        {recipient && <Portrait person={recipient} />}
        <div className="contact-text">
          <h2 id="caring-title">{cardTitle}</h2>
          {recipient?.relationship && <span>Your {recipient.relationship}</span>}
        </div>
        {recipient && <CallLink person={recipient} />}
      </section>
      {showCareTasks && can('read_help') && (
        <section className={help ? 'panel help-panel has-request' : 'panel help-panel'} aria-labelledby="help-title">
          <h2 id="help-title" className="icon-heading"><Icon name="help" />{help ? helpTitle : 'Help requests'}</h2>
          <p>{help ? helpDetail(helpJourney) : loaded ? 'No help requests.' : 'Loading…'}</p>
        </section>
      )}
      {showCareTasks && can('send_reminders') && (
        <ReminderForm recipient={recipient} latest={reminder} sender={sender} onSend={onSendReminder} />
      )}
      {showCareTasks && can('read_journey') && (
        <section className="panel wide" aria-labelledby="family-journey-title">
          <SectionHeading id="family-journey-title" icon="pin">Journey</SectionHeading>
          {journey ? <div className="journey-details"><JourneyDetails journey={journey} /></div>
            : <p className="journey-empty">{loaded ? 'No journey right now.' : 'Loading…'}</p>}
        </section>
      )}
      {showCareTasks && can('read_journey') && (
        <section className="panel wide" aria-labelledby="saved-title">
          <h2 id="saved-title" className="icon-heading"><Icon name="home" />Saved locations</h2>
          <ul className="saved-places">
            {savedPlaces.map(place => (
              <li key={place.name}><Icon name={place.icon} />{place.name}
                {journey?.destination.name === place.name && <span>Current destination</span>}</li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}
