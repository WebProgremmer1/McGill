export const fictionalMode = import.meta.env.MODE === 'fictional-auth'
export const authRequired = fictionalMode || import.meta.env.VITE_AUTH_REQUIRED === 'true'

async function call(path, { method = 'GET', body } = {}) {
  let response
  try {
    response = await fetch('/api' + path, {
      method,
      credentials: 'same-origin',
      signal: AbortSignal.timeout(10000),
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    })
  } catch {
    throw new Error('We couldn’t reach the server. Try again.')
  }
  const data = await response.json().catch(() => null)
  if (!response.ok) {
    const error = new Error(data?.error?.message || 'Something went wrong. Try again.')
    error.status = response.status
    error.field = data?.error?.details?.field
    throw error
  }
  return data
}

export async function getSession() {
  try {
    return await call('/auth/session')
  } catch (error) {
    // 404 means the sign-in backend is not deployed yet, so nobody is signed in.
    if (error.status === 401 || error.status === 404) return null
    throw error
  }
}

// Only a real redirect from the backend leaves this page. Anything else is reported.
export async function startGoogleSignIn() {
  const url = '/api/auth/google/start'
  let response
  try {
    response = await fetch(url, { redirect: 'manual', credentials: 'same-origin', signal: AbortSignal.timeout(10000) })
  } catch {
    throw new Error('We couldn’t reach the server. Try again.')
  }
  if (response.type !== 'opaqueredirect') throw new Error('Google sign-in isn’t available yet.')
  window.location.assign(url)
}

export const getFictionalAccounts = () => call('/dev/fictional-accounts').then(data => data.accounts)
export const signInFictional = accountId => call('/dev/fictional-sign-in', { method: 'POST', body: { account_id: accountId } })
export const signOut = () => call('/auth/sign-out', { method: 'POST' })
export const saveRole = role => call('/onboarding/role', { method: 'PUT', body: { role } })
export const createCircle = name => call('/circles', { method: 'POST', body: { name } })
export const joinCircle = code => call('/circles/join', { method: 'POST', body: { code } })
export const getCircle = id => call(`/circles/${encodeURIComponent(id)}`)
