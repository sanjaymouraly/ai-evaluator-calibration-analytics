import { useState } from 'react'
import type { FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError } from '../api/client'
import { useAuth } from '../auth'
import { Field, InfoNote } from '../components/ui'

export default function LoginPage() {
  const { login, register } = useAuth()
  const navigate = useNavigate()
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [email, setEmail] = useState('')
  const [fullName, setFullName] = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState('reviewer')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      if (mode === 'login') await login(email, password)
      else await register(email, fullName, password, role)
      navigate('/projects')
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : 'Unable to sign in. Please try again.',
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-900 px-4 py-10">
      <div className="w-full max-w-md">
        <div className="mb-6 flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-brand-600 text-base font-bold text-white">
            EC
          </div>
          <div>
            <h1 className="text-lg font-semibold text-white">AI Evaluator Calibration</h1>
            <p className="text-xs text-slate-400">&amp; Disagreement Analytics Platform</p>
          </div>
        </div>

        <div className="card card-pad">
          <div className="mb-4 flex rounded-lg bg-slate-100 p-1" role="tablist" aria-label="Authentication mode">
            {(['login', 'register'] as const).map((m) => (
              <button
                key={m}
                type="button"
                role="tab"
                aria-selected={mode === m}
                className={`flex-1 rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                  mode === m ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-700'
                }`}
                onClick={() => {
                  setMode(m)
                  setError(null)
                }}
              >
                {m === 'login' ? 'Sign in' : 'Create account'}
              </button>
            ))}
          </div>

          <form onSubmit={onSubmit} className="space-y-4" noValidate>
            <Field label="Email" htmlFor="email">
              <input
                id="email"
                type="email"
                autoComplete="email"
                required
                className="input"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </Field>

            {mode === 'register' && (
              <Field label="Full name" htmlFor="fullname">
                <input
                  id="fullname"
                  type="text"
                  autoComplete="name"
                  required
                  className="input"
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                />
              </Field>
            )}

            <Field
              label="Password"
              htmlFor="password"
              hint={mode === 'register' ? 'Minimum 8 characters.' : undefined}
            >
              <input
                id="password"
                type="password"
                autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
                required
                minLength={8}
                className="input"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </Field>

            {mode === 'register' && (
              <Field
                label="Role"
                htmlFor="role"
                hint="Only the very first account on an empty database may self-register as Administrator."
              >
                <select id="role" className="input" value={role} onChange={(e) => setRole(e.target.value)}>
                  <option value="reviewer">Reviewer</option>
                  <option value="senior_reviewer">Senior reviewer</option>
                  <option value="adjudicator">Adjudicator</option>
                  <option value="admin">Administrator</option>
                </select>
              </Field>
            )}

            {error && (
              <p className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700" role="alert">
                {error}
              </p>
            )}

            <button type="submit" className="btn-primary w-full" disabled={busy}>
              {busy ? 'Please wait…' : mode === 'login' ? 'Sign in' : 'Create account'}
            </button>
          </form>
        </div>

        <div className="mt-4">
          <InfoNote tone="slate">
            <strong className="font-semibold">Trying the demo?</strong> After signing in as an administrator, open
            <em> Administration → Seed demo data</em> to load a fully populated synthetic evaluation project
            (60 tasks, 5 reviewers with distinct scoring tendencies, gold labels, disagreements and adjudications).
            Demo accounts use the password <code className="font-mono">demo-pass-123</code>.
          </InfoNote>
        </div>
      </div>
    </div>
  )
}
