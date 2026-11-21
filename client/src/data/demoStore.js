// The only data boundary: replace this adapter with FastAPI reads, writes,
// and a subscription/polling transport when the backend is available.
export const demoData = {
  day: 'Friday',
  date: 'November 20',
  activities: [
    { time: '9:00 AM', title: 'Breakfast & a cup of tea', detail: 'A slow start at home', icon: 'cup', done: true },
    { time: '10:30 AM', title: 'Walk to the grocery store', detail: 'Bread, apples, and milk', icon: 'walk' },
    { time: '12:30 PM', title: 'Lunch at home', detail: 'Your favourite soup is in the fridge', icon: 'sun' },
    { time: '3:00 PM', title: 'Catch up with family', detail: 'A little time together', icon: 'phone' },
  ],
  directions: ['Continue along Maple Street toward Oak Avenue.', 'At Oak Avenue, turn right at the flower shop.', 'Maple Market is the next shop on your left, at 120 Maple Street.'],
  responses: { continue: 'They chose to keep going.', directions: 'They viewed directions.', contact: 'They asked for help.' },
}

const STORAGE_KEY = 'whats-next-demo-v1'
const listeners = new Set()
const emptyState = () => ({ version: 1, checkIn: null, contactRequest: null, storageError: false })

function readState() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return emptyState()
    const value = JSON.parse(raw)
    if (value.version !== 1 || !(value.checkIn === null || (typeof value.checkIn?.id === 'string' && [null, 'continue', 'directions', 'contact'].includes(value.checkIn.response))) || !(value.contactRequest === null || typeof value.contactRequest?.createdAt === 'string')) return emptyState()
    return { ...value, storageError: false }
  } catch {
    return { ...emptyState(), storageError: true }
  }
}

let snapshot = readState()
const emit = () => listeners.forEach(listener => listener())

function update(change) {
  const next = change(readState())
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
    snapshot = { ...next, storageError: false }
  } catch {
    snapshot = { ...next, storageError: true }
  }
  emit()
}

window.addEventListener('storage', event => {
  if (event.key === STORAGE_KEY || event.key === null) {
    snapshot = readState()
    emit()
  }
})

export const demoStore = {
  subscribe(listener) {
    listeners.add(listener)
    return () => listeners.delete(listener)
  },
  getSnapshot: () => snapshot,
  simulateOffRoute: () => update(state => state.checkIn ? state : ({ ...state, checkIn: { id: crypto.randomUUID(), response: null } })),
  respond: response => update(state => {
    if (!state.checkIn || !Object.hasOwn(demoData.responses, response)) return state
    return {
      ...state,
      checkIn: { ...state.checkIn, response },
      contactRequest: response === 'contact' ? state.contactRequest ?? { createdAt: new Date().toISOString() } : state.contactRequest,
    }
  }),
  reset: () => update(emptyState),
}
