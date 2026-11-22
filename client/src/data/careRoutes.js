const VIEWS = new Set(['messages', 'account'])

// Reads /manage or /c/:id/manage, plus an optional caregiver view.
export function careRoute(pathname) {
  const match = pathname.replace(/\/+$/, '').match(/^((?:\/c\/[^/]+)?\/manage)(?:\/(.*))?$/)
  if (!match) return null
  return { base: match[1], view: VIEWS.has(match[2]) ? match[2] : 'home' }
}

export const carePath = (base, view) => (view === 'home' ? base : `${base}/${view}`)
