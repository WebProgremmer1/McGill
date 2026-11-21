// People always come from the signed-in account and circle data returned by the backend.
export function toTelHref(value) {
  const text = value?.trim()
  if (!text || !/^\+?[\d\s().-]{7,24}$/.test(text)) return null
  const number = text.replace(/[^\d+]/g, '')
  return number.replace('+', '').length >= 7 ? `tel:${number}` : null
}

export function firstName(person) {
  return person?.given_name?.trim() || person?.name?.trim().split(/\s+/)[0] || ''
}

export function initials(person) {
  const parts = person?.name?.trim().split(/\s+/).filter(Boolean) ?? []
  return parts.slice(0, 2).map(part => part[0].toUpperCase()).join('')
}
