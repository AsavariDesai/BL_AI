import { useState } from 'react'
import { api } from '../api'

export default function Login({ onLoggedIn }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)

  async function submit(e) {
    e.preventDefault()
    if (!username || !password) return
    setBusy(true)
    setErr(null)
    try {
      const user = await api.login(username, password)
      onLoggedIn(user)
    } catch (e) {
      // A network-level failure (server not running, wrong port, CORS block)
      // throws a plain TypeError from fetch() itself, before any HTTP
      // response exists — that's a different problem than a wrong password
      // and deserves a message that says so instead of "invalid password".
      if (e instanceof TypeError) {
        setErr(`Can't reach the server at ${api.base} — is it running?`)
      } else {
        setErr('Invalid username or password.')
      }
    } finally {
      setBusy(false)
    }
  }

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
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
          />
        </label>
        <label className="login-field">
          <span>Password</span>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
          />
        </label>

        {err && <div className="login-error">{err}</div>}

        <button className="btn" type="submit" disabled={busy || !username || !password}>
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </div>
  )
}
