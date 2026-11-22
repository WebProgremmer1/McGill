import { ARRIVAL_ORDER_MS, ARRIVAL_PLACE, HELP_ONLY_PLACE } from './places.js'

const stepOrder = { checkin: 1, answered: 2, said_okay: 3, risk: 4, help_request: 5, arrived: 6 }
const riskLabels = { low: 'Low risk', medium: 'Medium risk', high: 'High risk' }
const alertTitles = { help_request: 'Help button pressed' }

export const riskLabel = level => riskLabels[level] ?? 'Risk not available'

// Risk messages normally include their reasons. Only reasons missing from the message are listed.
function missingReasons(alert) {
  if (alert.type !== 'risk') return []
  const message = alert.message ?? ''
  return (alert.reasons ?? []).map(reason => reason.description).filter(text => text && !message.includes(text.replace(/\.$/, '')))
}

// Saved records can still hold the old "App user" placeholder.
export function withoutPlaceholderName(text, defaultName = null) {
  return (text ?? '')
    .replace(/^Hi(?: App(?: user)?)?,\s*/i, () => (defaultName ? `Hi ${defaultName}, ` : 'Hi, '))
    .replace(/^(URGENT: )?App user\b/i, (_, urgent = '') => `${urgent}${defaultName ?? 'The patient'}`)
}

// The app has no pronoun field, so only the demo patient's stated pronoun is used.
const statedPossessive = { Margaret: 'her' }

// The name comes only from this event's own record or walk, never from another walk.
function patientFrom(recordedName, caregiverNames, defaultName) {
  const recorded = (recordedName ?? '').trim().replace(/\s+/g, ' ')
  const full = !recorded || /^app( user)?$/i.test(recorded) ? defaultName : recorded
  if (!full || caregiverNames.has(full.toLowerCase())) {
    return { name: 'the patient', subject: 'The patient', possessive: 'their' }
  }
  const first = full.split(' ')[0]
  return { name: first, subject: first, possessive: statedPossessive[full] ?? 'their' }
}

const walkDestination = walk => {
  const name = walk?.destination?.name
  return name && name !== HELP_ONLY_PLACE ? name : null
}

// Stored check-ins greet the patient. Care keeps only the question that was asked.
function checkInQuestion(message, destination) {
  const text = (message ?? '').trim()
  const lead = destination ? `on your way to ${destination}. ` : null
  const at = lead ? text.indexOf(lead) : -1
  return at >= 0 ? text.slice(at + lead.length) : text.replace(/^Hi\b[^.]*\.\s*/, '')
}

// Stored alerts start with the recorded name, so old entries are reworded here.
function alertText(alert, person) {
  const text = alert.message ?? ''
  const prefix = text.startsWith('URGENT: ') ? 'URGENT: ' : ''
  const body = text.slice(prefix.length)
  const recorded = [alert.user_name, 'App user', 'The patient'].find(value => value && body.startsWith(`${value} `))
  const named = recorded ? `${person.subject}${body.slice(recorded.length)}` : body
  return prefix + named.replace(` on the way to ${HELP_ONLY_PLACE}`, '')
}

// One row per backend event, using only that record's own values.
export function buildCareFeed(journey, alerts, checkIns, journeys = [], { caregivers = [], recipient = null, defaultName = null } = {}) {
  const recipientName = recipient?.name?.trim().toLowerCase()
  const caregiverNames = new Set(caregivers.map(person => person.name?.trim().toLowerCase()).filter(name => name && name !== recipientName))
  const patient = name => patientFrom(name, caregiverNames, defaultName)
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
    const walk = byId.get(item.journey_id) ?? journey
    const person = patient(walk?.user_name)
    const destination = walkDestination(walk)
    const question = checkInQuestion(item.message, destination)
    add({ id: `checkin:${item.id}:sent`, kind: 'checkin', time: item.created_at,
      title: destination ? `Check-in sent to ${person.name} on ${person.possessive} way to ${destination}.` : `Check-in sent to ${person.name}.`,
      message: question ? `Asked: “${question}”` : '' })
    if (item.status !== 'answered' || !item.answered_at) continue
    const okay = walkAlerts.find(alert => alert.type === 'said_okay' && alert.created_at === item.answered_at && !usedOkay.has(alert.id))
    if (okay) usedOkay.add(okay.id)
    add({ id: `checkin:${item.id}:answered`, kind: 'answered', time: item.answered_at, sequence: okay ? alertOrder.get(okay.id) - 0.5 : 0.5,
      title: item.response?.trim() ? `${person.subject} answered ‘${item.response.trim().replaceAll("'", '’')}’` : `${person.subject} answered the check-in` })
  }
  for (const alert of walkAlerts) {
    if (!stepOrder[alert.type]) continue
    const canAcknowledge = alert.type === 'risk' || alert.type === 'help_request'
    const person = patient(alert.user_name || byId.get(alert.journey_id)?.user_name)
    add({ id: `alert:${alert.id}`, kind: alert.type, place: placeFor(byId.get(alert.journey_id)), emailStatus: alert.type === 'help_request' ? alert.email_status : null, time: alert.created_at, sequence: alertOrder.get(alert.id),
      title: alert.type === 'risk' ? `Risk alert · ${alert.risk_score}/100` : alert.type === 'said_okay' ? `${person.subject} said okay` : alertTitles[alert.type],
      message: alertText(alert, person), details: missingReasons(alert), alertId: canAcknowledge ? alert.id : null, acknowledged: Boolean(alert.acknowledged) })
  }
  // Arrivals stay in the feed after the next walk starts, like handled help requests.
  for (const item of journeys.filter(record => record.destination.name === ARRIVAL_PLACE)) {
    const destination = item.safe_zones?.[0]?.name ?? 'the destination'
    add({ id: `arrival:${item.id}`, kind: 'arrived', time: item.started_at, sequence: Number.MAX_SAFE_INTEGER, sortTime: Math.max(Date.parse(item.started_at), (Date.parse(item.expected_arrival) - ARRIVAL_ORDER_MS) || 0), place: `Walk to ${destination}`,
      title: `Arrived at ${destination}`, message: `${patient(item.user_name).subject} pressed “I’ve arrived.”` })
  }
  const orderTime = entry => entry.sortTime ?? Date.parse(entry.time)
  return [...entries.values()].sort((a, b) => orderTime(b) - orderTime(a)
    || b.sequence - a.sequence
    || stepOrder[b.kind] - stepOrder[a.kind]
    || a.id.localeCompare(b.id))
}
