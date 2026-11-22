// Older messages have no sender role, and those were always patient-to-caregiver notes.
export const messageRole = item => (item.sender_role === 'caregiver' ? 'caregiver' : 'patient')

export function isOwnMessage(item, viewerRole, accountId) {
  if (item.sender?.id && accountId) return item.sender.id === accountId
  return messageRole(item) === viewerRole
}

// The API lists newest first. The conversation reads oldest first, with one row per message ID.
export function oldestFirst(messages) {
  const byId = new Map()
  for (const item of [...(messages ?? [])].reverse()) byId.set(item.id, item)
  return [...byId.values()]
}
