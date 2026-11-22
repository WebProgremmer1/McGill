import { useEffect, useRef, useState } from 'react'
import { firstName, initials, toTelHref } from './data/contacts.js'
import { riskLabel } from './data/careFeed.js'
import { liveMapUrl } from './data/journeyApi.js'
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

function PatientActions({ caregiverName, canMessage, canHelp, helpLabel, busy, onHelp, onSendMessage }) {
  const [open, setOpen] = useState(false)
  const [text, setText] = useState('')
  const [status, setStatus] = useState('')
  const [sending, setSending] = useState(false)
  const field = useRef(null)

  useEffect(() => {
    if (open) field.current?.focus()
  }, [open])

  async function submit(event) {
    event.preventDefault()
    if (sending) return
    if (!text.trim()) {
      setStatus('Write a message first.')
      return
    }
    setSending(true)
    setStatus('')
    try {
      await onSendMessage(text.trim())
      setText('')
      setStatus(caregiverName ? `Message sent to ${caregiverName}.` : 'Message sent.')
    } catch {
      setStatus('Your message didn’t send. Try again.')
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="patient-actions">
      {canHelp && (
        <button type="button" className="get-help" aria-disabled={busy} onClick={onHelp}>
          <Icon name="help" />{helpLabel}
        </button>
      )}
      {canMessage && (
        <>
          <button type="button" className="button secondary" aria-expanded={open} aria-controls="patient-message-form"
            onClick={() => setOpen(value => !value)}>
            <Icon name="message" />{caregiverName ? `Message ${caregiverName}` : 'Message caregiver'}
          </button>
          <form id="patient-message-form" className="reminder-form patient-message-form" hidden={!open} onSubmit={submit}>
            <label htmlFor="patient-message">Message to {caregiverName || 'caregiver'}</label>
            <textarea id="patient-message" ref={field} rows="3" maxLength="280" value={text}
              onChange={event => { setText(event.target.value); setStatus('') }} />
            <button type="submit" className="button primary" aria-disabled={sending}><Icon name="next" />Send message</button>
          </form>
          <p className="form-status" role="status">{status}</p>
        </>
      )}
    </div>
  )
}

function JourneyDetails({ journey, presenter = false, onMapProvider }) {
  return (
    <>
      <p className="journey-destination">Going to {journey.destination.name}</p>
      <div className="journey-panel">
        <JourneyMap journey={journey} presenter={presenter} onProviderChange={onMapProvider} />
        <div className="journey-strip">
          <p className="journey-fact"><span>Last known location</span><strong>{locationText(journey)}</strong></p>
        </div>
      </div>
    </>
  )
}

function TodayJourney({ journey, openDemo, options, canTravel, busy, onStart, onEnd, headingRef, detailsRef }) {
  const [mapProvider, setMapProvider] = useState(null)
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
      <SectionHeading id="journey-title" icon="pin" headingRef={headingRef}>
        {journey ? 'Journey' : 'Where would you like to go?'}
      </SectionHeading>
      {journey ? (
        <div id="journey-details" className="journey-details" ref={detailsRef} tabIndex={-1}>
          <JourneyDetails journey={journey} onMapProvider={setMapProvider} />
          <h3>Directions</h3>
          <p className="directions-note">Approximate, from the last known location.</p>
          <ol className="direction-steps">{directionSteps(journey).map((step, index) => <li key={`${index}-${step}`}>{step}</li>)}</ol>
          {openDemo && mapProvider === 'google' && (
            <a className="button secondary live-map-action" href={liveMapUrl(journey.id)} target="_blank" rel="noopener">
              <Icon name="pin" />Open live map (new tab)
            </a>
          )}
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
      ) : choices || <p>No places are ready right now.</p>}
    </section>
  )
}

const patientEmailText = {
  sending: 'Sending email…',
  accepted: 'Gmail accepted the email to your caregiver.',
  failed: 'The email didn’t send, but your request is on the care dashboard.',
}

const careEmailText = {
  not_sent: 'In-app alert only. No email was sent.',
  sending: 'Sending email…',
  accepted: 'Gmail accepted the email.',
  failed: 'The email failed. This alert is still here.',
}

