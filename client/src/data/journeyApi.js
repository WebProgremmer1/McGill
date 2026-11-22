import { buildCareFeed } from './careFeed.js'
import { DEMO_REMINDER_PLACE, HELP_ONLY_PLACE, reminderRequest, reminderText } from './places.js'

export const viewerUrl = '/viewer/'
export const liveMapUrl = journeyId => `/viewer/live-map.html?journey=${encodeURIComponent(journeyId)}`

let mapsConfig
export function readMapsConfig() {
  mapsConfig ??= fetch('/api/maps-config')
    .then(response => (response.ok ? response.json() : { maps_enabled: false }))
    .catch(() => ({ maps_enabled: false }))
    .then(config => {
      if (!config.maps_enabled) mapsConfig = undefined // The next map checks again after keys are added.
      return config
    })
  return mapsConfig
}

// Private calendar data comes back only for the browser with a server-side Google session.
export async function readCalendarReminder() {
  const [status, next] = await Promise.all([
    request('/google/status').catch(() => null),
    request('/google/calendar/next').catch(() => ({ state: 'unavailable' })),
  ])
  return {
    ...next,
    canConnect: Boolean(status?.configured) && !status?.connected,
    connected: Boolean(status?.connected),
    // Connections made before "Add to calendar" existed can read events but not create them.
    canWrite: (status?.scopes ?? []).includes(CALENDAR_WRITE_SCOPE),
  }
}

const CALENDAR_WRITE_SCOPE = 'https://www.googleapis.com/auth/calendar.events'

// date "2026-11-25" + time "10:00" in this browser's time zone -> "2026-11-25T10:00:00-05:00"
export function localStart(date, time) {
  const offset = -new Date(`${date}T${time}`).getTimezoneOffset()
  const sign = offset >= 0 ? '+' : '-'
  const pad = value => String(Math.floor(Math.abs(value))).padStart(2, '0')
  return `${date}T${time}:00${sign}${pad(offset / 60)}:${pad(offset % 60)}`
}

// Adds one timed event to the connected Google Calendar. Resolves to { title, start, end, link }.
export const createCalendarEvent = ({ title, start, durationMin, note }) =>
  postJson('/google/calendar/events', { title, start, duration_min: durationMin, note: note || null })

export async function readEmailSettings() {
  try {
    const status = await request('/google/status')
    return {
      connected: Boolean(status.connected),
      recipient: status.help_email_to ?? null,
      consent: Boolean(status.help_email_consent),
      ready: Boolean(status.help_email_ready),
      gmail: !(status.missing_scopes ?? []).some(scope => scope.includes('gmail.send')),
    }
  } catch {
    return { unavailable: true }
  }
}

async function request(path, options = {}) {
  const response = await fetch('/api' + path, {
    signal: AbortSignal.timeout(10000),
    ...options,
  })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    const error = new Error(body?.error?.message || `API request failed (HTTP ${response.status}).`)
    error.status = response.status
    error.code = body?.error?.code
    throw error
  }
  return response.json()
}

