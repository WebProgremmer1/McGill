import { DEMO_REMINDER_PLACE, HELP_ONLY_PLACE, reminderRequest, reminderText } from './places.js'

export const viewerUrl = '/viewer/'

async function request(path, options = {}) {
  const response = await fetch('/api' + path, {
    signal: AbortSignal.timeout(10000),
    ...options,
  })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    const error = new Error(body?.error?.message || `API request failed (HTTP ${response.status}).`)
    error.status = response.status
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

  return {
    can,

    async readJourney(signal) {
      const [allJourneys, reminder, alerts, routes] = await Promise.all([
        can('read_journey') ? request(`${base}/journeys`, { signal }) : [],
        circle && can('read_reminders') ? request(`${base}/reminder`, { signal }) : null,
        can('read_help') ? request(`${base}/alerts?acknowledged=false`, { signal }) : [],
        request('/routes/predefined', { signal }).catch(() => ({ routes: [] })),
      ])
      const journeys = allJourneys.filter(item => ![HELP_ONLY_PLACE, DEMO_REMINDER_PLACE].includes(item.destination.name))
      const reminderRecord = circle ? null : allJourneys.filter(item => item.destination.name === DEMO_REMINDER_PLACE).at(-1)
      // The newest active journey is what both windows show, including a backend replay.
      const journey = journeys.filter(item => item.status === 'active').at(-1) ?? null
      const help = alerts.find(item => item.type === 'help_request') ?? null
      const helpJourney = help ? allJourneys.find(item => item.id === help.journey_id) ?? null : null
      const checkIns = journey ? await request(`${base}/journeys/${encodeURIComponent(journey.id)}/checkins`, { signal }) : []
      return {
        journeys,
        journey,
        checkIn: checkIns.filter(item => item.status === 'open').at(-1) ?? null,
        help,
        helpJourney,
        routes: routes.routes ?? [],
        reminder: reminderRecord ? reminderText(reminderRecord) : reminder?.message ?? null,
        reminderId: reminderRecord?.id ?? reminder?.message ?? null,
        reminderSender: reminder?.sender ?? null,
      }
    },

    createJourney: body => postJson(`${base}/journeys`, body),

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
