// Local UI fixture for `npm run dev:onboarding`. It is not real authentication.
// It never completes Google sign-in. Test sessions start only from /test-session.
import { randomBytes } from 'node:crypto'

const cookieName = 'fictional_session'
const personPermissions = ['view_today', 'read_reminders', 'send_messages', 'read_journey', 'start_journey', 'read_help', 'request_help']
const caregiverPermissions = ['view_dashboard', 'read_reminders', 'send_reminders', 'read_messages', 'read_journey', 'read_help']
const remindersOnly = ['view_dashboard', 'read_reminders']

function seed() {
  const contactFields = {
    phone: process.env.FICTIONAL_TEST_PHONE || undefined,
    photo_url: process.env.FICTIONAL_TEST_PHOTO || undefined,
  }
  return {
    accounts: new Map([
      ['nora', { id: 'nora', name: 'Nora Ellis', given_name: 'Nora', role: 'self', ...contactFields }],
      ['priya', { id: 'priya', name: 'Priya Ellis', given_name: 'Priya', role: 'caregiver', ...contactFields }],
      ['omar', { id: 'omar', name: 'Omar Haddad', role: 'self' }],
      ['sam', { id: 'sam', name: 'Sam Rivera', given_name: 'Sam', role: null }],
      ['riley', { id: 'riley', name: 'Riley Chen', given_name: 'Riley', role: 'caregiver' }],
      ['jordan', { id: 'jordan', name: 'Jordan Lee (test session fails once)', given_name: 'Jordan', role: null, failOnce: true }],
    ]),
    circles: new Map([
      ['circle_ellis', {
        id: 'circle_ellis',
        name: 'Ellis care circle',
        recipient: 'nora',
        relationships: new Map([['priya', 'daughter']]),
        invites: new Map([['ELLIS-CARE', caregiverPermissions], ['ELLIS-VIEW', remindersOnly]]),
        members: new Map([['nora', personPermissions], ['priya', caregiverPermissions]]),
        journeys: new Set(),
        reminder: { message: 'I’ll pick you up at 3 p.m. Bring your blue coat.', senderId: 'priya' },
      }],
      ['circle_haddad', {
        id: 'circle_haddad',
        name: 'Haddad care circle',
        recipient: 'omar',
        relationships: new Map(),
        invites: new Map([['HADDAD-CARE', caregiverPermissions]]),
        members: new Map([['omar', personPermissions]]),
        journeys: new Set(),
        reminder: null,
      }],
      ['circle_chen', {
        id: 'circle_chen',
        name: 'Chen care circle',
        recipient: null,
        relationships: new Map(),
        invites: new Map([['CHEN-DEMO', caregiverPermissions]]),
        members: new Map([['riley', caregiverPermissions]]),
        journeys: new Set(),
        reminder: null,
      }],
    ]),
    sessions: new Map(),
  }
}

function send(res, status, body, headers = {}) {
  res.statusCode = status
  res.setHeader('Content-Type', 'application/json')
  res.setHeader('Cache-Control', 'no-store')
  for (const [key, value] of Object.entries(headers)) res.setHeader(key, value)
  res.end(JSON.stringify(body))
}

const fail = (res, status, code, message, field) =>
  send(res, status, { error: { code, message, details: field ? { field } : null } })
const forbidden = res => fail(res, 403, 'circle_forbidden', 'You don’t have access to this care circle.')

async function readBody(req) {
  let text = ''
  for await (const chunk of req) {
    text += chunk
    if (text.length > 16384) return null
  }
  try {
    return text ? JSON.parse(text) : {}
  } catch {
    return null
  }
}

function sessionAccount(state, req) {
  const cookie = (req.headers.cookie || '').split(/;\s*/).find(item => item.startsWith(`${cookieName}=`))
  const accountId = cookie && state.sessions.get(cookie.slice(cookieName.length + 1))
  return accountId ? state.accounts.get(accountId) : null
}

function personView(state, circle, id, includeContact) {
  const person = state.accounts.get(id)
  if (!person) return null
  const relationship = circle.relationships.get(id)
  return {
    id: person.id,
    name: person.name,
    ...(person.given_name ? { given_name: person.given_name } : {}),
    ...(relationship ? { relationship } : {}),
    ...(person.photo_url ? { photo_url: person.photo_url } : {}),
    ...(includeContact && person.phone ? { phone: person.phone } : {}),
  }
}

const circlesFor = (state, account) => [...state.circles.values()].filter(circle => circle.members.has(account.id))

function circleView(state, circle, account) {
  const permissions = circle.members.get(account.id)
  const includeContact = permissions.includes('send_reminders') || permissions.includes('request_help')
  const caregiverIds = [...circle.members].filter(([id, granted]) => id !== circle.recipient && granted.includes('send_reminders')).map(([id]) => id)
  return {
    id: circle.id,
    name: circle.name,
    permissions,
    care_recipient: circle.recipient ? personView(state, circle, circle.recipient, includeContact) : null,
    caregivers: caregiverIds.map(id => personView(state, circle, id, includeContact)),
  }
}

