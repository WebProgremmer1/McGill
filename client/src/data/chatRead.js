import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { isOwnMessage, oldestFirst } from './chat.js'

const MAX_STORED_IDS = 500

export const chatReadKey = (conversationId, caregiverId) =>
  `whats-next:chat-read:${conversationId ?? 'demo'}:${caregiverId ?? 'caregiver'}`

export function loadIdSet(key) {
  try {
    const stored = JSON.parse(localStorage.getItem(key))
    return new Set(Array.isArray(stored) ? stored.filter(id => typeof id === 'string') : [])
  } catch {
    return new Set()
  }
}

export function saveIdSet(key, ids) {
  try {
    localStorage.setItem(key, JSON.stringify([...ids].slice(-MAX_STORED_IDS)))
  } catch {
    // Without storage, the read state still works until the page is refreshed.
  }
}

// Tracks which incoming messages this caregiver has opened, per conversation.
export function useChatRead({ enabled, messages, conversationId, accountId }) {
  const key = chatReadKey(conversationId, accountId)
  const [read, setRead] = useState(() => (enabled ? loadIdSet(key) : new Set()))
  const latestRead = useRef(read)

  useEffect(() => {
    if (!enabled) return undefined
    const reload = () => {
      latestRead.current = loadIdSet(key)
      setRead(latestRead.current)
    }
    reload()
    // Another Care tab that opens the chat clears the badge here too.
    const onStorage = event => { if (event.key === key || event.key === null) reload() }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [enabled, key])

  const incomingIds = useMemo(() => (enabled
    ? oldestFirst(messages).filter(item => !isOwnMessage(item, 'caregiver', accountId)).map(item => item.id)
    : []), [accountId, enabled, messages])

  const markDisplayedRead = useCallback(() => {
    if (!enabled) return
    if (incomingIds.every(id => latestRead.current.has(id))) return
    const next = new Set([...loadIdSet(key), ...latestRead.current, ...incomingIds])
    latestRead.current = next
    setRead(next)
    saveIdSet(key, next)
  }, [enabled, incomingIds, key])

  return { unread: incomingIds.filter(id => !read.has(id)).length, markDisplayedRead }
}
