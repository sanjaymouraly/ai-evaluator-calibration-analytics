import { useEffect, useState } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import { useAuth, can } from '../auth'
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
import type { Adjudication, AdjudicationDetail, Task } from '../types'

const STATUS_TONE: Record<string, string> = {
  proposed: 'amber',
  final: 'green',
  reopened: 'violet',
}

export default function AdjudicationPage() {
  const { projectId = '' } = useParams()
  const [params] = useSearchParams()
  useTitle('Adjudication')
  const { user } = useAuth()
  const [selected, setSelected] = useState<string | null>(params.get('adjudication'))
  const preselectTask = params.get('task')
  const preselectDisagreement = params.get('disagreement')

  const { data: adjudications, loading, error, reload } = useAsync<Adjudication[]>(
    () => api.get<Adjudication[]>(`/api/projects/${projectId}/adjudications`),
    [projectId],
  )
  const { data: openDisagreements } = useAsync<
    Array<{ id: string; task_id: string; category_key: string | null; kind: string; severity_class: string; priority_score: number }>
  >(() => api.get(`/api/projects/${projectId}/disagreements?status=open&limit=100`), [projectId, adjudications])
  const { data: tasks } = useAsync<Task[]>(() => api.get<Task[]>(`/api/projects/${projectId}/tasks?limit=200`), [projectId])

  const create = useMutation((taskId: string, disagreementId: string | null) =>
    api.post<Adjudication>(
      `/api/projects/${projectId}/adjudications?task_id=${taskId}${disagreementId ? `&disagreement_id=${disagreementId}` : ''}`,
    ),
  )

  const taskLabel = (id: string) => {
    const t = tasks?.find((x) => x.id === id)
    return t?.external_id ?? id.slice(0, 8)
  }

  // Auto-create an adjudication when arriving from the disagreement queue.
  useEffect(() => {
    if (!preselectTask || selected) return
    if (create.loading) return
    void (async () => {
      const res = await create.run(preselectTask, preselectDisagreement)
      if (res) {
        setSelected(res.id)
        reload()
      }
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preselectTask, preselectDisagreement, selected])

  const finalCount = adjudications?.filter((a) => a.status === 'final').length ?? 0
  const proposedCount = adjudications?.filter((a) => a.status === 'proposed').length ?? 0
  const escalatedCount = adjudications?.filter((a) => a.escalated).length ?? 0

  return (
    <>
      <PageHeader
        title="Adjudication workspace"
        subtitle="Resolve disagreements with a documented, authoritative decision. Original reviewer scores are always preserved separately."
        backTo={`/projects/${projectId}`}
      />

      <div className="mb-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Adjudications" value={adjudications?.length ?? 0} />
        <StatCard label="Finalised" value={finalCount} tone="good" />
        <StatCard label="Awaiting decision" value={proposedCount} tone={proposedCount ? 'warn' : 'neutral'} />
        <StatCard label="Escalated" value={escalatedCount} tone={escalatedCount ? 'bad' : 'neutral'} />
      </div>

      {!can.adjudicate(user) && (
        <div className="mb-5">
          <InfoNote tone="amber">
            You are signed in as a reviewer. You can read adjudication outcomes, but only adjudicators, senior
            reviewers and administrators can record decisions.
          </InfoNote>
        </div>
      )}

      <div className="grid gap-5 lg:grid-cols-[340px_minmax(0,1fr)]">
        <div className="space-y-5">
          <Card title="Open disagreements" subtitle="Start an adjudication from the highest-priority case.">
            {!openDisagreements || openDisagreements.length === 0 ? (
              <EmptyState title="No open disagreements" body="Everything detected has been resolved or dismissed." />
            ) : (
              <ul className="max-h-72 space-y-1.5 overflow-y-auto pr-1">
                {openDisagreements.map((d) => (
                  <li key={d.id}>
                    <button
                      type="button"
                      className="w-full rounded-lg border border-slate-200 p-2.5 text-left transition-colors hover:border-brand-300 hover:bg-brand-50"
                      disabled={create.loading}
                      onClick={async () => {
                        const res = await create.run(d.task_id, d.id)
                        if (res) {
                          setSelected(res.id)
                          reload()
                        }
                      }}
                    >
                      <div className="mb-1 flex items-center justify-between gap-2">
                        <Badge tone={d.severity_class === 'critical' ? 'rose' : d.severity_class === 'major' ? 'amber' : 'slate'}>
                          {d.severity_class}
                        </Badge>
                        <span className="text-[11px] tabular-nums text-slate-500">p={d.priority_score.toFixed(2)}</span>
                      </div>
                      <p className="text-xs font-medium text-slate-800">{d.category_key ?? 'general'}</p>
                      <p className="text-[11px] text-slate-500">
                        {d.kind.replace(/_/g, ' ')} · item {taskLabel(d.task_id)}
                      </p>
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {create.error && <p className="mt-2 text-xs text-rose-600">{create.error}</p>}
          </Card>

          <Card title="Adjudication history">
            {loading && <Spinner label="Loading…" />}
            {error && <ErrorState message={error} onRetry={reload} />}
            {adjudications && adjudications.length === 0 && <EmptyState title="No adjudications yet" />}
            <ul className="max-h-96 space-y-1.5 overflow-y-auto pr-1">
              {adjudications?.map((a) => (
                <li key={a.id}>
                  <button
                    type="button"
                    onClick={() => setSelected(a.id)}
                    className={`w-full rounded-lg border p-2.5 text-left transition-colors ${
                      selected === a.id ? 'border-brand-300 bg-brand-50' : 'border-slate-200 hover:bg-slate-50'
                    }`}
                  >
                    <div className="mb-1 flex items-center justify-between gap-2">
                      <Badge tone={STATUS_TONE[a.status] ?? 'slate'}>{a.status}</Badge>
                      {a.escalated && <Badge tone="rose">escalated</Badge>}
                    </div>
                    <p className="text-xs text-slate-700">item {taskLabel(a.task_id)}</p>
                    <p className="text-[11px] text-slate-400">
                      {a.strategy} · {new Date(a.created_at).toLocaleDateString()}
                    </p>
                  </button>
                </li>
              ))}
            </ul>
          </Card>
        </div>

        <div>
          {selected ? (
            <AdjudicationPanel key={selected} projectId={projectId} adjudicationId={selected} onChanged={reload} />
          ) : (
            <EmptyState
              title="Select a case"
              body="Pick an open disagreement to start, or an existing adjudication to review its decision and audit trail."
            />
          )}
        </div>
      </div>
    </>
  )
}

function AdjudicationPanel({
  projectId,
  adjudicationId,
  onChanged,
}: {
  projectId: string
  adjudicationId: string
  onChanged: () => void
}) {
  const { user } = useAuth()
  const { data, loading, error, reload } = useAsync<AdjudicationDetail>(
    () => api.get<AdjudicationDetail>(`/api/projects/${projectId}/adjudications/${adjudicationId}`),
    [projectId, adjudicationId],
  )
  const [decision, setDecision] = useState<Record<string, number | string>>({})
  const [rationale, setRationale] = useState('')
  const [escalateReason, setEscalateReason] = useState('')
  const [reopenReason, setReopenReason] = useState('')
  const [showEscalate, setShowEscalate] = useState(false)
  const [showReopen, setShowReopen] = useState(false)
  const [note, setNote] = useState<string | null>(null)

  const finalize = useMutation(() =>
    api.post(`/api/projects/${projectId}/adjudications/${adjudicationId}/finalize`, { decision, rationale }),
  )
  const escalate = useMutation(() =>
    api.post(`/api/projects/${projectId}/adjudications/${adjudicationId}/escalate?reason=${encodeURIComponent(escalateReason)}`),
  )
  const reopen = useMutation(() =>
    api.post(`/api/projects/${projectId}/adjudications/${adjudicationId}/reopen?reason=${encodeURIComponent(reopenReason)}`),
  )

  // Seed the decision form from the advisory consensus.
  useEffect(() => {
    if (!data) return
    if (data.adjudication.decision) setDecision(data.adjudication.decision as Record<string, number | string>)
    else setDecision({ ...(data.consensus.scores ?? {}) })
    setRationale(data.adjudication.rationale ?? '')
  }, [data])

  if (loading) return <Spinner label="Loading adjudication…" />
  if (error) return <ErrorState message={error} onRetry={reload} />
  if (!data) return null

  const isFinal = data.adjudication.status === 'final'
  const canDecide = can.adjudicate(user)

  return (
    <div className="space-y-5">
      <Card
        title={`Case ${data.task.external_id ?? data.task.id.slice(0, 8)}`}
        subtitle={
          <span className="flex flex-wrap items-center gap-2">
            <Badge tone={STATUS_TONE[data.adjudication.status] ?? 'slate'}>{data.adjudication.status}</Badge>
            <Badge tone="slate">strategy: {data.adjudication.strategy}</Badge>
            {data.adjudication.escalated && <Badge tone="rose">escalated</Badge>}
          </span>
        }
        actions={
          <>
            {isFinal && canDecide && (
              <button type="button" className="btn-secondary" onClick={() => setShowReopen(true)}>
                Reopen
              </button>
            )}
            {!isFinal && canDecide && (
              <button type="button" className="btn-secondary" onClick={() => setShowEscalate(true)}>
                Escalate
              </button>
            )}
          </>
        }
      >
        <div className="space-y-3">
          <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
            <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Prompt</p>
            <p className="whitespace-pre-wrap text-sm text-slate-800">{data.task.prompt}</p>
          </div>
          <div className="rounded-lg border border-slate-200 p-3">
            <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Response</p>
            <p className="max-h-64 overflow-y-auto whitespace-pre-wrap text-sm text-slate-700">{data.task.response_a}</p>
          </div>
          {data.task.reference_answer && (
            <div className="rounded-lg border border-slate-200 p-3">
              <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Reference answer</p>
              <p className="whitespace-pre-wrap text-sm text-slate-600">{data.task.reference_answer}</p>
            </div>
          )}
          {data.task.gold_label && (
            <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3">
              <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-emerald-700">Expert gold label</p>
              <pre className="overflow-x-auto font-mono text-xs text-emerald-900">
                {JSON.stringify(data.task.gold_label.scores)}
              </pre>
            </div>
          )}
        </div>
      </Card>

      <Card title="Side-by-side reviewer assessments" subtitle="Original scores — these are never modified by adjudication.">
        <div className="grid gap-3 md:grid-cols-2">
          {data.ratings.map((r) => (
            <div key={r.id} className="rounded-lg border border-slate-200 p-3">
              <div className="mb-2 flex flex-wrap items-center gap-2">
                <span className="text-sm font-semibold text-slate-800">{r.reviewer_name}</span>
                {r.abstained && <Badge tone="amber">abstained</Badge>}
                {r.confidence !== null && (
                  <span className="text-xs text-slate-500">confidence {(r.confidence * 100).toFixed(0)}%</span>
                )}
              </div>
              {r.scores && (
                <dl className="mb-2 flex flex-wrap gap-1.5">
                  {Object.entries(r.scores).map(([k, v]) => (
                    <span key={k} className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-700">
                      {k}: <strong>{String(v)}</strong>
                    </span>
                  ))}
                </dl>
              )}
              {r.rationale && <p className="text-sm text-slate-600">{r.rationale}</p>}
            </div>
          ))}
        </div>
        {data.ratings.length === 0 && <EmptyState title="No submitted ratings on this item" />}
      </Card>

      <Card title="Advisory consensus" subtitle="Computed, not authoritative. A human decision is always required.">
        <div className="mb-3 flex flex-wrap gap-1.5">
          {Object.entries(data.consensus.scores ?? {}).map(([k, v]) => (
            <span key={k} className="rounded bg-brand-50 px-2 py-1 text-xs text-brand-900">
              {k}: <strong>{String(v)}</strong>
            </span>
          ))}
          {Object.keys(data.consensus.scores ?? {}).length === 0 && (
            <span className="text-sm text-slate-500">No consensus could be computed.</span>
          )}
        </div>
        {data.consensus.limitations.length > 0 && (
          <InfoNote tone="amber">
            <strong className="font-semibold">Limitations of “{data.consensus.strategy}”:</strong>
            <ul className="mt-1 list-disc space-y-0.5 pl-4">
              {data.consensus.limitations.map((l) => (
                <li key={l}>{l}</li>
              ))}
            </ul>
          </InfoNote>
        )}
      </Card>

      <Card title="Authoritative decision">
        {!canDecide && (
          <InfoNote tone="amber">Read-only: your role cannot record adjudication decisions.</InfoNote>
        )}
        {isFinal && (
          <div className="mb-3">
            <InfoNote tone="slate">
              This adjudication is final. Reopen it to record a new decision — reopening keeps the full audit chain.
            </InfoNote>
          </div>
        )}
        <div className="grid gap-4 sm:grid-cols-2">
          {Object.entries(decision).map(([key, value]) => (
            <Field key={key} label={key} htmlFor={`dec-${key}`}>
              {typeof value === 'number' ? (
                <input
                  id={`dec-${key}`}
                  type="number"
                  step={0.1}
                  className="input"
                  value={value}
                  disabled={isFinal || !canDecide}
                  onChange={(e) => setDecision((d) => ({ ...d, [key]: Number(e.target.value) }))}
                />
              ) : (
                <input
                  id={`dec-${key}`}
                  className="input"
                  value={String(value)}
                  disabled={isFinal || !canDecide}
                  onChange={(e) => setDecision((d) => ({ ...d, [key]: e.target.value }))}
                />
              )}
            </Field>
          ))}
        </div>
        <div className="mt-4">
          <Field
            label="Resolution rationale"
            htmlFor="adj-rationale"
            hint="Required. Explain which anchors or evidence drove the decision — reviewers see this after finalisation."
          >
            <textarea
              id="adj-rationale"
              className="input min-h-[100px]"
              value={rationale}
              disabled={isFinal || !canDecide}
              onChange={(e) => setRationale(e.target.value)}
            />
          </Field>
        </div>

        {(finalize.error || note) && (
          <p
            className={`mt-3 rounded-lg border px-3 py-2 text-sm ${
              finalize.error ? 'border-rose-200 bg-rose-50 text-rose-700' : 'border-emerald-200 bg-emerald-50 text-emerald-700'
            }`}
            role={finalize.error ? 'alert' : 'status'}
          >
            {finalize.error ?? note}
          </p>
        )}

        {!isFinal && canDecide && (
          <div className="mt-4 flex flex-wrap gap-2">
            <button
              type="button"
              className="btn-primary"
              disabled={finalize.loading || rationale.trim().length < 10}
              onClick={async () => {
                const res = await finalize.run()
                if (res) {
                  setNote('Decision recorded as final.')
                  onChanged()
                  reload()
                }
              }}
            >
              {finalize.loading ? 'Recording…' : 'Record final decision'}
            </button>
            {rationale.trim().length < 10 && (
              <span className="self-center text-xs text-slate-500">A rationale of at least 10 characters is required.</span>
            )}
          </div>
        )}
      </Card>

      {data.votes.length > 0 && (
        <Card title="Panel votes" subtitle="Recorded votes from adjudicators on this case.">
          <ul className="space-y-2">
            {data.votes.map((v, i) => (
              <li key={i} className="rounded-lg border border-slate-200 p-3 text-sm">
                <p className="font-medium text-slate-800">{v.user_id.slice(0, 8)}</p>
                <p className="font-mono text-xs text-slate-600">{JSON.stringify(v.decision)}</p>
                {v.rationale && <p className="mt-1 text-slate-600">{v.rationale}</p>}
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Modal
        open={showEscalate}
        title="Escalate this case"
        onClose={() => setShowEscalate(false)}
        footer={
          <>
            <button type="button" className="btn-secondary" onClick={() => setShowEscalate(false)}>
              Cancel
            </button>
            <button
              type="button"
              className="btn-danger"
              disabled={escalate.loading || escalateReason.trim().length < 5}
              onClick={async () => {
                const res = await escalate.run()
                if (res) {
                  setShowEscalate(false)
                  setNote('Escalated to the senior adjudication panel.')
                  onChanged()
                  reload()
                }
              }}
            >
              Escalate
            </button>
          </>
        }
      >
        <Field label="Reason for escalation" htmlFor="esc-reason" hint="Recorded in the audit trail.">
          <textarea
            id="esc-reason"
            className="input min-h-[90px]"
            value={escalateReason}
            onChange={(e) => setEscalateReason(e.target.value)}
          />
        </Field>
        {escalate.error && <p className="mt-2 text-sm text-rose-600">{escalate.error}</p>}
      </Modal>

      <Modal
        open={showReopen}
        title="Reopen adjudication"
        onClose={() => setShowReopen(false)}
        footer={
          <>
            <button type="button" className="btn-secondary" onClick={() => setShowReopen(false)}>
              Cancel
            </button>
            <button
              type="button"
              className="btn-primary"
              disabled={reopen.loading || reopenReason.trim().length < 5}
              onClick={async () => {
                const res = await reopen.run()
                if (res) {
                  setShowReopen(false)
                  setNote('Reopened — a new adjudication record was created and linked to the previous one.')
                  onChanged()
                  reload()
                }
              }}
            >
              Reopen
            </button>
          </>
        }
      >
        <InfoNote tone="amber">
          Reopening creates a <strong className="font-semibold">new</strong> adjudication linked to the previous one.
          The prior decision is retained for audit; nothing is deleted or overwritten.
        </InfoNote>
        <div className="mt-3">
          <Field label="Reason for reopening" htmlFor="reopen-reason">
            <textarea
              id="reopen-reason"
              className="input min-h-[90px]"
              value={reopenReason}
              onChange={(e) => setReopenReason(e.target.value)}
            />
          </Field>
        </div>
        {reopen.error && <p className="mt-2 text-sm text-rose-600">{reopen.error}</p>}
      </Modal>
    </div>
  )
}
