import { HELP_ONLY_PLACE } from './places.js'

const stepOrder = { checkin: 1, answered: 2, said_okay: 3, risk: 4, help_request: 5 }
const riskLabels = { low: 'Low risk', medium: 'Medium risk', high: 'High risk' }
const alertTitles = { help_request: 'Help button pressed', said_okay: 'Said okay' }

export const riskLabel = level => riskLabels[level] ?? 'Risk not available'

// Risk messages normally include their reasons. Only reasons missing from the message are listed.
function missingReasons(alert) {
  if (alert.type !== 'risk') return []
  const message = alert.message ?? ''
  return (alert.reasons ?? []).map(reason => reason.description).filter(text => text && !message.includes(text.replace(/\.$/, '')))
}

// Saved records can still hold the app's "App user" placeholder.
export function withoutPlaceholderName(text) {
  return (text ?? '')
    .replace(/^Hi App(?: user)?,\s*/i, 'Hi, ')
    .replace(/^(URGENT: )?App user\b/i, '$1The patient')
}

// A check-in is written to the patient ("Hi Margaret, … Are you okay?"). The caregiver feed
// reports it instead: who was asked, then the question without the greeting.
export function checkInForCaregiver(message, userName) {
  const name = userName && !/^app(?: user)?$/i.test(userName.trim()) ? userName.trim() : 'the patient'
  const question = (message ?? '').replace(/^Hi\b[^,]*,\s*/i, '').trim()
  if (!question) return `The app checked in with ${name}.`
  return `The app asked ${name}: “${question.charAt(0).toUpperCase()}${question.slice(1)}”`
}

// One row per backend event, using only that record's own values.
export function buildCareFeed(journey, alerts, checkIns, journeys = []) {
  const byId = new Map(journeys.map(item => [item.id, item]))
  const placeFor = item => {
    if (!item) return null
    return item.destination.name === HELP_ONLY_PLACE ? 'Outside a journey' : `Walk to ${item.destination.name}`
  }
  // Handled help requests stay visible even when they belong to another walk or no walk.
  const walkAlerts = alerts.filter(alert => alert.journey_id === journey?.id || (alert.type === 'help_request' && alert.acknowledged))
  // The API lists alerts newest first, which breaks ties when records share a GPS time.
  const alertOrder = new Map(walkAlerts.map((alert, index) => [alert.id, walkAlerts.length - index]))
  const place = placeFor(journey)
  const entries = new Map()
  const add = entry => entries.set(entry.id, { place, sequence: 0, message: '', details: [], alertId: null, acknowledged: false, emailStatus: null, ...entry })
  const usedOkay = new Set()
  for (const item of checkIns.filter(checkIn => checkIn.journey_id === journey?.id)) {
    add({ id: `checkin:${item.id}:sent`, kind: 'checkin', time: item.created_at, title: 'Check-in sent', message: checkInForCaregiver(item.message, journey?.user_name) })
    if (item.status !== 'answered' || !item.answered_at) continue
    const okay = walkAlerts.find(alert => alert.type === 'said_okay' && alert.created_at === item.answered_at && !usedOkay.has(alert.id))
    if (okay) usedOkay.add(okay.id)
    add({ id: `checkin:${item.id}:answered`, kind: 'answered', time: item.answered_at, sequence: okay ? alertOrder.get(okay.id) - 0.5 : 0.5,
      title: 'Check-in answered', message: item.response ?? '' })
  }
  for (const alert of walkAlerts) {
    if (!stepOrder[alert.type]) continue
    const canAcknowledge = alert.type === 'risk' || alert.type === 'help_request'
    add({ id: `alert:${alert.id}`, kind: alert.type, place: placeFor(byId.get(alert.journey_id)), emailStatus: alert.type === 'help_request' ? alert.email_status : null, time: alert.created_at, sequence: alertOrder.get(alert.id),
      title: alert.type === 'risk' ? `Risk alert · ${alert.risk_score}/100` : alertTitles[alert.type],
      message: withoutPlaceholderName(alert.message), details: missingReasons(alert), alertId: canAcknowledge ? alert.id : null, acknowledged: Boolean(alert.acknowledged) })
  }
  return [...entries.values()].sort((a, b) => Date.parse(b.time) - Date.parse(a.time)
    || b.sequence - a.sequence
    || stepOrder[b.kind] - stepOrder[a.kind]
    || a.id.localeCompare(b.id))
}
