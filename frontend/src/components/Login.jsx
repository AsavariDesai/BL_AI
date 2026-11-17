import { useEffect, useState } from 'react'
import { api } from '../api'

function formatClock(date) {
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

export default function Login({ onLoggedIn }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)
  // Set only while a wrong (but not yet lockout-triggering) password has
  // been entered for this username — cleared on any successful login,
  // username change, or once a lockout takes over.
  const [attempts, setAttempts] = useState(null) // { failed, max, remaining }
  // Set once the account is locked — `untilMs` drives a live countdown so
  // the user sees it count down rather than a one-time, go-stale message.
  const [lockout, setLockout] = useState(null) // { untilMs, maxAttempts }
  const [secondsLeft, setSecondsLeft] = useState(0)
  const [showPassword, setShowPassword] = useState(false)

  useEffect(() => {
    if (!lockout) return
    const tick = () => {
      const left = Math.max(0, Math.ceil((lockout.untilMs - Date.now()) / 1000))
      setSecondsLeft(left)
      if (left <= 0) setLockout(null) // lets the user try again without a refresh
    }
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [lockout])

  async function submit(e) {
    e.preventDefault()
    if (!username || !password || lockout) return
    setBusy(true)
    setErr(null)
    try {
      const user = await api.login(username, password)
      setAttempts(null)
      setLockout(null)
      onLoggedIn(user)
    } catch (e) {
      // A network-level failure (server not running, wrong port, CORS block)
      // throws a plain TypeError from fetch() itself, before any HTTP
      // response exists — that's a different problem than a wrong password
      // and deserves a message that says so instead of "invalid password".
      if (e instanceof TypeError) {
        setErr(`Can't reach the server at ${api.base} — is it running?`)
        setAttempts(null)
      } else if (e.status === 423 && e.detail && typeof e.detail === 'object') {
        setLockout({
          untilMs: e.detail.retry_after_seconds != null
            ? Date.now() + e.detail.retry_after_seconds * 1000
            : new Date(e.detail.locked_until).getTime(),
          maxAttempts: e.detail.max_attempts,
        })
        setAttempts(null)
        setErr(null)
      } else if (e.status === 401 && e.detail && typeof e.detail === 'object'
        && e.detail.failed_attempts != null) {
        setAttempts({
          failed: e.detail.failed_attempts,
          max: e.detail.max_attempts,
          remaining: e.detail.remaining_attempts,
        })
        setErr(null)
      } else {
        setErr('Invalid username or password.')
        setAttempts(null)
      }
    } finally {
      setBusy(false)
    }
  }

  function onUsernameChange(v) {
    setUsername(v)
    // A counter or lockout tied to the previous username would be
    // confusing once they start typing a different one.
    setAttempts(null)
  }

  const minutesLeft = Math.max(1, Math.ceil(secondsLeft / 60))
  const unlockClock = lockout ? formatClock(new Date(lockout.untilMs)) : ''

  return (
    <div className="login-screen">
      <form className="login-card" onSubmit={submit}>
        <div className="login-logo">BL</div>
        <h1>BL-AI</h1>
        <p className="muted sm">Sign in to continue</p>

        <label className="login-field">
          <span>Username</span>
          <input
            autoFocus
            value={username}
            onChange={(e) => onUsernameChange(e.target.value)}
            autoComplete="username"
          />
        </label>
        <label className="login-field">
          <span>Password</span>
          <div className="login-password-wrap">
            <input
              type={showPassword ? 'text' : 'password'}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
            />
            <button
              type="button"
              className="login-password-toggle"
              onClick={() => setShowPassword((s) => !s)}
              disabled={!password}
              aria-label={showPassword ? 'Hide password' : 'Show password'}
              aria-pressed={showPassword}
              tabIndex={-1}
            >
              {showPassword ? (
                // eye-off
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                  strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M17.94 17.94A10.94 10.94 0 0 1 12 20c-7 0-11-8-11-8a18.5 18.5 0 0 1 5.06-5.94M9.9 4.24A10.94 10.94 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" />
                  <line x1="1" y1="1" x2="23" y2="23" />
                </svg>
              ) : (
                // eye
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                  strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                  <circle cx="12" cy="12" r="3" />
                </svg>
              )}
            </button>
          </div>
        </label>

        {err && <div className="login-error">{err}</div>}

        {attempts && !lockout && (
          <div className="login-warning">
            Incorrect password — {attempts.failed} of {attempts.max} attempts used.{' '}
            {attempts.remaining > 0
              ? `${attempts.remaining} attempt${attempts.remaining === 1 ? '' : 's'} left before the account is temporarily locked.`
              : 'One more wrong attempt will lock the account.'}
          </div>
        )}

        {lockout && (
          <div className="login-error login-lockout">
            <strong>Account temporarily locked</strong> — too many failed login attempts
            ({lockout.maxAttempts} in a row). Try again in {minutesLeft} minute{minutesLeft === 1 ? '' : 's'}
            {' '}(around {unlockClock}).
          </div>
        )}

        <button
          className="btn"
          type="submit"
          disabled={busy || !username || !password || !!lockout}
        >
          {busy ? 'Signing in…' : lockout ? `Locked — retry in ${secondsLeft}s` : 'Sign in'}
        </button>
      </form>
    </div>
  )
}
