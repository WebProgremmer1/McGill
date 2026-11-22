import { useEffect, useMemo, useRef, useState } from 'react'
import { CaregiverDashboard, TodayScreen } from './CareScreens.jsx'
import { firstName } from './data/contacts.js'
import { createJourneyApi, readCalendarReminder, readEmailSettings } from './data/journeyApi.js'
import { destinationOptions, helpOnlyRequest } from './data/places.js'
import Shell from './Shell.jsx'

export default function BackendDemo({ family, circle = null, account = null, onAccessLost, shell }) {
  const api = useMemo(() => createJourneyApi(circle), [circle])
  const [data, setData] = useState(null)
  const [readError, setReadError] = useState('')
  const [actionError, setActionError] = useState('')
  const [busy, setBusy] = useState(false)
  const [revision, setRevision] = useState(0)
  const [continuedJourney, setContinuedJourney] = useState(null)
  const [calendar, setCalendar] = useState({ state: 'loading' })
  const [emailSettings, setEmailSettings] = useState(null)
  const remindersHeading = useRef(null)
  const journeyHeading = useRef(null)
  const journeyDetails = useRef(null)
  const focusAfterUpdate = useRef(null)
  const reminderRegion = useRef(null)
  const lastReminder = useRef(undefined)
  const eventRegion = useRef(null)
  const lastEvent = useRef(undefined)
  const messageRegion = useRef(null)
  const seenMessages = useRef(null)
  // Holds Get help from the first press until a snapshot read after the save has rendered.
  const helpLock = useRef(null)
  const helpSnapshot = useRef(null)

  useEffect(() => {
    const controller = new AbortController()
    let timer
    async function poll() {
      const confirmsHelp = helpLock.current === 'confirming'
      try {
        const snapshot = await api.readJourney(AbortSignal.any([controller.signal, AbortSignal.timeout(10000)]), family)
        if (!controller.signal.aborted) {
          if (confirmsHelp) helpSnapshot.current = snapshot
          setData(snapshot)
          setReadError('')
        }
      } catch (error) {
        if (!controller.signal.aborted) {
          if (circle && [401, 403].includes(error.status)) {
            setData(null)
            onAccessLost?.(error.status)
            return
          }
          setReadError(`Could not refresh the journey. ${error.message}`)
        }
      } finally {
        if (!controller.signal.aborted) timer = setTimeout(poll, 2000)
      }
    }
    poll()
    return () => {
      controller.abort()
      clearTimeout(timer)
    }
  }, [api, circle, family, onAccessLost, revision])

  useEffect(() => {
    if (circle) return undefined
    let active = true
    let timer
    let latest = 0
    async function load() {
      const request = ++latest
      clearTimeout(timer)
      const [next, email] = await Promise.all([readCalendarReminder(), family ? readEmailSettings() : null])
      if (!active || request !== latest) return
      setCalendar(next)
      setEmailSettings(email)
      timer = setTimeout(load, 60000)
    }
    load()
    // Returning to a window picks up a Google connection made in the other one.
    window.addEventListener('focus', load)
    return () => {
      active = false
      clearTimeout(timer)
      window.removeEventListener('focus', load)
    }
  }, [circle, family])

  useEffect(() => {
    if (!data || data !== helpSnapshot.current) return
    helpSnapshot.current = null
    helpLock.current = null
  }, [data])

  const { journey = null, checkIn = null, help = null, openHelp = [] } = data ?? {}
  const canReadReminders = api.can('read_reminders')
  const reminder = canReadReminders ? data?.reminder ?? null : null
  const reminderKey = canReadReminders ? data?.reminderId ?? null : null
  const sender = canReadReminders && circle ? data?.reminderSender ?? null : null
  const senderName = firstName(sender)
  const linkedPerson = circle?.care_recipient ?? null
  const viewerIsRecipient = Boolean(account && linkedPerson?.id === account.id)
  const recipient = viewerIsRecipient ? null : linkedPerson
  const caregiver = circle?.caregivers?.find(person => person.id !== account?.id) ?? null
  const caregiverName = firstName(caregiver)
  const viewerName = firstName(account)

  // An action can remove the control that had focus, so keyboard users continue nearby.
  useEffect(() => {
    const target = focusAfterUpdate.current
    if (!target || !data) return
    const ready = (target === 'details' && journey) || (target === 'journey' && !journey) || (target === 'reminders' && !checkIn)
    if (!ready) return
    focusAfterUpdate.current = null
    if (document.activeElement !== document.body) return
    const element = { details: journeyDetails, journey: journeyHeading, reminders: remindersHeading }[target].current
    element?.focus()
  }, [checkIn, data, journey])

  // Announce changed reminders once. Whatever is loaded with the page is not new.
  const remindersLoaded = canReadReminders && Boolean(data)
  useEffect(() => {
    if (family || !remindersLoaded) return
    if (lastReminder.current !== undefined && reminderKey && lastReminder.current !== reminderKey && reminderRegion.current) {
      reminderRegion.current.textContent = senderName ? `New reminder from ${senderName}: ${reminder}` : `New reminder: ${reminder}`
    }
    lastReminder.current = reminderKey
  }, [family, reminder, reminderKey, remindersLoaded, senderName])

  // Announce new caregiver messages once without moving focus.
  useEffect(() => {
    if (!family || !data) return
    const messages = data.messages ?? []
    if (seenMessages.current && messageRegion.current) {
      const fresh = messages.filter(item => !seenMessages.current.has(item.id))
      if (fresh.length === 1) {
        const from = firstName(fresh[0].sender)
        messageRegion.current.textContent = from ? `New message from ${from}: ${fresh[0].body}` : `New message: ${fresh[0].body}`
      } else if (fresh.length > 1) {
        messageRegion.current.textContent = `${fresh.length} new messages.`
      }
    }
    seenMessages.current = new Set(messages.map(item => item.id))
  }, [data, family])

  function handleAccessError(error) {
    if (!circle || ![401, 403].includes(error.status)) return false
    setData(null)
    onAccessLost?.(error.status)
    return true
  }

  async function perform(action, failureMessage) {
    if (busy) return
    setBusy(true)
    setActionError('')
    try {
      await action()
    } catch (error) {
      focusAfterUpdate.current = null
      if (!handleAccessError(error)) setActionError(failureMessage ?? error.message)
    } finally {
      setBusy(false)
      setRevision(value => value + 1)
    }
  }

  const destination = journey?.destination.name
  const event = family ? openHelp[0]?.alert ?? null : checkIn
  const helpTitle = openHelp.length > 1
    ? `${openHelp.length} help requests are waiting.`
    : recipient ? `${firstName(recipient)} asked for help.` : 'A help request is waiting.'
  const announcement = family ? helpTitle : `Still heading to ${destination}?`
  const controlsUnavailable = busy || Boolean(readError)
  const options = data ? destinationOptions(data.journeys, data.routes, account?.name) : []
  const helpLabel = caregiverName ? `Ask ${caregiverName} for help` : 'Get help'
  const eventId = event?.id ?? null
  const helpSent = Boolean(help && (!journey || help.journey_id === journey.id))

  // Announce each new check-in or help request once. Items already there on load are not new.
  useEffect(() => {
    if (!data || !eventRegion.current) return
    if (!eventId) eventRegion.current.textContent = ''
    else if (lastEvent.current !== undefined && lastEvent.current !== eventId) eventRegion.current.textContent = announcement
    lastEvent.current = eventId
  }, [announcement, data, eventId])

  const requestHelp = () => {
    if (helpSent || busy || helpLock.current) return
    helpLock.current = 'sending'
    perform(async () => {
      try {
        if (journey) {
          await api.requestHelp(journey.id, checkIn?.id)
        } else {
          const record = await api.createJourney(helpOnlyRequest(account?.name))
          try {
            await api.requestHelp(record.id)
          } finally {
            await api.closeJourney(record.id, 'cancel').catch(() => {})
          }
        }
        helpLock.current = 'confirming'
      } catch (error) {
        helpLock.current = null
        throw error
      }
    }, 'Your help request didn’t send. Try again.')
  }

  const keepGoing = () => perform(async () => {
    await api.answerCheckIn(journey.id, checkIn.id)
    focusAfterUpdate.current = 'reminders'
    setContinuedJourney(journey.id)
  })

  const startJourney = option => perform(async () => {
    const created = await api.createJourney(option.build(await api.googleRoutesEnabled()))
    const others = data.journeys.filter(item => item.status === 'active' && item.id !== created.id)
    await Promise.all(others.map(item => api.closeJourney(item.id, 'cancel').catch(() => {})))
    focusAfterUpdate.current = 'details'
  }, 'That journey didn’t start. Try again.')

  const endJourney = action => perform(async () => {
    const active = data.journeys.filter(item => item.status === 'active')
    await api.closeJourney(journey.id, action)
    await Promise.all(active.filter(item => item.id !== journey.id).map(item => api.closeJourney(item.id, 'cancel').catch(() => {})))
    focusAfterUpdate.current = 'journey'
  }, 'That didn’t work. Try again.')

  async function sendReminder(text) {
    try {
      await api.sendReminder(text)
    } catch (error) {
      handleAccessError(error)
      throw error
    }
    setRevision(value => value + 1)
  }

  async function sendMessage(text) {
    try {
      await api.sendMessage(text)
    } catch (error) {
      handleAccessError(error)
      throw error
    }
  }

  const helpConfirmation = caregiverName
    ? `Your help request is on ${caregiverName}’s dashboard.`
    : circle ? 'No caregiver is linked yet, so no one can see this request.' : 'Your help request is on the care dashboard.'
  const confirmation = helpSent
    ? helpConfirmation
    : journey && continuedJourney === journey.id && !checkIn ? `Okay. Enjoy your walk to ${destination}.` : ''
  const canHelp = api.can('request_help')
  const heading = family ? 'Care dashboard' : viewerName ? `Hi, ${viewerName}` : 'Patient dashboard'

  return (
    <Shell {...shell} family={family} heading={heading}>
      <div ref={eventRegion} className="sr-only" role="status" aria-live="polite" aria-atomic="true" />
      <div ref={reminderRegion} className="sr-only" role="status" aria-live="polite" aria-atomic="true" />
      <div ref={messageRegion} className="sr-only" role="status" aria-live="polite" aria-atomic="true" />
      {(readError || actionError) && <p className="error-banner" role="alert">{actionError || readError}</p>}
      {family ? (
        <CaregiverDashboard calendar={circle ? null : calendar} emailSettings={emailSettings} loaded={Boolean(data)} helpRequests={openHelp} helpTitle={helpTitle} journey={journey}
          reminder={reminder} sender={sender} recipient={recipient} openDemo={!circle} showCareTasks={!circle || Boolean(recipient)}
          messages={data?.messages} can={api.can} onSendReminder={sendReminder} />
      ) : (
        <TodayScreen openDemo={!circle} checkIn={checkIn} journey={journey} help={helpSent ? help : null} reminder={reminder} sender={sender}
          calendar={circle ? null : calendar}
          viewerIsRecipient={viewerIsRecipient} caregiver={caregiver} helpLabel={helpLabel} confirmation={confirmation}
          options={options} busy={busy} controlsUnavailable={controlsUnavailable}
          canTravel={api.can('start_journey')} canHelp={canHelp} canMessage={api.can('send_messages')}
          caregiverName={caregiverName} onSendMessage={sendMessage}
          onKeepGoing={keepGoing} onAskForHelp={requestHelp} onStart={startJourney} onEnd={endJourney}
          remindersRef={remindersHeading} journeyRef={journeyHeading} detailsRef={journeyDetails} />
      )}
    </Shell>
  )
}