function eventTime(event) {
  if (event.all_day) {
    const [year, month, day] = event.start.split('-').map(Number)
    return `${new Date(year, month - 1, day).toLocaleDateString([], { weekday: 'long', month: 'short', day: 'numeric' })} · All day`
  }
  const start = new Date(event.start)
  const dayText = start.toLocaleDateString([], { weekday: 'long', month: 'short', day: 'numeric' })
  return `${dayText} · ${start.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}`
}

function CalendarReminder({ calendar, care = false }) {
  const messages = {
    loading: 'Checking your calendar…',
    empty: 'No upcoming events.',
    not_configured: 'Calendar isn’t set up yet.',
    not_connected: calendar.canConnect ? 'Calendar isn’t connected.' : 'Calendar isn’t set up yet.',
    unavailable: 'Calendar is unavailable right now.',
  }
  return (
    <article className={care ? 'calendar-reminder care-calendar' : 'calendar-reminder'} data-calendar-state={calendar.state}>
      {!care && <p className="calendar-label"><Icon name="calendar" />Next on your calendar</p>}
      {calendar.state === 'ok' ? (
        <>
          <p className="calendar-title">{calendar.event.title}</p>
          <p className="calendar-time"><time dateTime={calendar.event.start}>{eventTime(calendar.event)}</time></p>
        </>
      ) : <p className="calendar-state">{messages[calendar.state] ?? messages.unavailable}</p>}
      {!care && calendar.canConnect && (
        <>
          <p className="calendar-consent">Connect Google to send help emails through Gmail and show Calendar events.</p>
          <a className="button secondary" href="/api/google/connect"><Icon name="signIn" />Connect Google</a>
        </>
      )}
    </article>
  )
}

