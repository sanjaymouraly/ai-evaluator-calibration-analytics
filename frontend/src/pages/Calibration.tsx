import { useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import { api } from '../api/client'
import { useAuth } from '../auth'
import { GroupedBarChart } from '../components/charts'
import {
  Badge,
  Card,
  EmptyState,
  ErrorState,
  Field,
  InfoNote,
  MetricValue,
  Modal,
  PageHeader,
  Spinner,
  StatCard,
} from '../components/ui'
import { useAsync, useMutation, useTitle } from '../hooks'
import type { CalibrationAttempt, CalibrationSession, Task } from '../types'

interface SessionSummary {
  n_reviewers: number
  by_reviewer: Record<string, { pre?: Partial<CalibrationAttempt>; post?: Partial<CalibrationAttempt> }>
  pre_mean_kappa: number | null
  post_mean_kappa: number | null
  pre_mean_accuracy: number | null
  post_mean_accuracy: number | null
}

export default function CalibrationPage() {
  const { projectId = '' } = useParams()
  useTitle('Calibration')
  const { user } = useAuth()
  const [selected, setSelected] = useState<string | null>(null)
  const [showCreate, setShowCreate] = useState(false)
  const [showAssess, setShowAssess] = useState(false)

  const { data: sessions, loading, error, reload } = useAsync<CalibrationSession[]>(
    () => api.get<CalibrationSession[]>(`/api/projects/${projectId}/calibration/sessions`),
    [projectId],
  )

  const active = selected ?? sessions?.[0]?.id ?? null

  return (
    <>
      <PageHeader
        title="Reviewer calibration"
        subtitle="Measure reviewer accuracy against expert-approved gold labels, give feedback, and track improvement from pre- to post-calibration."
        backTo={`/projects/${projectId}`}
        actions={
          <>
            <button type="button" className="btn-secondary" onClick={() => setShowAssess(true)} disabled={!active}>
              Take assessment
            </button>
            {user?.role === 'admin' && (
              <button type="button" className="btn-primary" onClick={() => setShowCreate(true)}>
                + New session
              </button>
            )}
          </>
        }
      />

      <InfoNote>
        <strong className="font-semibold">Calibration ≠ agreement.</strong> These numbers measure how closely each
        reviewer matches an <em>expert-approved reference label</em>. Inter-reviewer consistency is reported on the
        dashboard; severity/leniency bias is reported separately. Calibration is a quality-improvement loop, not a
        ranking tool — always consider task mix before comparing reviewers.
      </InfoNote>

      {loading && <Spinner label="Loading calibration sessions…" />}
      {error && <ErrorState message={error} onRetry={reload} />}

      {sessions && sessions.length === 0 && (
        <div className="mt-5">
          <EmptyState
            title="No calibration sessions yet"
            body="Approve gold labels on a handful of tasks, then create a session to assess reviewers against them."
            action={
              user?.role === 'admin' ? (
                <button type="button" className="btn-primary" onClick={() => setShowCreate(true)}>
                  + New session
                </button>
              ) : undefined
            }
          />
        </div>
      )}

      {sessions && sessions.length > 0 && (
        <>
          <div className="mt-5 flex flex-wrap gap-2">
            {sessions.map((s) => (
              <button
                key={s.id}
                type="button"
                onClick={() => setSelected(s.id)}
                className={`rounded-lg border px-3 py-2 text-sm transition-colors ${
                  active === s.id ? 'border-brand-400 bg-brand-50 text-brand-900' : 'border-slate-200 bg-white text-slate-700 hover:bg-slate-50'
                }`}
              >
                <span className="font-medium">{s.name}</span>
                <span className="ml-2 text-xs text-slate-500">{new Date(s.created_at).toLocaleDateString()}</span>
              </button>
            ))}
          </div>

          {active && (
            <SessionDetail
              key={active}
              projectId={projectId}
              session={sessions.find((s) => s.id === active) ?? sessions[0]}
            />
          )}
        </>
      )}

      <CreateSessionModal
        open={showCreate}
        projectId={projectId}
        onClose={() => setShowCreate(false)}
        onCreated={() => {
          reload()
          setShowCreate(false)
        }}
      />
      {active && (
        <AssessmentModal
          open={showAssess}
          projectId={projectId}
          sessionId={active}
          onClose={() => setShowAssess(false)}
          onDone={() => {
            reload()
            setShowAssess(false)
          }}
        />
      )}
    </>
  )
}

function SessionDetail({ projectId, session }: { projectId: string; session: CalibrationSession }) {
  const { data: summary, loading, error, reload } = useAsync<SessionSummary>(
    () => api.get<SessionSummary>(`/api/projects/${projectId}/calibration/sessions/${session.id}/summary`),
    [projectId, session.id],
  )
  const { data: progress } = useAsync<{ mine: Record<string, unknown>; all: CalibrationAttempt[] }>(
    () => api.get(`/api/projects/${projectId}/calibration/sessions/${session.id}/progress`),
    [projectId, session.id],
  )
  const { data: users } = useAsync<Array<{ id: string; full_name: string }>>(
    () =>
      api
        .get<Array<{ id: string; full_name: string }>>('/api/auth/users')
        .catch(() => [] as Array<{ id: string; full_name: string }>),
    [],
  )

  const nameOf = useMemo(() => {
    const map = new Map<string, string>()
    users?.forEach((u) => map.set(u.id, u.full_name))
    return (id: string) => map.get(id) ?? id.slice(0, 8)
  }, [users])

  if (loading) return <Spinner label="Computing calibration results…" />
  if (error) return <ErrorState message={error} onRetry={reload} />
  if (!summary) return null

  const chartRows = Object.entries(summary.by_reviewer).map(([rid, phases]) => ({
    name: nameOf(rid),
    pre: phases.pre?.accuracy != null ? Number((phases.pre.accuracy * 100).toFixed(1)) : null,
    post: phases.post?.accuracy != null ? Number((phases.post.accuracy * 100).toFixed(1)) : null,
  }))

  const improved =
    summary.pre_mean_accuracy !== null && summary.post_mean_accuracy !== null
      ? summary.post_mean_accuracy - summary.pre_mean_accuracy
      : null

  return (
    <div className="mt-5 space-y-5">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Reviewers assessed" value={summary.n_reviewers} />
        <StatCard
          label="Mean pre-accuracy"
          value={<MetricValue value={summary.pre_mean_accuracy === null ? null : summary.pre_mean_accuracy * 100} digits={1} suffix="%" />}
        />
        <StatCard
          label="Mean post-accuracy"
          value={<MetricValue value={summary.post_mean_accuracy === null ? null : summary.post_mean_accuracy * 100} digits={1} suffix="%" />}
          tone={improved !== null && improved > 0 ? 'good' : 'neutral'}
        />
        <StatCard
          label="Improvement"
          value={improved === null ? '—' : `${improved >= 0 ? '+' : ''}${(improved * 100).toFixed(1)} pp`}
          tone={improved !== null && improved > 0 ? 'good' : improved !== null && improved < 0 ? 'bad' : 'neutral'}
          hint="post minus pre"
        />
      </div>

      <Card
        title="Pass thresholds"
        subtitle={`Accuracy ≥ ${(session.pass_threshold_accuracy * 100).toFixed(0)}% · Cohen's κ ≥ ${session.pass_threshold_kappa.toFixed(2)}`}
      >
        <InfoNote tone="slate">
          Thresholds are configurable per session by administrators. A reviewer who does not pass is not penalised
          automatically — the outcome triggers feedback and, where useful, a post-calibration reassessment.
        </InfoNote>
      </Card>

      {chartRows.some((r) => r.pre !== null || r.post !== null) && (
        <Card title="Accuracy by reviewer" subtitle="Pre-calibration versus post-calibration (% match with gold labels).">
          <GroupedBarChart data={chartRows} keys={['pre', 'post']} height={260} />
        </Card>
      )}

      <Card title="Attempts" subtitle="Every attempt is retained — calibration progress is a trend, not a snapshot.">
        {(!progress || progress.all.length === 0) && <EmptyState title="No attempts recorded yet" />}
        {progress && progress.all.length > 0 && (
          <div className="overflow-x-auto">
            <table className="table-base">
              <thead>
                <tr>
                  <th className="th" scope="col">Reviewer</th>
                  <th className="th" scope="col">Phase</th>
                  <th className="th text-right" scope="col">Accuracy</th>
                  <th className="th text-right" scope="col">Cohen's κ</th>
                  <th className="th text-right" scope="col">MAE</th>
                  <th className="th" scope="col">Result</th>
                  <th className="th text-right" scope="col">Divergences</th>
                  <th className="th" scope="col">Completed</th>
                </tr>
              </thead>
              <tbody>
                {progress.all.map((a) => (
                  <tr key={a.id}>
                    <td className="td font-medium text-slate-800">{nameOf(a.reviewer_id)}</td>
                    <td className="td">
                      <Badge tone={a.phase === 'pre' ? 'slate' : 'blue'}>{a.phase}</Badge>
                    </td>
                    <td className="td text-right">
                      <MetricValue value={a.accuracy === null ? null : a.accuracy * 100} digits={1} suffix="%" />
                    </td>
                    <td className="td text-right">
                      <MetricValue value={a.kappa} />
                    </td>
                    <td className="td text-right">
                      <MetricValue value={a.mae} digits={2} />
                    </td>
                    <td className="td">
                      {a.passed === null ? (
                        <Badge tone="slate">n/a</Badge>
                      ) : a.passed ? (
                        <Badge tone="green">passed</Badge>
                      ) : (
                        <Badge tone="rose">needs feedback</Badge>
                      )}
                    </td>
                    <td className="td text-right tabular-nums">{a.feedback?.items?.length ?? 0}</td>
                    <td className="td text-xs text-slate-500">{new Date(a.completed_at).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  )
}

function CreateSessionModal({
  open,
  projectId,
  onClose,
  onCreated,
}: {
  open: boolean
  projectId: string
  onClose: () => void
  onCreated: () => void
}) {
  const { data: tasks } = useAsync<Task[]>(
    () => (open ? api.get<Task[]>(`/api/projects/${projectId}/tasks?limit=200`) : Promise.resolve([])),
    [open, projectId],
  )
  const goldTasks = (tasks ?? []).filter((t) => t.gold_label)
  const [name, setName] = useState('')
  const [selected, setSelected] = useState<string[]>([])
  const [kappa, setKappa] = useState(0.7)
  const [accuracy, setAccuracy] = useState(0.8)
  const create = useMutation((payload: unknown) => api.post(`/api/projects/${projectId}/calibration/sessions`, payload))

  return (
    <Modal
      open={open}
      title="New calibration session"
      onClose={onClose}
      wide
      footer={
        <>
          <button type="button" className="btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className="btn-primary"
            disabled={create.loading || !name.trim() || selected.length < 2}
            onClick={async () => {
              const res = await create.run({
                name,
                task_ids: selected,
                pass_threshold_kappa: kappa,
                pass_threshold_accuracy: accuracy,
              })
              if (res) onCreated()
            }}
          >
            {create.loading ? 'Creating…' : 'Create session'}
          </button>
        </>
      }
    >
      {goldTasks.length < 2 ? (
        <InfoNote tone="amber">
          Calibration needs at least <strong className="font-semibold">two tasks with expert-approved gold labels</strong>.
          Set gold labels on the Tasks &amp; data page first. ({goldTasks.length} currently labelled.)
        </InfoNote>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-3">
            <div className="sm:col-span-3">
              <Field label="Session name" htmlFor="cs-name">
                <input id="cs-name" className="input" value={name} onChange={(e) => setName(e.target.value)} />
              </Field>
            </div>
            <Field label="Pass threshold — accuracy" htmlFor="cs-acc">
              <input
                id="cs-acc"
                type="number"
                step={0.05}
                min={0}
                max={1}
                className="input"
                value={accuracy}
                onChange={(e) => setAccuracy(Number(e.target.value))}
              />
            </Field>
            <Field label="Pass threshold — Cohen's κ" htmlFor="cs-kappa">
              <input
                id="cs-kappa"
                type="number"
                step={0.05}
                min={0}
                max={1}
                className="input"
                value={kappa}
                onChange={(e) => setKappa(Number(e.target.value))}
              />
            </Field>
            <Field label="Selected items" htmlFor="cs-count">
              <input id="cs-count" className="input" value={`${selected.length} of ${goldTasks.length}`} readOnly />
            </Field>
          </div>

          <div className="mt-4 flex gap-2">
            <button type="button" className="btn-secondary" onClick={() => setSelected(goldTasks.map((t) => t.id))}>
              Select all
            </button>
            <button type="button" className="btn-ghost" onClick={() => setSelected([])}>
              Clear
            </button>
          </div>

          <ul className="mt-3 max-h-64 space-y-1 overflow-y-auto">
            {goldTasks.map((t) => (
              <li key={t.id}>
                <label className="flex items-start gap-2 rounded-lg border border-slate-200 p-2 text-sm">
                  <input
                    type="checkbox"
                    className="mt-0.5 h-4 w-4 rounded border-slate-300"
                    checked={selected.includes(t.id)}
                    onChange={(e) =>
                      setSelected((s) => (e.target.checked ? [...s, t.id] : s.filter((x) => x !== t.id)))
                    }
                  />
                  <span className="min-w-0">
                    <span className="font-mono text-[11px] text-slate-400">{t.external_id ?? t.id.slice(0, 8)}</span>
                    <span className="block truncate text-slate-700">{t.prompt}</span>
                  </span>
                </label>
              </li>
            ))}
          </ul>
        </>
      )}
      {create.error && <p className="mt-3 text-sm text-rose-600">{create.error}</p>}
    </Modal>
  )
}

function AssessmentModal({
  open,
  projectId,
  sessionId,
  onClose,
  onDone,
}: {
  open: boolean
  projectId: string
  sessionId: string
  onClose: () => void
  onDone: () => void
}) {
  const { data: session } = useAsync<CalibrationSession>(
    () => (open ? api.get<CalibrationSession[]>(`/api/projects/${projectId}/calibration/sessions`).then((s) => s.find((x) => x.id === sessionId)!) : Promise.resolve(null as unknown as CalibrationSession)),
    [open, projectId, sessionId],
  )
  const { data: tasks } = useAsync<Task[]>(
    () => (open ? api.get<Task[]>(`/api/projects/${projectId}/tasks?limit=200`) : Promise.resolve([])),
    [open, projectId],
  )
  const { data: rubrics } = useAsync<Array<{ id: string; status: string; categories: Array<Record<string, unknown>> }>>(
    () => (open ? api.get(`/api/projects/${projectId}/rubrics`) : Promise.resolve([])),
    [open, projectId],
  )

  const goldTasks = useMemo(() => (tasks ?? []).filter((t) => t.gold_label), [tasks])
  const activeRubric = (rubrics ?? []).find((r) => r.status === 'active') ?? rubrics?.[0]
  const categories = (activeRubric?.categories ?? []) as Array<{
    key: string
    name: string
    scale_type: string
    min_value: number | null
    options: Array<{ value: number | string; label: string }> | null
  }>

  const [phase, setPhase] = useState<'pre' | 'post'>('pre')
  const [answers, setAnswers] = useState<Record<string, Record<string, number | string>>>({})
  const [result, setResult] = useState<CalibrationAttempt | null>(null)
  const submit = useMutation(() =>
    api.post<CalibrationAttempt>(`/api/projects/${projectId}/calibration/assess`, {
      session_id: sessionId,
      phase,
      item_scores: answers,
    }),
  )

  if (!open) return null

  return (
    <Modal
      open
      title="Calibration assessment"
      onClose={onClose}
      wide
      footer={
        result ? (
          <button type="button" className="btn-primary" onClick={onDone}>
            Done
          </button>
        ) : (
          <>
            <button type="button" className="btn-secondary" onClick={onClose}>
              Cancel
            </button>
            <button
              type="button"
              className="btn-primary"
              disabled={submit.loading || Object.keys(answers).length === 0}
              onClick={async () => {
                const res = await submit.run()
                if (res) setResult(res)
              }}
            >
              {submit.loading ? 'Scoring…' : 'Submit assessment'}
            </button>
          </>
        )
      }
    >
      {result ? (
        <div className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-4">
            <StatCard
              label="Accuracy"
              value={<MetricValue value={result.accuracy === null ? null : result.accuracy * 100} digits={1} suffix="%" />}
              tone={result.passed ? 'good' : 'bad'}
            />
            <StatCard label="Cohen's κ" value={<MetricValue value={result.kappa} />} />
            <StatCard label="MAE" value={<MetricValue value={result.mae} digits={2} />} />
            <StatCard label="Result" value={result.passed ? 'Passed' : 'Needs feedback'} tone={result.passed ? 'good' : 'warn'} />
          </div>
          {result.feedback?.items && result.feedback.items.length > 0 && (
            <Card title="Where you diverged from the expert label" subtitle="Use this feedback to re-align before your next assessment.">
              <ul className="space-y-2">
                {result.feedback.items.map((item, i) => (
                  <li key={i} className="rounded-lg border border-amber-200 bg-amber-50 p-2.5 text-sm">
                    <p className="font-medium text-amber-900">
                      {String(item.category)} · item {String(item.task_id).slice(0, 8)}
                    </p>
                    <p className="text-amber-800">
                      Your score <strong>{String(item.your_score)}</strong> · expert label{' '}
                      <strong>{String(item.gold_score)}</strong>
                    </p>
                    <p className="mt-0.5 text-xs text-amber-700">{String(item.guidance)}</p>
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </div>
      ) : (
        <div className="space-y-4">
          <InfoNote>
            Score each item independently. Gold labels are hidden until you submit — this is an assessment, not a
            training exercise. Session thresholds: accuracy ≥{' '}
            {((session?.pass_threshold_accuracy ?? 0.8) * 100).toFixed(0)}%, κ ≥{' '}
            {(session?.pass_threshold_kappa ?? 0.7).toFixed(2)}.
          </InfoNote>

          <Field label="Phase" htmlFor="phase">
            <select
              id="phase"
              className="input max-w-xs"
              value={phase}
              onChange={(e) => setPhase(e.target.value as 'pre' | 'post')}
            >
              <option value="pre">Pre-calibration</option>
              <option value="post">Post-calibration (reassessment)</option>
            </select>
          </Field>

          {goldTasks.length === 0 && <EmptyState title="No gold-labelled items in this project" />}

          {goldTasks.map((t) => (
            <div key={t.id} className="rounded-lg border border-slate-200 p-3">
              <p className="mb-1 font-mono text-[11px] text-slate-400">{t.external_id ?? t.id.slice(0, 8)}</p>
              <p className="mb-2 text-sm font-medium text-slate-800">{t.prompt}</p>
              <p className="mb-3 max-h-32 overflow-y-auto whitespace-pre-wrap rounded bg-slate-50 p-2 text-xs text-slate-600">
                {t.response_a}
              </p>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {categories.map((c) => {
                  const current = answers[t.id]?.[c.key]
                  return (
                    <Field key={c.key} label={c.name} htmlFor={`${t.id}-${c.key}`}>
                      {c.scale_type === 'categorical' ? (
                        <select
                          id={`${t.id}-${c.key}`}
                          className="input"
                          value={current === undefined ? '' : String(current)}
                          onChange={(e) =>
                            setAnswers((a) => ({ ...a, [t.id]: { ...(a[t.id] ?? {}), [c.key]: e.target.value } }))
                          }
                        >
                          <option value="" disabled>
                            Select…
                          </option>
                          {(c.options ?? []).map((o) => (
                            <option key={String(o.value)} value={String(o.value)}>
                              {o.label}
                            </option>
                          ))}
                        </select>
                      ) : (
                        <input
                          id={`${t.id}-${c.key}`}
                          type="number"
                          step={c.scale_type === 'ordinal' ? 1 : 0.1}
                          min={c.min_value ?? undefined}
                          className="input"
                          value={current === undefined ? '' : Number(current)}
                          onChange={(e) =>
                            setAnswers((a) => ({
                              ...a,
                              [t.id]: { ...(a[t.id] ?? {}), [c.key]: Number(e.target.value) },
                            }))
                          }
                        />
                      )}
                    </Field>
                  )
                })}
              </div>
            </div>
          ))}

          {submit.error && (
            <p className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700" role="alert">
              {submit.error}
            </p>
          )}
        </div>
      )}
    </Modal>
  )
}
