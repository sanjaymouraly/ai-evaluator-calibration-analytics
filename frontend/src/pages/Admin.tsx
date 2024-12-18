import { useState } from 'react'
import { api } from '../api/client'
import { useAuth } from '../auth'
import {
  Badge,
  Card,
  EmptyState,
  ErrorState,
  Field,
  InfoNote,
  Modal,
  PageHeader,
  Spinner,
  StatCard,
} from '../components/ui'
import { useAsync, useMutation, useTitle } from '../hooks'
import type { AuditEntry, User } from '../types'

interface SystemStats {
  users: number
  projects: number
  tasks: number
  ratings: number
  disagreements: number
  calibration_sessions: number
  rubric_versions: number
  database_url_kind: string
}

interface LLMConfig {
  enabled: boolean
  active: { provider: string; model: string | null; base_url: string | null; api_key?: string } | null
  allow_evaluation_content: boolean
  available_providers: string[]
}

const PROVIDER_HINTS: Record<string, string> = {
  openai: 'Uses https://api.openai.com/v1 — requires an OpenAI API key (billed separately from any ChatGPT subscription).',
  anthropic: 'Uses https://api.anthropic.com/v1 — requires an Anthropic Console API key.',
  openrouter: 'Uses https://openrouter.ai/api/v1 — one key for many models.',
  openai_compatible: 'Any OpenAI-compatible endpoint (Azure, Groq, Together, LiteLLM, vLLM…). Provide the base URL.',
  ollama: 'Local model server, e.g. http://localhost:11434/v1. No API key required; data never leaves the machine.',
  offline: 'Deterministic offline analysis. No credentials, no network calls, no cost.',
}