const sessionView = (state, account) => ({
  account: { id: account.id, name: account.name, ...(account.given_name ? { given_name: account.given_name } : {}) },
  role: account.role,
  circles: circlesFor(state, account).map(circle => circleView(state, circle, account)),
  fictional: true,
})

async function upstream(target, path, options = {}) {
  const response = await fetch(target + path, { signal: AbortSignal.timeout(10000), ...options })
  const body = await response.json().catch(() => null)
  return { status: response.status, body }
}

const jsonPost = payload => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload ?? {}) })

async function handleScoped(state, target, req, res, circle, account, rest, url) {
  const parts = rest.split('/').filter(Boolean)
  const method = req.method
  const permissions = circle.members.get(account.id)
  const can = permission => permissions.includes(permission)

  if (rest === '/reminder' && method === 'GET') {
    if (!can('read_reminders')) return forbidden(res)
    if (!circle.reminder) return send(res, 200, { message: null, sender: null })
    return send(res, 200, { message: circle.reminder.message, sender: personView(state, circle, circle.reminder.senderId, false) })
  }
  if (rest === '/reminder' && method === 'PUT') {
    if (!can('send_reminders')) return forbidden(res)
    const body = await readBody(req)
    const message = typeof body?.message === 'string' ? body.message.trim() : ''
    if (!message || message.length > 140) return fail(res, 422, 'invalid_reminder', 'Write a reminder of 140 characters or fewer.', 'message')
    // The sender comes from the session, never from the request body.
    circle.reminder = { message, senderId: account.id }
    return send(res, 200, { message, sender: personView(state, circle, account.id, false) })
  }
  if (rest === '/messages' && method === 'GET') {
    if (!can('read_messages')) return forbidden(res)
    return send(res, 200, [...(circle.messages ?? [])].reverse())
  }
  if (rest === '/messages' && method === 'POST') {
    if (!can('send_messages')) return forbidden(res)
    const body = await readBody(req)
    const text = typeof body?.body === 'string' ? body.body.trim() : ''
    if (!text || text.length > 280) return fail(res, 422, 'invalid_message', 'Write a message of 280 characters or fewer.', 'body')
    // The sender comes from the session, never from the request body.
    const message = { id: `msg_${randomBytes(4).toString('hex')}`, body: text, created_at: new Date().toISOString(), sender: personView(state, circle, account.id, false) }
    circle.messages = [...(circle.messages ?? []), message]
    return send(res, 201, message)
  }
  if (rest === '/journeys' && method === 'GET') {
    if (!can('read_journey')) return forbidden(res)
    const { status, body } = await upstream(target, '/api/journeys')
    return send(res, status, status === 200 ? body.filter(item => circle.journeys.has(item.id)) : body)
  }
  if (rest === '/journeys' && method === 'POST') {
    if (!can('start_journey') && !can('request_help')) return forbidden(res)
    const payload = await readBody(req)
    const owner = state.accounts.get(circle.recipient) ?? account
    const { status, body } = await upstream(target, '/api/journeys', jsonPost({ ...payload, user_name: owner.name }))
    if (status === 201) circle.journeys.add(body.id)
    return send(res, status, body)
  }
  if (parts[0] === 'journeys' && parts.length === 3) {
    const journeyId = decodeURIComponent(parts[1])
    if (!circle.journeys.has(journeyId)) return forbidden(res)
    const path = `/api/journeys/${encodeURIComponent(journeyId)}/${parts[2]}`
    if (parts[2] === 'checkins' && method === 'GET') {
      if (!can('read_journey')) return forbidden(res)
      const { status, body } = await upstream(target, path)
      return send(res, status, body)
    }
    if (parts[2] === 'checkin' && method === 'POST') {
      const payload = await readBody(req)
      if (!can(payload?.help_requested ? 'request_help' : 'start_journey')) return forbidden(res)
      const { status, body } = await upstream(target, path, jsonPost(payload))
      return send(res, status, body)
    }
    if (['complete', 'cancel'].includes(parts[2]) && method === 'POST') {
      if (!can('start_journey') && !can('request_help')) return forbidden(res)
      const { status, body } = await upstream(target, path, { method: 'POST' })
      return send(res, status, body)
    }
  }
  if (rest === '/alerts' && method === 'GET') {
    if (!can('read_help')) return forbidden(res)
    const { status, body } = await upstream(target, `/api/alerts${url.search}`)
    return send(res, status, status === 200 ? body.filter(item => circle.journeys.has(item.journey_id)) : body)
  }
  return fail(res, 404, 'not_found', 'Not found.')
}