const postJson = (path, body) => request(path, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

// With a circle, every read and write goes through routes the server authorizes.
export function createJourneyApi(circle = null) {
  const base = circle ? `/circles/${encodeURIComponent(circle.id)}` : ''
  const can = permission => !circle || Boolean(circle.permissions?.includes(permission))
  let chatReplies = Boolean(circle)

  return {
    can,

    async readJourney(signal, forCare = false) {
      const [allJourneys, reminder, alerts, routes, messages] = await Promise.all([
        can('read_journey') ? request(`${base}/journeys`, { signal }) : [],
        circle && can('read_reminders') ? request(`${base}/reminder`, { signal }) : null,
        can('read_help') ? request(`${base}/alerts${forCare ? '' : '?acknowledged=false'}`, { signal }) : [],
        request('/routes/predefined', { signal }).catch(() => ({ routes: [] })),
        // A 404 means this server predates messages. The rest of the dashboard keeps working.
        can('read_messages')
          ? request(`${base}/messages`, { signal }).catch(error => {
            if (error.status === 404) return null
            throw error
          })
          : [],
      ])
      // An older running server stores every message as the patient's, so Care waits for this capability.
      if (!chatReplies) chatReplies = await request('/health', { signal }).then(health => Boolean(health.two_way_messages)).catch(() => false)
      const journeys = allJourneys.filter(item => ![HELP_ONLY_PLACE, DEMO_REMINDER_PLACE].includes(item.destination.name))
      const reminderRecord = circle ? null : allJourneys.filter(item => item.destination.name === DEMO_REMINDER_PLACE).at(-1)
      // The newest active journey is what both windows show, including a backend replay.
      const journey = journeys.filter(item => item.status === 'active').at(-1) ?? null
      const helpRequests = alerts.filter(item => item.type === 'help_request' && !item.acknowledged)
      const help = helpRequests.find(item => item.journey_id === journey?.id) ?? helpRequests[0] ?? null
      // The API returns alerts newest first. Each request keeps its own journey.
      const openHelp = helpRequests.map(alert => ({ alert, journey: allJourneys.find(item => item.id === alert.journey_id) ?? null }))
      // Care reads the selected walk directly, so its feed does not depend on the live-map tab.
      const feedJourney = forCare ? journey ?? journeys.at(-1) ?? null : null
      const walksToRead = [...new Set([journey, feedJourney].filter(Boolean))]
      const recentCheckIns = (await Promise.all(walksToRead.map(item => request(`${base}/journeys/${encodeURIComponent(item.id)}/checkins`, { signal })
        .catch(error => {
          if (error.status === 404) return []
          throw error
        })))).flat()
      const checkIns = recentCheckIns.filter(item => item.journey_id === journey?.id)
      return {
        journeys,
        journey,
        checkIn: checkIns.filter(item => item.status === 'open').at(-1) ?? null,
        help,
        openHelp,
        feedJourney,
        activity: buildCareFeed(feedJourney, alerts, recentCheckIns, allJourneys),
        routes: routes.routes ?? [],
        reminder: reminderRecord ? reminderText(reminderRecord) : reminder?.message ?? null,
        reminderId: reminderRecord?.id ?? reminder?.message ?? null,
        reminderSender: reminder?.sender ?? null,
        messages,
        chatReplies,
      }
    },

    createJourney: body => postJson(`${base}/journeys`, body),

    googleRoutesEnabled: () => request('/health').then(health => Boolean(health.google_routes_configured)).catch(() => false),

    closeJourney: (journeyId, action) =>
      request(`${base}/journeys/${encodeURIComponent(journeyId)}/${action}`, { method: 'POST' }),

    requestHelp: (journeyId, checkInId) => postJson(
      `${base}/journeys/${encodeURIComponent(journeyId)}/checkin`,
      { help_requested: true, ...(checkInId ? { checkin_id: checkInId } : {}) },
    ),

    answerCheckIn: (journeyId, checkInId) => postJson(
      `${base}/journeys/${encodeURIComponent(journeyId)}/checkin`,
      { response: "I'm okay", checkin_id: checkInId },
    ),

    // Circles have no authorized acknowledge route, so they never fall back to the open route.
    acknowledgeAlert: circle ? null : alertId => request(`/alerts/${encodeURIComponent(alertId)}/acknowledge`, { method: 'POST' }),

    sendMessage: (body, senderRole) => postJson(`${base}/messages`, circle || !chatReplies ? { body } : { body, sender_role: senderRole }),

    // Demo only. Circle conversations have no clear route.
    clearChat: circle ? null : () => request('/demo/messages/clear', { method: 'POST' }),

    // Demo only: moves the walker by posting one GPS point. Circles have no location route.
    moveLocation: circle ? null : (journeyId, latitude, longitude, timestamp) => postJson(
      `/journeys/${encodeURIComponent(journeyId)}/location`, { latitude, longitude, timestamp },
    ),

    async sendReminder(message) {
      if (circle) {
        return request(`${base}/reminder`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message }),
        })
      }
      const record = await postJson('/journeys', reminderRequest(message))
      await request(`/journeys/${encodeURIComponent(record.id)}/cancel`, { method: 'POST' }).catch(() => {})
      return record
    },
  }
}
