import { useCallback, useEffect, useState } from 'react'
import BackendDemo from './BackendDemo.jsx'
import { fictionalMode, getCircle, getSession, signOut } from './data/accountApi.js'
import { careRoute } from './data/careRoutes.js'
import Icon from './Icon.jsx'
import Onboarding, { TestSession } from './Onboarding.jsx'

function CircleMessage({ title, children }) {
  return (
    <main id="main" className="onboarding">
      <h1>{title}</h1>
      {children}
    </main>
  )
}

function CircleRoute({ circleId, family }) {
  const [circle, setCircle] = useState(null)
  const [account, setAccount] = useState(null)
  const [status, setStatus] = useState('loading')
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)

  const onAccessLost = useCallback(code => {
    setCircle(null)
    setStatus(code === 401 ? 'loading' : 'denied')
    if (code === 401) window.location.replace('/onboarding')
  }, [])

  useEffect(() => {
    let active = true
    Promise.all([getCircle(circleId), getSession()]).then(([result, session]) => {
      if (!active) return
      if (!session) {
        window.location.replace('/onboarding')
        return
      }
      // Backend permissions choose the layout. The onboarding role is never checked here.
      const permissions = result.permissions ?? []
      const base = `/c/${encodeURIComponent(result.id)}`
      if (!permissions.includes(family ? 'view_dashboard' : 'view_today')) {
        if (permissions.includes(family ? 'view_today' : 'view_dashboard')) {
          window.location.replace(family ? base : `${base}/manage`)
        } else {
          setStatus('denied')
        }
        return
      }
      setAccount(session.account)
      setCircle(result)
      setStatus('ready')
    }).catch(failure => {
      if (!active) return
      setCircle(null)
      if (failure.status === 401) window.location.replace('/onboarding')
      else if (failure.status === 403 || failure.status === 404) setStatus('denied')
      else {
        setError(failure.message)
        setStatus('error')
      }
    })
    return () => { active = false }
  }, [circleId, family, attempt])

  async function leave() {
    try { await signOut() } finally { window.location.replace('/onboarding') }
  }

  if (status === 'loading') return <main id="main" className="onboarding"><p role="status">Checking access…</p></main>
  if (status === 'denied') {
    return (
      <CircleMessage title="You don’t have access to this care circle">
        <p className="onboarding-lead">Ask someone in the circle for an invite code.</p>
        <div className="onboarding-actions">
          <a className="button primary" href="/onboarding"><Icon name="users" />Go to my care circles</a>
          <button type="button" className="button secondary" onClick={leave}><Icon name="signOut" />Sign out</button>
        </div>
      </CircleMessage>
    )
  }
  if (status === 'error') {
    return (
      <CircleMessage title="We couldn’t open this care circle">
        <p className="field-error" role="alert">{error}</p>
        <button type="button" className="button primary" onClick={() => { setStatus('loading'); setAttempt(value => value + 1) }}>
          <Icon name="retry" />Try again
        </button>
      </CircleMessage>
    )
  }

  const shell = {
    footer: (
      <>
        {fictionalMode && <span>Fictional test session · Not Google sign-in</span>}
        {!family && <button type="button" className="text-button" onClick={leave}>Sign out</button>}
      </>
    ),
  }
  return <BackendDemo key={circle.id} family={family} circle={circle} account={account} onAccessLost={onAccessLost} onSignOut={leave} shell={shell} />
}

export default function AccessGate() {
  const path = window.location.pathname.replace(/\/$/, '')
  const match = path.match(/^\/c\/([^/]+)(\/manage(?:\/.*)?)?$/)
  if (match) return <CircleRoute circleId={decodeURIComponent(match[1])} family={Boolean(match[2])} />
  if (path === '/test-session' && fictionalMode) return <TestSession />
  return <Onboarding familyView={careRoute(path)?.base === '/manage'} />
}
