import { useEffect, useRef, useState } from 'react'
import { authRequired } from './data/accountApi.js'
import Icon from './Icon.jsx'
import './SignUp.css'

// Plain links: the URL is the role, so no session, account, or browser setting is created.
const demoRoles = [
  { href: '/manage', label: 'I’m a caregiver', opens: 'Opens Care dashboard', icon: 'users' },
  { href: '/', label: 'I’m signing up for myself', opens: 'Opens Today', icon: 'person' },
]

const roles = [
  { value: 'caregiver', label: 'I’m a caregiver', icon: 'users' },
  { value: 'self', label: 'I’m signing up for myself', icon: 'person' },
]
const fieldOrder = ['role', 'name', 'email', 'password']

function validate(form) {
  const values = new FormData(form)
  const email = String(values.get('email')).trim()
  const password = String(values.get('password'))
  const errors = {}
  if (!values.get('role')) errors.role = 'Choose one option.'
  if (!String(values.get('name')).trim()) errors.name = 'Enter your name.'
  if (!email) errors.email = 'Enter your email.'
  else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) errors.email = 'Enter an email like name@example.com.'
  if (!password) errors.password = 'Enter a password.'
  else if (password.length < 8) errors.password = 'Use at least 8 characters.'
  return errors
}

function Field({ name, label, type = 'text', autoComplete, hint, error }) {
  const id = `signup-${name}`
  const describedBy = [hint && `${id}-hint`, error && `${id}-error`].filter(Boolean).join(' ') || undefined
  return (
    <div className="signup-field">
      <label htmlFor={id}>{label}</label>
      {hint && <p id={`${id}-hint`} className="signup-hint">{hint}</p>}
      <input id={id} name={name} type={type} autoComplete={autoComplete} required
        aria-invalid={Boolean(error)} aria-describedby={describedBy} />
      {error && <p id={`${id}-error`} className="signup-error">{error}</p>}
    </div>
  )
}

export default function SignUp() {
  const formRef = useRef(null)
  const [errors, setErrors] = useState({})
  const [unavailable, setUnavailable] = useState(false)

  useEffect(() => {
    document.title = 'Sign up · What’s Next?'
  }, [])

  // Values stay in the native fields. Nothing is sent, stored, or logged.
  function submit(event) {
    event.preventDefault()
    const form = formRef.current
    const nextErrors = validate(form)
    setErrors(nextErrors)
    const firstInvalid = fieldOrder.find(name => nextErrors[name])
    if (firstInvalid) {
      setUnavailable(false)
      const field = form.elements[firstInvalid]
      ;(firstInvalid === 'role' ? field[0] : field).focus()
      return
    }
    form.elements.password.value = ''
    setUnavailable(true)
  }

  function clearFieldError(event) {
    const { name } = event.target
    setUnavailable(false)
    setErrors(current => {
      if (!current[name]) return current
      const next = { ...current }
      delete next[name]
      return next
    })
  }

  return (
    <div className="signup-page">
      <main className="signup-column">
        <h1>Sign up</h1>
        {!authRequired && (
          <section className="signup-demo" aria-labelledby="signup-demo-title">
            <h2 id="signup-demo-title">Try the demo</h2>
            <p>Choose a role. No account needed. All demo data is fictional.</p>
            <div className="signup-role-grid">
              {demoRoles.map(role => (
                <a className="signup-demo-card" href={role.href} key={role.href}>
                  <Icon name={role.icon} className="signup-role-icon" />
                  <span>{role.label}</span>
                  <span className="signup-demo-opens">{role.opens}<Icon name="next" /></span>
                </a>
              ))}
            </div>
          </section>
        )}
        <h2 className="signup-account-title">Create an account</h2>
        <form ref={formRef} className="signup-form" onSubmit={submit} onChange={clearFieldError} noValidate>
          <fieldset className="signup-roles">
            <legend>Who is this account for?</legend>
            <div className="signup-role-grid">
              {roles.map(role => (
                <label className="signup-role" key={role.value}>
                  <input type="radio" name="role" value={role.value} required
                    aria-describedby={errors.role ? 'signup-role-error' : undefined} />
                  <span className="signup-role-card">
                    <span className="signup-check" aria-hidden="true"><Icon name="check" /></span>
                    <Icon name={role.icon} className="signup-role-icon" />
                    <span>{role.label}</span>
                  </span>
                </label>
              ))}
            </div>
            {errors.role && <p id="signup-role-error" className="signup-error">{errors.role}</p>}
          </fieldset>
          <Field name="name" label="Name" autoComplete="name" error={errors.name} />
          <Field name="email" label="Email" type="email" autoComplete="email" error={errors.email} />
          <Field name="password" label="Password" type="password" autoComplete="new-password"
            hint="At least 8 characters." error={errors.password} />
          <button type="submit" className="signup-submit">Create account</button>
          <p className="signup-notice" role="status">{unavailable && 'Account creation isn’t available yet.'}</p>
        </form>
        <p className="signup-signin">Already have an account? Sign in isn’t available yet.</p>
      </main>
    </div>
  )
}
