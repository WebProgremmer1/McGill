import { useEffect, useRef, useState } from 'react'
import {
  createCircle, fictionalMode, getFictionalAccounts, getSession, joinCircle,
  saveRole, signInFictional, signOut, startGoogleSignIn,
} from './data/accountApi.js'
import Icon from './Icon.jsx'

const titles = ['Sign in', 'How will you use the app?', 'Create or join a care circle']
const roles = [
  { value: 'self', label: 'For myself', hint: 'I want reminders and support.', icon: 'home' },
  { value: 'caregiver', label: 'I’m a caregiver', hint: 'I help care for someone.', icon: 'heart' },
  { value: 'family', label: 'I’m a family member', hint: 'I stay connected with a relative.', icon: 'users' },
]

function FieldError({ id, children }) {
  return <p id={id} className="field-error" role="alert">{children}</p>
}

function Actions({ onBack, backLabel = 'Back', children }) {
  return (
    <div className="onboarding-actions">
      {children}
      {onBack && <button type="button" className="button secondary" onClick={onBack}><Icon name="back" />{backLabel}</button>}
    </div>
  )
}

// Fixture-only route. It is deliberately separate from the Google button.
export function TestSession() {
  const [accounts, setAccounts] = useState([])
  const [accountId, setAccountId] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const field = useRef(null)

  useEffect(() => {
    let active = true
    getFictionalAccounts().then(list => {
      if (!active) return
      setAccounts(list)
      setAccountId(current => current || list[0]?.id || '')
    }).catch(failure => { if (active) setError(failure.message) })
    return () => { active = false }
  }, [])

  async function submit(event) {
    event.preventDefault()
    if (busy || !accountId) return
    setBusy(true)
    setError('')
    try {
      await signInFictional(accountId)
      window.location.replace('/onboarding')
    } catch (failure) {
      setError(failure.message)
      setBusy(false)
      field.current?.focus()
    }
  }

  return (
    <main id="main" className="onboarding">
      <h1>Fictional test session</h1>
      <p className="test-label">This is not Google sign-in. It only tests the screens after sign-in.</p>
      <form className="onboarding-form" onSubmit={submit} noValidate>
        <div className="onboarding-field">
          <label htmlFor="account">Fictional test account</label>
          <select id="account" ref={field} value={accountId} aria-invalid={Boolean(error)}
            aria-describedby={error ? 'account-error' : undefined}
            onChange={event => { setAccountId(event.target.value); setError('') }}>
            {accounts.map(account => <option key={account.id} value={account.id}>{account.name}</option>)}
          </select>
          {error && <FieldError id="account-error">{error}</FieldError>}
        </div>
        <Actions>
          <button type="submit" className="button primary" aria-disabled={busy || !accountId}>
            <Icon name={error ? 'retry' : 'next'} />{error ? 'Try again' : 'Start test session'}
          </button>
        </Actions>
      </form>
    </main>
  )
}

function SignInStep({ session, onContinue, onSignedOut }) {
  const callbackFailed = new URLSearchParams(window.location.search).has('auth_error')
  const [error, setError] = useState(callbackFailed ? 'Google sign-in didn’t finish. Try again.' : '')
  const [busy, setBusy] = useState(false)

  async function startGoogle() {
    if (busy) return
    setBusy(true)
    setError('')
    try {
      await startGoogleSignIn()
    } catch (failure) {
      setError(failure.message)
    } finally {
      setBusy(false)
    }
  }

  async function useDifferentAccount() {
    setError('')
    try {
      await signOut()
      onSignedOut()
    } catch (failure) {
      setError(failure.message)
    }
  }

  if (session) {
    return (
      <>
        <p className="onboarding-lead">Signed in as <strong>{session.account.name}</strong>.</p>
        {error && <FieldError id="account-error">{error}</FieldError>}
        <Actions onBack={useDifferentAccount} backLabel="Use a different account">
          <button type="button" className="button primary" onClick={onContinue}>Continue<Icon name="next" /></button>
        </Actions>
      </>
    )
  }

  return (
    <div className="onboarding-form">
      <div className="onboarding-field">
        <button type="button" className="button primary" aria-disabled={busy}
          aria-describedby={error ? 'google-error' : undefined} onClick={startGoogle}>
          <Icon name="signIn" />Continue with Google
        </button>
        {error && <FieldError id="google-error">{error}</FieldError>}
      </div>
      {fictionalMode && <a className="directions-link test-link" href="/test-session">Use a fictional test session</a>}
    </div>
  )
}