export function TodayScreen({
  calendar, openDemo, checkIn, journey, help, reminder, sender, viewerIsRecipient, caregiver, helpLabel, confirmation, options, busy,
  controlsUnavailable, canTravel, canHelp, canMessage, caregiverName, onSendMessage, onKeepGoing, onAskForHelp, onStart, onEnd,
  remindersRef, journeyRef, detailsRef,
}) {
  const question = `Still heading to ${journey?.destination.name}?`
  const senderLine = sender?.relationship && viewerIsRecipient
    ? `${sender.name} · Your ${sender.relationship}`
    : sender?.name
  // A real event leads the card. Setup and error states stay below the caregiver's reminder.
  const calendarCard = calendar && <CalendarReminder calendar={calendar} />
  const eventFirst = calendar?.state === 'ok'
  return (
    <div className="today-view">
      <section className="today-section message-card" aria-labelledby="reminders-title">
        <SectionHeading id="reminders-title" icon="calendar" headingRef={remindersRef}>Reminders</SectionHeading>
        {eventFirst && calendarCard}
        {reminder ? (
          <article className="sender-reminder">
            <div className="reminder-from">
              {sender && <Portrait person={sender} />}
              <p>{sender ? senderLine : 'From your caregiver'}</p>
            </div>
            <p className="reminder-message">{reminder}{sender ? ` — ${firstName(sender)}` : ''}</p>
          </article>
        ) : <p className="reminder-message">No messages yet</p>}
        {!eventFirst && calendarCard}
      </section>
      <PatientActions caregiverName={caregiverName} canMessage={canMessage} canHelp={canHelp} helpLabel={helpLabel}
        busy={busy} onHelp={onAskForHelp} onSendMessage={onSendMessage} />
      <div className="today-confirmation-wrap">
        <p className="response today-confirmation" role="status">{confirmation}</p>
        <p className="email-status" role="status">{help ? patientEmailText[help.email_status] ?? '' : ''}</p>
        {help && <CallLink person={caregiver} />}
      </div>
      {checkIn && (
        <section className="check-in" aria-labelledby="check-in-title">
          <h2 id="check-in-title">{question}</h2>
          <div className="check-in-actions">
            <button className="button primary" aria-disabled={controlsUnavailable}
              onClick={controlsUnavailable ? undefined : onKeepGoing}><Icon name="check" />Keep going</button>
            <a className="button secondary" href="#journey-details"><Icon name="pin" />Show directions</a>
            {canHelp && (
              <button className="button secondary" aria-disabled={controlsUnavailable || Boolean(help)}
                onClick={controlsUnavailable || help ? undefined : onAskForHelp}><Icon name="help" />I need help</button>
            )}
          </div>
        </section>
      )}
      <TodayJourney journey={journey} openDemo={openDemo} options={options} canTravel={canTravel} busy={busy}
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
    <section className="panel care-reminder-panel" aria-labelledby="family-reminders-title">
      <SectionHeading id="family-reminders-title" icon="message">Send a reminder</SectionHeading>
      <form className="reminder-form" onSubmit={submit}>
        <label htmlFor="reminder-text">{name ? `Reminder for ${name}` : 'Reminder message'}</label>
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

function MessagesPanel({ messages }) {
  const time = value => new Date(value).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
  return (
    <section className="panel wide messages-panel" aria-labelledby="messages-title">
      <SectionHeading id="messages-title" icon="message">Messages</SectionHeading>
      {messages === undefined && <p>Loading…</p>}
      {messages === null && <p>Messages aren’t available on this server yet.</p>}
      {messages?.length === 0 && <p>No messages yet</p>}
      {messages?.length > 0 && (
        <ul className="message-list">
          {messages.slice(0, 10).map(item => (
            <li key={item.id}>
              <p className="message-meta">From {item.sender?.name ?? 'patient'} · {time(item.created_at)}</p>
              <p className="message-body">{item.body}</p>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function helpDetail(helpJourney) {
  if (!helpJourney) return 'Journey details aren’t available for this request.'
  if (helpJourney.destination.name === HELP_ONLY_PLACE) return 'Help was requested outside a journey. No location was recorded.'
  return `Help was requested during the walk to ${helpJourney.destination.name}. ${locationText(helpJourney)}`
}

function FeedAcknowledge({ entry, onAcknowledge }) {
  const [state, setState] = useState('idle')
  const done = entry.acknowledged || state === 'done'
  if (!entry.alertId) return null
  if (!onAcknowledge) return done ? <p className="feed-ack-state">Acknowledged</p> : null

  async function acknowledge() {
    if (done || state === 'saving') return
    setState('saving')
    try {
      await onAcknowledge(entry.alertId)
      setState('done')
    } catch {
      setState('failed')
    }
  }

  return (
    <div className="feed-ack">
      <button type="button" className="button secondary" aria-disabled={done || state === 'saving'} onClick={acknowledge}>
        {done ? 'Acknowledged' : state === 'saving' ? 'Saving…' : 'Acknowledge'}
      </button>
      {!done && <p className="feed-ack-note">Stops further caregiver emails for this alert. A new alert can still notify caregivers.</p>}
      <p className="feed-ack-status" role="status">{state === 'failed' ? 'Couldn’t acknowledge. Try again.' : ''}</p>
    </div>
  )
}

function CareFeed({ entries, journey, loaded, onAcknowledge }) {
  const time = value => new Date(value).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
  return (
    <section className="panel wide care-feed-panel" aria-labelledby="care-feed-title">
      <SectionHeading id="care-feed-title" icon="users">Caregiver feed</SectionHeading>
      {journey && <p className="care-feed-walk">Walk to {journey.destination.name} · Current risk: {riskLabel(journey.risk?.level)}{journey.risk ? ` · ${journey.risk.score}/100` : ''}</p>}
      {entries.length === 0 ? <p className="care-feed-empty">{loaded ? 'No recent activity' : 'Loading…'}</p> : (
        <ol className="care-feed">
          {entries.map(entry => (
            <li key={entry.id} data-feed-id={entry.id} data-feed-kind={entry.kind}>
              <p className="feed-text">{entry.title}</p>
              <p className="feed-meta"><time dateTime={entry.time}>{time(entry.time)}</time>{entry.place ? ` · ${entry.place}` : ''}</p>
              {entry.message && <p className="feed-message">{entry.message}</p>}
              {entry.details.length > 0 && <ul className="feed-reasons">{entry.details.map(detail => <li key={detail}>{detail}</li>)}</ul>}
              <FeedAcknowledge entry={entry} onAcknowledge={onAcknowledge} />
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}

function helpEmailText(settings) {
  if (!settings) return 'Checking…'
  if (settings.unavailable) return 'Unavailable right now'
  if (!settings.connected) return 'Not available in this browser'
  if (settings.ready) return 'On'
  if (!settings.recipient) return 'Off · no caregiver address'
  if (!settings.consent) return 'Off · waiting for caregiver consent'
  return 'Off · Gmail permission is missing'
}

function recipientText(settings) {
  if (!settings) return 'Checking…'
  if (settings.unavailable) return 'Unavailable right now'
  if (!settings.connected) return 'Connect Google on the Patient dashboard to view it.'
  return settings.recipient ?? 'Not configured'
}

function AccountPanel({ settings }) {
  return (
    <section className="panel wide account-panel" aria-labelledby="account-title">
      <SectionHeading id="account-title" icon="person">Account</SectionHeading>
      <h3>Email notifications</h3>
      <dl className="email-settings">
        <div><dt>Caregiver address</dt><dd className="email-recipient">{recipientText(settings)}</dd></div>
        <div><dt>Help emails</dt><dd className="help-email-state">{helpEmailText(settings)}</dd></div>
        <div><dt>Ordinary messages</dt><dd className="message-email-state">In the app only. Email opt-in is the next feature.</dd></div>
      </dl>
      <p className="settings-note">Set by the demo server. These settings are read-only.</p>
    </section>
  )
}

export function CaregiverDashboard({
  calendar, emailSettings, loaded, helpRequests = [], feed = [], feedJourney = null, onAcknowledge = null, helpTitle, journey, reminder, sender, recipient, openDemo, showCareTasks, messages, can, onSendReminder,
}) {
  const onlyHelp = helpRequests.length === 1 ? helpRequests[0] : null
  const canRemind = showCareTasks && can('send_reminders')
  const showCalendar = showCareTasks && Boolean(calendar)
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
      {(canRemind || showCalendar) && (
        <div className={canRemind && showCalendar ? 'care-top-row wide' : 'care-top-row care-top-row-single wide'}>
          {canRemind && <ReminderForm recipient={recipient} latest={reminder} sender={sender} onSend={onSendReminder} />}
          {showCalendar && (
            <section className="panel care-calendar-panel" aria-labelledby="care-calendar-title">
              <SectionHeading id="care-calendar-title" icon="calendar">Next on your calendar</SectionHeading>
              <CalendarReminder calendar={calendar} care />
            </section>
          )}
        </div>
      )}
      {showCareTasks && can('read_help') && (
        <section className={helpRequests.length ? 'panel wide help-panel has-request' : 'panel wide help-panel'} data-journey-id={onlyHelp?.alert.journey_id} aria-labelledby="help-title">
          <h2 id="help-title" className="icon-heading"><Icon name="help" />{helpRequests.length ? helpTitle : 'Help requests'}</h2>
          {helpRequests.length > 1 ? (
            <ol className="help-request-list">
              {helpRequests.map(({ alert, journey: requestJourney }) => (
                <li key={alert.id} data-alert-id={alert.id} data-journey-id={alert.journey_id}>
                  <p>{helpDetail(requestJourney)}</p>
                  <p className="email-status" role="status" data-email-status={alert.email_status}>{careEmailText[alert.email_status] ?? ''}</p>
                </li>
              ))}
            </ol>
          ) : (
            <>
              <p>{onlyHelp ? helpDetail(onlyHelp.journey) : loaded ? 'No help requests.' : 'Loading…'}</p>
              <p className="email-status" role="status" data-email-status={onlyHelp?.alert.email_status}>{onlyHelp ? careEmailText[onlyHelp.alert.email_status] ?? '' : ''}</p>
            </>
          )}
        </section>
      )}
      {showCareTasks && can('read_help') && <CareFeed entries={feed} journey={feedJourney} loaded={loaded} onAcknowledge={onAcknowledge} />}
      {showCareTasks && can('read_messages') && <MessagesPanel messages={messages} />}
      {showCareTasks && can('read_journey') && (
        <section className="panel wide" aria-labelledby="family-journey-title">
          <SectionHeading id="family-journey-title" icon="pin">Journey</SectionHeading>
          {journey ? <div className="journey-details"><JourneyDetails journey={journey} presenter={openDemo} /></div>
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
      {openDemo && <AccountPanel settings={emailSettings} />}
    </div>
  )
}
