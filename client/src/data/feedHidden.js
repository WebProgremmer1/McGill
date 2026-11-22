import { useCallback, useEffect, useState } from 'react'
import { loadIdSet, saveIdSet } from './chatRead.js'

export const feedHiddenKey = (conversationId, caregiverId) =>
  `whats-next:feed-hidden:${conversationId ?? 'demo'}:${caregiverId ?? 'caregiver'}`

// Hiding only changes this caregiver's feed. It never acknowledges or closes an alert.
export function useHiddenFeed({ conversationId, accountId, enabled }) {
  const key = feedHiddenKey(conversationId, accountId)
  const [hidden, setHidden] = useState(() => (enabled ? loadIdSet(key) : new Set()))

  useEffect(() => {
    if (!enabled) return undefined
    const reload = () => setHidden(loadIdSet(key))
    reload()
    const onStorage = event => { if (event.key === key || event.key === null) reload() }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [enabled, key])

  const hide = useCallback(id => {
    const next = new Set([...loadIdSet(key), ...hidden, id])
    saveIdSet(key, next)
    setHidden(next)
  }, [hidden, key])

  return { hidden, hide }
}