export default function AdminPage() {
  useTitle('Administration')
  const { user } = useAuth()
  const [tab, setTab] = useState<'overview' | 'users' | 'audit' | 'ai'>('overview')

  if (user?.role !== 'admin') {
    return (
      <>
        <PageHeader title="Administration" backTo="/projects" />
        <InfoNote tone="amber">Administrator role required.</InfoNote>
      </>
    )
  }

  return (
    <>
      <PageHeader title="Administration" subtitle="System health, user management, audit trail, demo data and optional AI assistance." backTo="/projects" />

      <div className="mb-5 flex flex-wrap gap-2" role="tablist" aria-label="Administration sections">
        {(['overview', 'users', 'audit', 'ai'] as const).map((t) => (
          <button
            key={t}
            type="button"
            role="tab"
            aria-selected={tab === t}
            onClick={() => setTab(t)}
            className={`rounded-lg border px-3 py-1.5 text-sm font-medium transition-colors ${
              tab === t ? 'border-brand-500 bg-brand-50 text-brand-800' : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50'
            }`}
          >
            {t === 'ai' ? 'AI assistance' : t[0].toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {tab === 'overview' && <OverviewTab />}
      {tab === 'users' && <UsersTab />}
      {tab === 'audit' && <AuditTab />}
      {tab === 'ai' && <AITab />}
    </>
  )
}

function OverviewTab() {
  const { data: stats, loading, error, reload } = useAsync<SystemStats>(() => api.get('/api/admin/stats'), [])
  const [note, setNote] = useState<string | null>(null)
  const seed = useMutation(() => api.post<Record<string, number>>('/api/admin/seed-demo'))
  const reset = useMutation(() => api.post<{ removed_demo_users: number }>('/api/admin/reset-demo'))

  return (
    <div className="space-y-5">
      {loading && <Spinner label="Loading system stats…" />}
      {error && <ErrorState message={error} onRetry={reload} />}
      {stats && (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <StatCard label="Users" value={stats.users} />
          <StatCard label="Projects" value={stats.projects} />
          <StatCard label="Tasks" value={stats.tasks} />
          <StatCard label="Ratings" value={stats.ratings} />
          <StatCard label="Disagreements" value={stats.disagreements} />
          <StatCard label="Calibration sessions" value={stats.calibration_sessions} />
          <StatCard label="Rubric versions" value={stats.rubric_versions} />
          <StatCard label="Database" value={stats.database_url_kind} />
        </div>
      )}

      <Card
        title="Demonstration data"
        subtitle="A deterministic, fully synthetic evaluation scenario: 60 tasks across 3 models, 5 reviewers with distinct scoring tendencies, 20 expert gold labels, deliberate disagreement patterns, adjudications and a calibration session."
      >
        <InfoNote tone="amber">
          Seeding and resetting only touch demo accounts (<code className="font-mono">@demo.eval-platform.io</code>) and
          the projects they own. <strong className="font-semibold">Real user data is never modified or deleted.</strong>
        </InfoNote>
        <div className="mt-4 flex flex-wrap gap-2">
          <button
            type="button"
            className="btn-primary"
            disabled={seed.loading}
            onClick={async () => {
              setNote(null)
              const res = await seed.run()
              if (res) {
                setNote(
                  `Seeded ${res.tasks} tasks, ${res.ratings} ratings, ${res.disagreements} disagreements, ${res.gold_labeled} gold labels.`,
                )
                reload()
              }
            }}
          >
            {seed.loading ? 'Seeding…' : 'Seed demo data'}
          </button>
          <button
            type="button"
            className="btn-danger"
            disabled={reset.loading}
            onClick={async () => {
              setNote(null)
              const res = await reset.run()
              if (res) {
                setNote(`Removed demo data (${res.removed_demo_users} demo accounts).`)
                reload()
              }
            }}
          >
            {reset.loading ? 'Resetting…' : 'Reset demo data'}
          </button>
        </div>
        {(note || seed.error || reset.error) && (
          <p className={`mt-3 text-sm ${seed.error || reset.error ? 'text-rose-600' : 'text-emerald-700'}`} role="status">
            {seed.error ?? reset.error ?? note}
          </p>
        )}
        <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600">
          <p className="mb-1 font-semibold text-slate-700">Demo accounts (password: demo-pass-123)</p>
          <ul className="grid gap-1 sm:grid-cols-2">
            <li>alice@demo.eval-platform.io — reviewer, well calibrated</li>
            <li>bob@demo.eval-platform.io — reviewer, systematically severe</li>
            <li>carol@demo.eval-platform.io — reviewer, systematically lenient</li>
            <li>dave@demo.eval-platform.io — reviewer, noisy, boundary-confused, drifts over time</li>
            <li>elena@demo.eval-platform.io — senior reviewer, near-expert</li>
            <li>judge@demo.eval-platform.io — adjudicator</li>
          </ul>
        </div>
      </Card>
    </div>
  )
}

function UsersTab() {
  const { data: users, loading, error, reload } = useAsync<User[]>(() => api.get<User[]>('/api/auth/users'), [])
  const { user: me } = useAuth()
  const [q, setQ] = useState('')
  const [target, setTarget] = useState<User | null>(null)
  const [newRole, setNewRole] = useState<string>('reviewer')
  const changeRole = useMutation(() => api.patch<User>(`/api/auth/users/${target?.id}/role`, { role: newRole }))
  const deactivate = useMutation(() => api.post<User>(`/api/auth/users/${target?.id}/deactivate`))

  const visible = (users ?? []).filter(
    (u) => !q || u.email.toLowerCase().includes(q.toLowerCase()) || u.full_name.toLowerCase().includes(q.toLowerCase()),
  )

  return (
    <Card
      title="Users"
      subtitle="Global roles gate administrative powers; project roles gate what a member can do inside a project."
      actions={
        <input className="input w-56" placeholder="Search users…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search users" />
      }
    >
      {loading && <Spinner label="Loading users…" />}
      {error && <ErrorState message={error} onRetry={reload} />}
      {visible.length === 0 && !loading && <EmptyState title="No users match" />}
      {visible.length > 0 && (
        <div className="overflow-x-auto">
          <table className="table-base">
            <thead>
              <tr>
                <th className="th" scope="col">Name</th>
                <th className="th" scope="col">Email</th>
                <th className="th" scope="col">Role</th>
                <th className="th" scope="col">Status</th>
                <th className="th" scope="col">Last login</th>
                <th className="th" scope="col"><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              {visible.map((u) => (
                <tr key={u.id}>
                  <td className="td font-medium text-slate-800">
                    {u.full_name}
                    {u.id === me?.id && <span className="ml-1 text-xs text-slate-400">(you)</span>}
                  </td>
                  <td className="td text-xs">{u.email}</td>
                  <td className="td">
                    <Badge tone={u.role === 'admin' ? 'violet' : u.role === 'adjudicator' ? 'blue' : 'slate'}>{u.role}</Badge>
                  </td>
                  <td className="td">
                    <Badge tone={u.is_active ? 'green' : 'rose'}>{u.is_active ? 'active' : 'deactivated'}</Badge>
                  </td>
                  <td className="td text-xs text-slate-500">
                    {u.created_at ? new Date(u.created_at).toLocaleDateString() : '—'}
                  </td>
                  <td className="td">
                    {u.id !== me?.id && (
                      <button
                        type="button"
                        className="btn-secondary px-2.5 py-1 text-xs"
                        onClick={() => {
                          setTarget(u)
                          setNewRole(u.role)
                        }}
                      >
                        Manage
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Modal
        open={target !== null}
        title={`Manage ${target?.full_name ?? ''}`}
        onClose={() => setTarget(null)}
        footer={
          <>
            <button type="button" className="btn-secondary" onClick={() => setTarget(null)}>
              Close
            </button>
            <button
              type="button"
              className="btn-danger"
              disabled={deactivate.loading || !target?.is_active}
              onClick={async () => {
                const res = await deactivate.run()
                if (res) {
                  setTarget(null)
                  reload()
                }
              }}
            >
              Deactivate account
            </button>
            <button
              type="button"
              className="btn-primary"
              disabled={changeRole.loading}
              onClick={async () => {
                const res = await changeRole.run()
                if (res) {
                  setTarget(null)
                  reload()
                }
              }}
            >
              Save role
            </button>
          </>
        }
      >
        <Field label="Global role" htmlFor="u-role" hint="Administrators manage users, demo data and AI provider settings.">
          <select id="u-role" className="input" value={newRole} onChange={(e) => setNewRole(e.target.value)}>
            <option value="reviewer">Reviewer</option>
            <option value="senior_reviewer">Senior reviewer</option>
            <option value="adjudicator">Adjudicator</option>
            <option value="admin">Administrator</option>
          </select>
        </Field>
        {(changeRole.error || deactivate.error) && (
          <p className="mt-3 text-sm text-rose-600" role="alert">
            {changeRole.error ?? deactivate.error}
          </p>
        )}
      </Modal>
    </Card>
  )
}

function AuditTab() {
  const { data: logs, loading, error, reload } = useAsync<AuditEntry[]>(() => api.get<AuditEntry[]>('/api/admin/audit-log?limit=200'), [])

  return (
    <Card
      title="Audit log"
      subtitle="Consequential actions: project and rubric changes, submissions, corrections, adjudications, membership and demo data operations."
      actions={<button type="button" className="btn-secondary" onClick={reload}>Refresh</button>}
    >
      {loading && <Spinner label="Loading audit log…" />}
      {error && <ErrorState message={error} onRetry={reload} />}
      {logs && logs.length === 0 && <EmptyState title="No audited actions yet" />}
      {logs && logs.length > 0 && (
        <div className="max-h-[70vh] overflow-auto">
          <table className="table-base">
            <thead>
              <tr>
                <th className="th" scope="col">When</th>
                <th className="th" scope="col">Action</th>
                <th className="th" scope="col">Entity</th>
                <th className="th" scope="col">Actor</th>
                <th className="th" scope="col">Details</th>
              </tr>
            </thead>
            <tbody>
              {logs.map((entry) => (
                <tr key={entry.id}>
                  <td className="td whitespace-nowrap text-xs text-slate-500">{new Date(entry.created_at).toLocaleString()}</td>
                  <td className="td">
                    <Badge tone="slate">{entry.action}</Badge>
                  </td>
                  <td className="td font-mono text-[11px] text-slate-500">
                    {entry.entity_type ?? '—'}
                    {entry.entity_id ? ` · ${entry.entity_id.slice(0, 8)}` : ''}
                  </td>
                  <td className="td font-mono text-[11px] text-slate-500">{entry.user_id?.slice(0, 8) ?? 'system'}</td>
                  <td className="td max-w-md truncate font-mono text-[11px] text-slate-500">
                    {entry.details ? JSON.stringify(entry.details) : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}

function AITab() {
  const { data: config, loading, error, reload } = useAsync<LLMConfig>(() => api.get<LLMConfig>('/api/llm/config'), [])
  const [provider, setProvider] = useState('offline')
  const [baseUrl, setBaseUrl] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [model, setModel] = useState('')
  const [label, setLabel] = useState('')
  const [testResult, setTestResult] = useState<Record<string, unknown> | null>(null)
  const [note, setNote] = useState<string | null>(null)

  const save = useMutation(() =>
    api.post('/api/llm/config', {
      provider,
      base_url: baseUrl || null,
      api_key: apiKey || null,
      model: model || null,
      label: label || null,
    }),
  )
  const test = useMutation(() => api.get<Record<string, unknown>>('/api/llm/test'))

  if (loading) return <Spinner label="Loading AI configuration…" />
  if (error) return <ErrorState message={error} onRetry={reload} />
  if (!config) return null

  return (
    <div className="space-y-5">
      <Card title="Optional AI assistance" subtitle="The platform is fully functional without any AI provider. Everything below is opt-in.">
        <div className="space-y-3">
          <InfoNote tone="slate">
            <strong className="font-semibold">Status:</strong>{' '}
            {config.active ? (
              <>
                provider <Badge tone="blue">{config.active.provider}</Badge>{' '}
                {config.active.model && <Badge tone="slate">{config.active.model}</Badge>}
                {config.active.api_key && (
                  <span className="ml-2 font-mono text-xs text-slate-500">key {config.active.api_key}</span>
                )}
              </>
            ) : (
              <Badge tone="amber">not configured — offline deterministic mode</Badge>
            )}
          </InfoNote>
          <InfoNote tone="amber">
            <strong className="font-semibold">Billing note.</strong> OpenAI API usage is billed separately from a
            ChatGPT Plus/Pro subscription — a ChatGPT plan does <em>not</em> grant API access. Anthropic and OpenRouter
            have their own billing. Use the <code className="font-mono">offline</code> provider (or Ollama locally) for
            zero cost.
          </InfoNote>
          <InfoNote>
            <strong className="font-semibold">Data protection.</strong> Evaluation content (prompts, responses,
            rationales) is only sent to a provider when the backend is explicitly configured with{' '}
            <code className="font-mono">LLM_ENABLED=true</code> and{' '}
            <code className="font-mono">LLM_ALLOW_EVALUATION_CONTENT=true</code>. AI outputs are always labelled
            AI-generated and never change a rubric or decision without human approval. API keys are encrypted at rest,
            masked in the UI and never written to logs.
          </InfoNote>
        </div>
      </Card>

      <Card title="Provider configuration">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Provider" htmlFor="ai-provider">
            <select
              id="ai-provider"
              className="input"
              value={provider}
              onChange={(e) => {
                setProvider(e.target.value)
                setTestResult(null)
              }}
            >
              {config.available_providers.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Label (optional)" htmlFor="ai-label">
            <input id="ai-label" className="input" value={label} onChange={(e) => setLabel(e.target.value)} placeholder="e.g. Team Claude account" />
          </Field>
          <div className="sm:col-span-2">
            <InfoNote tone="slate">{PROVIDER_HINTS[provider]}</InfoNote>
          </div>
          {provider !== 'offline' && (
            <>
              <Field
                label="Base URL"
                htmlFor="ai-base"
                hint={provider === 'ollama' ? 'e.g. http://localhost:11434/v1' : 'Leave blank to use the provider default.'}
              >
                <input id="ai-base" className="input font-mono text-xs" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://api.example.com/v1" />
              </Field>
              <Field label="Model" htmlFor="ai-model" hint="e.g. gpt-4o-mini, claude-3-5-haiku-20241022, llama3.1">
                <input id="ai-model" className="input font-mono text-xs" value={model} onChange={(e) => setModel(e.target.value)} />
              </Field>
              <div className="sm:col-span-2">
                <Field
                  label="API key"
                  htmlFor="ai-key"
                  hint="Stored encrypted (Fernet) and masked everywhere. Leave blank to keep the existing key."
                >
                  <input
                    id="ai-key"
                    type="password"
                    autoComplete="off"
                    className="input font-mono text-xs"
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                    placeholder="••••••••••••••••"
                  />
                </Field>
              </div>
            </>
          )}
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          <button
            type="button"
            className="btn-primary"
            disabled={save.loading}
            onClick={async () => {
              setNote(null)
              const res = await save.run()
              if (res) {
                setNote('Provider configuration saved. Enable LLM_ENABLED on the backend to allow live calls.')
                setApiKey('')
                reload()
              }
            }}
          >
            {save.loading ? 'Saving…' : 'Save configuration'}
          </button>
          <button
            type="button"
            className="btn-secondary"
            disabled={test.loading}
            onClick={async () => {
              setTestResult(null)
              const res = await test.run()
              if (res) setTestResult(res)
            }}
          >
            {test.loading ? 'Testing…' : 'Test connection'}
          </button>
        </div>

        {(note || save.error) && (
          <p className={`mt-3 text-sm ${save.error ? 'text-rose-600' : 'text-emerald-700'}`} role="status">
            {save.error ?? note}
          </p>
        )}
        {testResult && (
          <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm">
            <p className="font-medium text-slate-800">
              Connection test:{' '}
              <Badge tone={testResult.ok ? 'green' : 'rose'}>{testResult.ok ? 'ok' : 'failed'}</Badge>
            </p>
            <p className="mt-1 text-xs text-slate-600">{String(testResult.detail ?? '')}</p>
            {!config.enabled && (
              <p className="mt-2 text-xs text-amber-700">
                Live calls are disabled server-side (<code className="font-mono">LLM_ENABLED=false</code>). Offline
                deterministic analysis is used until an administrator enables it in the environment.
              </p>
            )}
          </div>
        )}
        {test.error && <p className="mt-2 text-sm text-rose-600">{test.error}</p>}
      </Card>

      <UsageLogCard />
    </div>
  )
}

function UsageLogCard() {
  const { data: logs, loading } = useAsync<
    Array<{ id: string; provider: string; model: string | null; prompt_tokens: number; completion_tokens: number; estimated_cost_usd: number; status: string; created_at: string }>
  >(() => api.get('/api/llm/usage-logs'), [])

  const total = (logs ?? []).reduce((sum, l) => sum + (l.estimated_cost_usd ?? 0), 0)

  return (
    <Card title="Usage & cost" subtitle={`Estimated spend across ${(logs ?? []).length} logged calls.`}>
      {loading && <Spinner label="Loading usage…" />}
      <div className="mb-3">
        <StatCard label="Estimated cost" value={`$${total.toFixed(4)}`} hint="Based on published per-token list prices" />
      </div>
      {(!logs || logs.length === 0) && <EmptyState title="No AI calls logged" body="Offline deterministic analysis is not billed and not logged as usage." />}
      {logs && logs.length > 0 && (
        <div className="max-h-72 overflow-auto">
          <table className="table-base">
            <thead>
              <tr>
                <th className="th" scope="col">When</th>
                <th className="th" scope="col">Provider</th>
                <th className="th" scope="col">Model</th>
                <th className="th text-right" scope="col">Tokens in/out</th>
                <th className="th text-right" scope="col">Cost</th>
                <th className="th" scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              {logs.map((l) => (
                <tr key={l.id}>
                  <td className="td whitespace-nowrap text-xs text-slate-500">{new Date(l.created_at).toLocaleString()}</td>
                  <td className="td">{l.provider}</td>
                  <td className="td font-mono text-xs">{l.model ?? '—'}</td>
                  <td className="td text-right tabular-nums text-xs">
                    {l.prompt_tokens} / {l.completion_tokens}
                  </td>
                  <td className="td text-right tabular-nums text-xs">${l.estimated_cost_usd.toFixed(5)}</td>
                  <td className="td">
                    <Badge tone={l.status === 'ok' ? 'green' : l.status === 'skipped_offline' ? 'slate' : 'rose'}>{l.status}</Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}
