import { useEffect, useRef, useState } from 'react'
import ChatPanel from './ChatPanel.jsx'
import { firstName, initials, toTelHref } from './data/contacts.js'
import { riskLabel, withoutPlaceholderName } from './data/careFeed.js'
import { directionSteps, HELP_ONLY_PLACE, locationText, savedPlaces } from './data/places.js'
import Icon from './Icon.jsx'
import JourneyMap from './JourneyMap.jsx'
import './PatientDashboard.css'

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

function JourneyDetails({ journey, presenter = false, wayfinding = false, onMove = null }) {
  return (
    <>
      <p className="journey-destination">Going to {journey.destination.name}</p>
      <div className="journey-panel">
        <JourneyMap journey={journey} presenter={presenter} wayfinding={wayfinding} onMove={onMove} />
        {!wayfinding && (
          <div className="journey-strip">
            <p className="journey-fact"><span>Last known location</span><strong>{locationText(journey)}</strong></p>
          </div>
        )}
      </div>
    </>
  )
}

function TodayJourney({ journey, options, canTravel, busy, onStart, onEnd, onMove, headingRef, detailsRef }) {
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
    <section className="today-section patient-journey" aria-labelledby="journey-title">
      <SectionHeading id="journey-title" icon="pin" headingRef={headingRef}>
        {journey ? 'Journey' : 'Where would you like to go?'}
      </SectionHeading>
      {journey ? (
        <div id="journey-details" className="journey-details" ref={detailsRef} tabIndex={-1}>
          <JourneyDetails journey={journey} wayfinding onMove={onMove} />
          <h3>Directions</h3>
          <p className="directions-note">Approximate, from the last known location.</p>
          <ol className="direction-steps">{directionSteps(journey).map((step, index) => <li key={`${index}-${step}`}>{step}</li>)}</ol>
          <p className="patient-location"><span>Last known location</span><strong>{locationText(journey)}</strong></p>
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
  not_sent: 'In-app alert only. No email was sent.',
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
  // Match the page language (like the header date), not the browser's, so the app reads in one language.
  const lang = document.documentElement.lang || 'en'
  if (event.all_day) {
    const [year, month, day] = event.start.split('-').map(Number)
    return `${new Date(year, month - 1, day).toLocaleDateString(lang, { weekday: 'long', month: 'short', day: 'numeric' })} · All day`
  }
  const start = new Date(event.start)
  const dayText = start.toLocaleDateString(lang, { weekday: 'long', month: 'short', day: 'numeric' })
  return `${dayText} · ${start.toLocaleTimeString(lang, { hour: 'numeric', minute: '2-digit' })}`
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
    <article className="calendar-reminder care-calendar" data-calendar-state={calendar.state}>
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
  calendar, defaultPatientName = null, checkIn, journey, help, reminder, sender, viewerIsRecipient, caregiver, helpLabel, confirmation, options, busy,
  controlsUnavailable, canTravel, canHelp, chat, onKeepGoing, onAskForHelp, onStart, onEnd, onMoveLocation,
  remindersRef, journeyRef, detailsRef,
}) {
  const question = `Still heading to ${journey?.destination.name}?`
  const senderLine = sender?.relationship && viewerIsRecipient
    ? `${sender.name} · Your ${sender.relationship}`
    : sender?.name
  const layout = ['today-view', 'patient-dashboard', checkIn && 'has-check-in', !calendar && 'no-calendar'].filter(Boolean).join(' ')
  // The source order is the phone order. On desktop, CSS places these sections in the two-column grid.
  return (
    <div className={layout}>
      <div className="patient-actions patient-help">
        {canHelp && (
          <button type="button" className="get-help" aria-disabled={busy} onClick={onAskForHelp}>
            <Icon name="help" />{helpLabel}
          </button>
        )}
        <div className="today-confirmation-wrap">
          <p className="response today-confirmation" role="status">{confirmation}</p>
          <p className="email-status" role="status">{help ? patientEmailText[help.email_status] ?? '' : ''}</p>
          {help && <CallLink person={caregiver} />}
        </div>
      </div>
      {checkIn && (
        <section className="check-in" aria-labelledby="check-in-title">
          <h2 id="check-in-title">{question}</h2>
          {checkIn.message && <p className="check-in-message">{withoutPlaceholderName(checkIn.message, defaultPatientName)}</p>}
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
      <TodayJourney journey={journey} options={options} canTravel={canTravel} busy={busy}
        onStart={onStart} onEnd={onEnd} onMove={onMoveLocation} headingRef={journeyRef} detailsRef={detailsRef} />
      <section className="today-section message-card" aria-labelledby="reminders-title">
        <SectionHeading id="reminders-title" icon="check" headingRef={remindersRef}>Reminders</SectionHeading>
        {reminder ? (
          <article className="sender-reminder">
            <div className="reminder-from">
              {sender && <Portrait person={sender} />}
              <p>{sender ? senderLine : 'From your caregiver'}</p>
            </div>
            <p className="reminder-message">{reminder}{sender ? ` — ${firstName(sender)}` : ''}</p>
          </article>
        ) : <p className="reminder-message">No reminders yet.</p>}
      </section>
      {calendar && (
        <section className="today-section patient-calendar" aria-labelledby="patient-calendar-title">
          <SectionHeading id="patient-calendar-title" icon="calendar">Next on your calendar</SectionHeading>
          <CalendarReminder calendar={calendar} />
        </section>
      )}
      {chat && <ChatPanel className="today-section patient-messages" {...chat} />}
    </div>
  )
}

function ReminderForm({ recipient, latest, sender, onSend, text, setText }) {
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

function HelpRequestAction({ alert, onAcknowledge, onHandled }) {
  const [state, setState] = useState('idle')
  if (!onAcknowledge) return null

  async function markHandled() {
    if (state === 'saving') return
    setState('saving')
    try {
      await onAcknowledge(alert.id)
      onHandled() // Stays busy until the refreshed list removes this request.
    } catch {
      setState('failed')
    }
  }

  return (
    <div className="help-action">
      <button type="button" className="button secondary" aria-disabled={state === 'saving'} aria-describedby={`help-detail-${alert.id}`} onClick={markHandled}>
        <Icon name="check" />{state === 'saving' ? 'Saving…' : 'Mark as handled'}
      </button>
      <p className="help-action-error" role="status">{state === 'failed' ? 'Couldn’t mark this as handled. Try again.' : ''}</p>
    </div>
  )
}

function CareFeed({ entries, journey, loaded, onAcknowledge, hiddenIds, onHide }) {
  const panel = useRef(null)
  const heading = useRef(null)
  const focusAfter = useRef(null)
  const visible = entries.filter(entry => !hiddenIds.has(entry.id))

  // The pressed button disappears, so keyboard users continue from the nearest control.
  useEffect(() => {
    const target = focusAfter.current
    if (!target) return
    focusAfter.current = null
    const button = panel.current?.querySelector(`[data-feed-id="${CSS.escape(target)}"] .feed-hide`)
    ;(button ?? heading.current)?.focus()
  }, [hiddenIds])

  function hide(entry) {
    const index = visible.findIndex(item => item.id === entry.id)
    focusAfter.current = (visible[index + 1] ?? visible[index - 1])?.id ?? 'heading'
    onHide(entry.id)
  }

  const time = value => new Date(value).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
  return (
    <section ref={panel} className="panel wide care-feed-panel" aria-labelledby="care-feed-title">
      <SectionHeading id="care-feed-title" icon="users" headingRef={heading}>Caregiver feed</SectionHeading>
      {journey && <p className="care-feed-walk">Walk to {journey.destination.name} · Current risk: {riskLabel(journey.risk?.level)}{journey.risk ? ` · ${journey.risk.score}/100` : ''}</p>}
      {visible.length === 0 ? <p className="care-feed-empty">{loaded ? 'No recent activity' : 'Loading…'}</p> : (
        <ol className="care-feed">
          {visible.map(entry => (
            <li key={entry.id} className="feed-entry" data-feed-id={entry.id} data-feed-kind={entry.kind}>
              <button type="button" className="feed-hide" aria-label="Hide from feed" onClick={() => hide(entry)}><Icon name="close" /></button>
              <p className="feed-text">{entry.title}</p>
              <p className="feed-meta"><time dateTime={entry.time}>{time(entry.time)}</time>{entry.place ? ` · ${entry.place}` : ''}</p>
              {entry.message && <p className="feed-message">{entry.message}</p>}
              {entry.emailStatus && <p className="email-status" data-email-status={entry.emailStatus}>{careEmailText[entry.emailStatus] ?? ''}</p>}
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

function missingEmailSteps(settings) {
  if (!settings || settings.unavailable || settings.ready) return []
  if (!settings.connected) return ['Connect the approved Google account on the Patient dashboard in this browser.']
  return [
    !settings.gmail && 'Reconnect Google and allow Gmail sending.',
    !settings.recipient && 'Set HELP_EMAIL_TO on the server.',
    !settings.consent && 'Set HELP_EMAIL_CONSENT=yes after the caregiver agrees.',
  ].filter(Boolean)
}

export function AccountPanel({ settings, openDemo, account, onSignOut, headingRef }) {
  const missing = missingEmailSteps(settings)
  return (
    <section className="panel wide account-panel" aria-labelledby="account-title">
      <SectionHeading id="account-title" icon="person" headingRef={headingRef}>Account</SectionHeading>
      {account?.name && <p>Signed in as {account.name}</p>}
      {onSignOut && <button type="button" className="button secondary account-signout" onClick={onSignOut}><Icon name="signOut" />Sign out</button>}
      {openDemo && <>
      <h3>Email notifications</h3>
      <dl className="email-settings">
        <div><dt>Caregiver address</dt><dd className="email-recipient">{recipientText(settings)}</dd></div>
        <div><dt>Help emails</dt><dd className="help-email-state">{helpEmailText(settings)}</dd></div>
        {missing.length > 0 && (
          <div><dt>Needed for help emails</dt><dd><ul className="email-missing">{missing.map(step => <li key={step}>{step}</li>)}</ul></dd></div>
        )}
        <div><dt>Ordinary messages</dt><dd className="message-email-state">In the app only. Email opt-in is the next feature.</dd></div>
      </dl>
      <p className="settings-note">Set by the demo server. These settings are read-only.</p>
      </>}
    </section>
  )
}

export function CaregiverDashboard({
  calendar, loaded, helpRequests = [], feed = [], feedJourney = null, onAcknowledge = null, helpTitle, journey, reminder, sender, recipient, openDemo, showCareTasks, can, onSendReminder, onMoveLocation = null, reminderDraft, onReminderDraft, hiddenFeed, onHideFeed,
}) {
  const onlyHelp = helpRequests.length === 1 ? helpRequests[0] : null
  const helpHeading = useRef(null)
  const focusHelpHeading = useRef(false)
  const patientName = firstName(recipient)
  // The handled button disappears, so keyboard users continue from the Help requests heading.
  useEffect(() => {
    if (!focusHelpHeading.current) return
    focusHelpHeading.current = false
    helpHeading.current?.focus()
  }, [helpRequests.length])
  const handled = () => { focusHelpHeading.current = true }
  const canRemind = showCareTasks && can('send_reminders')
  const showCalendar = showCareTasks && Boolean(calendar)
  const cardTitle = recipient ? `Caring for ${recipient.name}` : 'No one is linked yet.'
  return (
    <div className="family-view">
      {!openDemo && (
        <section className="caring-card wide" aria-labelledby="caring-title">
          {recipient && <Portrait person={recipient} />}
          <div className="contact-text">
            <h2 id="caring-title">{cardTitle}</h2>
            {recipient?.relationship && <span>Your {recipient.relationship}</span>}
          </div>
          {recipient && <CallLink person={recipient} />}
        </section>
      )}
      {(canRemind || showCalendar) && (
        <div className={canRemind && showCalendar ? 'care-top-row wide' : 'care-top-row care-top-row-single wide'}>
          {canRemind && <ReminderForm recipient={recipient} latest={reminder} sender={sender} onSend={onSendReminder} text={reminderDraft} setText={onReminderDraft} />}
          {showCalendar && (
            <section className="panel care-calendar-panel" aria-labelledby="care-calendar-title">
              <SectionHeading id="care-calendar-title" icon="calendar">{patientName ? `Next on ${patientName}’s calendar` : 'Next on the patient’s calendar'}</SectionHeading>
              <CalendarReminder calendar={calendar} care />
            </section>
          )}
        </div>
      )}
      {showCareTasks && can('read_help') && (
        <section className={helpRequests.length ? 'panel wide help-panel has-request' : 'panel wide help-panel'} data-journey-id={onlyHelp?.alert.journey_id} aria-labelledby="help-title">
          <h2 id="help-title" ref={helpHeading} tabIndex={-1} className="icon-heading"><Icon name="help" />{helpRequests.length ? helpTitle : 'Help requests'}</h2>
          {helpRequests.length > 1 ? (
            <ol className="help-request-list">
              {helpRequests.map(({ alert, journey: requestJourney }) => (
                <li key={alert.id} data-alert-id={alert.id} data-journey-id={alert.journey_id}>
                  <p id={`help-detail-${alert.id}`}>{helpDetail(requestJourney)}</p>
                  <p className="email-status" role="status" data-email-status={alert.email_status}>{careEmailText[alert.email_status] ?? ''}</p>
                  <HelpRequestAction alert={alert} onAcknowledge={onAcknowledge} onHandled={handled} />
                </li>
              ))}
            </ol>
          ) : (
            <>
              <p id={onlyHelp ? `help-detail-${onlyHelp.alert.id}` : undefined}>{onlyHelp ? helpDetail(onlyHelp.journey) : loaded ? 'No help requests.' : 'Loading…'}</p>
              <p className="email-status" role="status" data-email-status={onlyHelp?.alert.email_status}>{onlyHelp ? careEmailText[onlyHelp.alert.email_status] ?? '' : ''}</p>
              {onlyHelp && <HelpRequestAction key={onlyHelp.alert.id} alert={onlyHelp.alert} onAcknowledge={onAcknowledge} onHandled={handled} />}
            </>
          )}
        </section>
      )}
      {showCareTasks && can('read_help') && <CareFeed entries={feed} journey={feedJourney} loaded={loaded} onAcknowledge={onAcknowledge} hiddenIds={hiddenFeed} onHide={onHideFeed} />}
      {showCareTasks && can('read_journey') && (
        <section className="panel wide" aria-labelledby="family-journey-title">
          <SectionHeading id="family-journey-title" icon="pin">Journey</SectionHeading>
          {journey ? <div className="journey-details"><JourneyDetails journey={journey} presenter={openDemo} onMove={openDemo ? onMoveLocation : null} /></div>
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