function RoleStep({ role, onRole, onBack, onSaved }) {
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const first = useRef(null)

  async function submit(event) {
    event.preventDefault()
    if (busy) return
    if (!role) {
      setError('Choose one option.')
      first.current?.focus()
      return
    }
    setBusy(true)
    setError('')
    try {
      onSaved(await saveRole(role))
    } catch (failure) {
      setError(failure.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="onboarding-form" onSubmit={submit} noValidate>
      <fieldset className="choice-group" aria-describedby={error ? 'role-error' : undefined}>
        <legend>Choose one</legend>
        {roles.map((option, index) => (
          <label className="choice role-card" key={option.value}>
            <input ref={index === 0 ? first : undefined} type="radio" name="role" value={option.value}
              checked={role === option.value} onChange={() => { onRole(option.value); setError('') }} />
            <Icon name={option.icon} />
            <span><strong>{option.label}</strong><span>{option.hint}</span></span>
          </label>
        ))}
        {error && <FieldError id="role-error">{error}</FieldError>}
      </fieldset>
      <Actions onBack={onBack}>
        <button type="submit" className="button primary" aria-disabled={busy}>
          {error && role ? <><Icon name="retry" />Try again</> : <>Continue<Icon name="next" /></>}
        </button>
      </Actions>
    </form>
  )
}

function CircleStep({ role, onBack, onDone }) {
  const [mode, setMode] = useState(role === 'self' ? 'create' : 'join')
  const [values, setValues] = useState({ join: '', create: '' })
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const field = useRef(null)
  const joining = mode === 'join'
  const value = values[mode]
  const guidance = role === 'self'
    ? 'Create your circle, then invite the people who help you.'
    : role === 'family' ? 'Join with the invite code from your family.' : 'Join with the invite code from the person you support.'
  const choices = [['join', 'Join with an invite code'], ['create', 'Create a new circle']]
  if (role === 'self') choices.reverse()

  async function submit(event) {
    event.preventDefault()
    if (busy) return
    if (!value.trim()) {
      setError(joining ? 'Enter your invite code.' : 'Enter a name for your care circle.')
      field.current?.focus()
      return
    }
    setBusy(true)
    setError('')
    try {
      onDone(joining ? await joinCircle(value) : await createCircle(value))
    } catch (failure) {
      setError(failure.message)
      field.current?.focus()
      setBusy(false)
    }
  }

  return (
    <form className="onboarding-form" onSubmit={submit} noValidate>
      <p className="onboarding-lead">{guidance}</p>
      <fieldset className="choice-group">
        <legend>What would you like to do?</legend>
        {choices.map(([option, label]) => (
          <label className="choice" key={option}>
            <input type="radio" name="circle-mode" value={option} checked={mode === option}
              onChange={() => { setMode(option); setError('') }} />
            <span><strong>{label}</strong></span>
          </label>
        ))}
      </fieldset>
      <div className="onboarding-field">
        <label htmlFor="circle-value">{joining ? 'Invite code' : 'Circle name'}</label>
        <input id="circle-value" ref={field} type="text" value={value} maxLength={40}
          autoCapitalize={joining ? 'characters' : 'words'} autoComplete="off" aria-invalid={Boolean(error)}
          aria-describedby={error ? 'circle-error' : undefined}
          onChange={event => { setValues(current => ({ ...current, [mode]: event.target.value })); setError('') }} />
        {error && <FieldError id="circle-error">{error}</FieldError>}
      </div>
      <Actions onBack={onBack}>
        <button type="submit" className="button primary" aria-disabled={busy}>
          <Icon name={error ? 'retry' : 'users'} />{error ? 'Try again' : joining ? 'Join circle' : 'Create circle'}
        </button>
      </Actions>
    </form>
  )
}

export default function Onboarding({ familyView }) {
  const [session, setSession] = useState(null)
  const [step, setStep] = useState(null)
  const [role, setRole] = useState(null)
  const [loadError, setLoadError] = useState('')
  const [attempt, setAttempt] = useState(0)
  const heading = useRef(null)
  const previousStep = useRef(null)

  function openCircle(circle) {
    // The server's permissions choose the screen. The onboarding role does not.
    const permissions = circle.permissions ?? []
    const dashboard = permissions.includes('view_dashboard') && (familyView || !permissions.includes('view_today'))
    window.location.replace(`/c/${encodeURIComponent(circle.id)}${dashboard ? '/manage' : ''}`)
  }

  function route(next) {
    setSession(next)
    if (!next) {
      setStep(0)
      return
    }
    setRole(current => current ?? next.role)
    if (next.circles.length) openCircle(next.circles[0])
    else setStep(next.role ? 2 : 1)
  }

  useEffect(() => {
    let active = true
    getSession().then(next => { if (active) { setLoadError(''); route(next) } })
      .catch(failure => { if (active) setLoadError(failure.message) })
    return () => { active = false }
    // `route` only uses state setters and stable page values.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [attempt])

  useEffect(() => {
    if (step === null) return
    document.title = titles[step]
    if (previousStep.current !== null && previousStep.current !== step) heading.current?.focus()
    previousStep.current = step
  }, [step])

  if (loadError) {
    return (
      <main id="main" className="onboarding">
        <h1>We couldn’t load your account</h1>
        <p className="field-error" role="alert">{loadError}</p>
        <button type="button" className="button primary" onClick={() => { setLoadError(''); setAttempt(value => value + 1) }}>
          <Icon name="retry" />Try again
        </button>
      </main>
    )
  }

  if (step === null) return <main id="main" className="onboarding"><p role="status">Loading…</p></main>

  return (
    <main id="main" className="onboarding">
      {step > 0 && <p className="step-count">Step {step} of 2</p>}
      <h1 ref={heading} tabIndex={-1}>{titles[step]}</h1>
      {step === 0 && <SignInStep session={session} onContinue={() => setStep(1)}
        onSignedOut={() => { setRole(null); route(null) }} />}
      {step === 1 && <RoleStep role={role} onRole={setRole} onBack={() => setStep(0)}
        onSaved={next => { setSession(next); if (next.circles.length) openCircle(next.circles[0]); else setStep(2) }} />}
      {step === 2 && <CircleStep role={role} onBack={() => setStep(1)} onDone={openCircle} />}
    </main>
  )
}
