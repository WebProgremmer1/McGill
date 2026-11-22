// Places the app can open. Each one depends on a route the backend actually has.
const routeName = 'tim_hortons_demo'
const nearbyMeters = 75

export const HELP_ONLY_PLACE = 'No active journey'
// The open demo has no account, so its patient is Margaret. Signed-in accounts use their own names.
export const DEFAULT_PATIENT_NAME = 'Margaret'
export const home = { name: 'Home', latitude: 45.5048, longitude: -73.5772 }
export const timHortons = { name: 'Tim Hortons', latitude: 45.5088, longitude: -73.5697 }
export const savedPlaces = [{ ...home, icon: 'home' }, { ...timHortons, icon: 'cup' }]

const zones = [home, timHortons].map(place => ({ ...place, radius_m: nearbyMeters }))
const coordinates = ({ latitude, longitude }) => ({ latitude, longitude })
const radians = value => value * Math.PI / 180

export function metersBetween(a, b) {
  const latitude = radians(b.latitude - a.latitude)
  const longitude = radians(b.longitude - a.longitude)
  const h = Math.sin(latitude / 2) ** 2
    + Math.cos(radians(a.latitude)) * Math.cos(radians(b.latitude)) * Math.sin(longitude / 2) ** 2
  return 2 * 6371000 * Math.asin(Math.sqrt(h))
}

function journeyRequest(start, destination, route, userName) {
  return {
    user_name: userName || DEFAULT_PATIENT_NAME,
    start,
    destination,
    expected_arrival: new Date(Date.now() + 15 * 60000).toISOString(),
    safe_zones: zones,
    ...route,
  }
}

// The API ties help to a journey, so help before a walk uses a closed placeholder record.
export const helpOnlyRequest = userName => ({
  ...journeyRequest(home, { ...home, name: HELP_ONLY_PLACE }, { route: [coordinates(home), coordinates(home)] }, userName),
  safe_zones: [],
})

// FastAPI has no reminders route yet. A closed demo record keeps reminders in shared server
// state, and the existing demo reset clears them. Safe-zone names hold up to 120 characters each.
export const DEMO_REMINDER_PLACE = 'Demo reminder'

export function reminderRequest(message) {
  const characters = Array.from(message)
  const parts = []
  for (let index = 0; index < characters.length; index += 120) parts.push(characters.slice(index, index + 120).join(''))
  return {
    ...journeyRequest(home, { ...home, name: DEMO_REMINDER_PLACE }, { route: [coordinates(home), coordinates(home)] }),
    safe_zones: parts.map(name => ({ ...coordinates(home), name, radius_m: 1 })),
  }
}

export const reminderText = record => record.safe_zones.map(part => part.name).join('')

// A finished walk can also come from the map's simulations, so "I've arrived" keeps its own closed record.
export const ARRIVAL_PLACE = 'Patient arrival'
export const ARRIVAL_ORDER_MS = 15 * 60000

export function arrivalRequest(walk) {
  const pressed = Date.now()
  // Map taps can run a walk's clock ahead. The real time is shown, and the walk's clock only orders the feed.
  const walkClock = Math.max(pressed, Date.parse(walk.ended_at) || 0)
  return {
    ...journeyRequest(home, { ...home, name: ARRIVAL_PLACE }, { route: [coordinates(home), coordinates(home)] }, walk.user_name),
    safe_zones: [{ ...coordinates(home), name: walk.destination.name, radius_m: 1 }],
    started_at: new Date(pressed).toISOString(),
    expected_arrival: new Date(walkClock + ARRIVAL_ORDER_MS).toISOString(),
  }
}

function positionOf(journey) {
  if (journey.status === 'completed') return journey.destination
  return journey.latest_location ?? journey.start
}

function nearestIndex(points, position) {
  let nearest = 0
  points.forEach((point, index) => {
    if (metersBetween(point, position) < metersBetween(points[nearest], position)) nearest = index
  })
  return nearest
}

function routeHome(journey, position) {
  const points = journey.route
  const endsAtHome = metersBetween(points.at(-1), home) <= metersBetween(points[0], home)
  const ordered = endsAtHome ? points : [...points].reverse()
  return [position, ...ordered.slice(nearestIndex(ordered, position)), home].map(coordinates)
}

export function destinationOptions(journeys, availableRoutes, userName) {
  const last = journeys.at(-1)
  const position = last ? positionOf(last) : home
  const headingTo = last?.status === 'active' ? last.destination.name : null

  if (metersBetween(position, home) <= nearbyMeters) {
    if (headingTo || !availableRoutes.includes(routeName)) return []
    return [{
      id: 'tim-hortons',
      label: 'Go to Tim Hortons',
      icon: 'cup',
      // Google is tried first when configured. The demo route remains the backend's fallback.
      build: useGoogle => journeyRequest(home, timHortons, useGoogle ? { fallback_route: routeName } : { predefined_route: routeName }, userName),
    }]
  }
  if (headingTo === home.name) return []
  return [{
    id: 'home',
    label: 'Go home',
    icon: 'home',
    build: () => journeyRequest(
      { name: 'Current location', ...coordinates(position) },
      home,
      { route: routeHome(last, position) },
      userName,
    ),
  }]
}

export function locationText(journey) {
  const latest = journey.latest_location
  if (!latest) return `Starting at ${journey.start.name}.`
  const zone = journey.safe_zones?.find(item => metersBetween(latest, item) <= item.radius_m)
  if (zone) return `Near ${zone.name}.`
  const meters = Math.round(metersBetween(latest, journey.destination) / 10) * 10
  return `About ${meters} meters from ${journey.destination.name}.`
}

const compass = ['north', 'northeast', 'east', 'southeast', 'south', 'southwest', 'west', 'northwest']

function bearing(a, b) {
  const y = Math.sin(radians(b.longitude - a.longitude)) * Math.cos(radians(b.latitude))
  const x = Math.cos(radians(a.latitude)) * Math.sin(radians(b.latitude))
    - Math.sin(radians(a.latitude)) * Math.cos(radians(b.latitude)) * Math.cos(radians(b.longitude - a.longitude))
  return (Math.atan2(y, x) * 180 / Math.PI + 360) % 360
}

const signedTurn = (from, to) => ((to - from + 540) % 360) - 180
const roundedMeters = meters => Math.max(10, Math.round(meters / 10) * 10)

// The backend has route points but no street names, so steps come from the route's shape.
// They start at the last known location so they stay useful after someone leaves the route.
export function directionSteps(journey) {
  const latest = journey.latest_location
  const route = latest ? [latest, ...journey.route.slice(nearestIndex(journey.route, latest))] : journey.route
  const legs = []
  route.slice(1).forEach((point, index) => {
    const previous = route[index]
    const meters = metersBetween(previous, point)
    if (meters < 5) return
    const heading = bearing(previous, point)
    const leg = legs.at(-1)
    // Detailed walking routes have tiny bends, so very short legs join the current step.
    if (leg && (meters < 25 || Math.abs(signedTurn(leg.heading, heading)) < 30)) leg.meters += meters
    else legs.push({ heading, meters })
  })
  const steps = legs.map((leg, index) => {
    const distance = roundedMeters(leg.meters)
    if (index === 0) return `Walk ${compass[Math.round(leg.heading / 45) % 8]} for about ${distance} meters.`
    const turn = signedTurn(legs[index - 1].heading, leg.heading)
    return `${Math.abs(turn) < 60 ? 'Bear' : 'Turn'} ${turn > 0 ? 'right' : 'left'} and walk about ${distance} meters.`
  })
  return [...steps, `Arrive at ${journey.destination.name}.`]
}