async function handle(state, target, req, res, next) {
  const url = new URL(req.url, 'http://local.test')
  const path = url.pathname
  if (path === '/viewer' || path.startsWith('/viewer/') || path === '/api/maps-config') {
    const account = sessionAccount(state, req)
    if (!account) return fail(res, 401, 'not_signed_in', 'Sign in to continue.')
    if (!circlesFor(state, account).some(circle => circle.members.get(account.id).includes('read_journey'))) return forbidden(res)
    return next()
  }
  if (!path.startsWith('/api/') || path === '/api/health' || path === '/api/routes/predefined') return next()

  if (path === '/api/auth/google/start') return fail(res, 501, 'google_pending', 'Google sign-in isn’t available yet.')
  if (path === '/api/dev/fictional-accounts' && req.method === 'GET') {
    return send(res, 200, { accounts: [...state.accounts.values()].map(({ id, name }) => ({ id, name })) })
  }
  if (path === '/api/dev/fictional-sign-in' && req.method === 'POST') {
    const body = await readBody(req)
    const account = state.accounts.get(body?.account_id)
    if (!account) return fail(res, 422, 'unknown_account', 'Choose a fictional account.', 'account')
    if (account.failOnce) {
      account.failOnce = false
      return fail(res, 503, 'test_session_failed', 'The test session didn’t start. Try again.', 'account')
    }
    const token = randomBytes(24).toString('hex')
    state.sessions.set(token, account.id)
    return send(res, 200, sessionView(state, account), { 'Set-Cookie': `${cookieName}=${token}; HttpOnly; SameSite=Strict; Path=/` })
  }

  const account = sessionAccount(state, req)
  if (!account) return fail(res, 401, 'not_signed_in', 'Sign in to continue.')

  if (path === '/api/auth/session' && req.method === 'GET') return send(res, 200, sessionView(state, account))
  if (path === '/api/auth/sign-out' && req.method === 'POST') {
    for (const [token, id] of state.sessions) if (id === account.id) state.sessions.delete(token)
    return send(res, 200, { status: 'signed_out' }, { 'Set-Cookie': `${cookieName}=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0` })
  }
  if (path === '/api/onboarding/role' && req.method === 'PUT') {
    const body = await readBody(req)
    if (!['self', 'caregiver', 'family'].includes(body?.role)) return fail(res, 422, 'invalid_role', 'Choose one option.', 'role')
    account.role = body.role // Onboarding input only. It never grants access to an existing circle.
    return send(res, 200, sessionView(state, account))
  }
  if (path === '/api/circles' && req.method === 'POST') {
    const body = await readBody(req)
    const name = typeof body?.name === 'string' ? body.name.trim() : ''
    if (name.length < 2 || name.length > 40) return fail(res, 422, 'invalid_circle_name', 'Enter a name from 2 to 40 characters.', 'name')
    const id = `circle_${randomBytes(6).toString('hex')}`
    const forSelf = account.role === 'self'
    const circle = {
      id,
      name,
      recipient: forSelf ? account.id : null,
      relationships: new Map(),
      invites: new Map(),
      members: new Map([[account.id, forSelf ? personPermissions : caregiverPermissions]]),
      journeys: new Set(),
      reminder: null,
    }
    state.circles.set(id, circle)
    return send(res, 201, circleView(state, circle, account))
  }
  if (path === '/api/circles/join' && req.method === 'POST') {
    const body = await readBody(req)
    const code = typeof body?.code === 'string' ? body.code.trim().toUpperCase() : ''
    if (!code) return fail(res, 422, 'invalid_code', 'Enter your invite code.', 'code')
    const circle = [...state.circles.values()].find(item => item.invites.has(code))
    if (!circle) return fail(res, 404, 'invite_not_found', 'That code didn’t work. Check it and try again.', 'code')
    // The invite sets permissions. The role chosen during onboarding has no effect.
    if (!circle.members.has(account.id)) circle.members.set(account.id, circle.invites.get(code))
    return send(res, 200, circleView(state, circle, account))
  }

  const scoped = path.match(/^\/api\/circles\/([^/]+)(\/.*)?$/)
  if (scoped) {
    const circle = state.circles.get(decodeURIComponent(scoped[1]))
    // Unknown and forbidden circles look identical to the client.
    if (!circle || !circle.members.has(account.id)) return forbidden(res)
    if (!scoped[2] && req.method === 'GET') return send(res, 200, circleView(state, circle, account))
    return handleScoped(state, target, req, res, circle, account, scoped[2] || '', url)
  }
  return fail(res, 403, 'circle_required', 'This data is only available through a care circle.')
}

export function fictionalAuth(target) {
  const state = seed()
  return {
    name: 'fictional-auth',
    apply: 'serve',
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        handle(state, target, req, res, next).catch(() => {
          if (!res.headersSent) fail(res, 502, 'upstream_failed', 'We couldn’t reach the server. Try again.')
        })
      })
    },
  }
}
