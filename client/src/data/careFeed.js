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

// One row per backend event, using only that record's own values.
export function buildCareFeed(journey, alerts, checkIns) {
  if (!journey) return []
  const walkAlerts = alerts.filter(alert => alert.journey_id === journey.id)
  // The API lists alerts newest first, which breaks ties when records share a GPS time.
  const alertOrder = new Map(walkAlerts.map((alert, index) => [alert.id, walkAlerts.length - index]))
  const place = `Walk to ${journey.destination.name}`
  const entries = new Map()
  const add = entry => entries.set(entry.id, { place, sequence: 0, message: '', details: [], alertId: null, acknowledged: false, ...entry })
  const usedOkay = new Set()
  for (const item of checkIns.filter(checkIn => checkIn.journey_id === journey.id)) {
    add({ id: `checkin:${item.id}:sent`, kind: 'checkin', time: item.created_at, title: 'Check-in sent', message: item.message })
    if (item.status !== 'answered' || !item.answered_at) continue
    const okay = walkAlerts.find(alert => alert.type === 'said_okay' && alert.created_at === item.answered_at && !usedOkay.has(alert.id))
    if (okay) usedOkay.add(okay.id)
    add({ id: `checkin:${item.id}:answered`, kind: 'answered', time: item.answered_at, sequence: okay ? alertOrder.get(okay.id) - 0.5 : 0.5,
      title: 'Check-in answered', message: item.response ?? '' })
  }
  for (const alert of walkAlerts) {
    if (!stepOrder[alert.type]) continue
    const canAcknowledge = alert.type === 'risk' || alert.type === 'help_request'
    add({ id: `alert:${alert.id}`, kind: alert.type, time: alert.created_at, sequence: alertOrder.get(alert.id),
      title: alert.type === 'risk' ? `Risk alert · ${alert.risk_score}/100` : alertTitles[alert.type],
      message: alert.message, details: missingReasons(alert), alertId: canAcknowledge ? alert.id : null, acknowledged: Boolean(alert.acknowledged) })
  }
  return [...entries.values()].sort((a, b) => Date.parse(b.time) - Date.parse(a.time)
    || b.sequence - a.sequence
    || stepOrder[b.kind] - stepOrder[a.kind]
    || a.id.localeCompare(b.id))
}
