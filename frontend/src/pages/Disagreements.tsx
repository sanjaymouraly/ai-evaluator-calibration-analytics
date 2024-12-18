import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, buildQuery } from '../api/client'
import {
  Badge,
  Card,
  EmptyState,
  ErrorState,
  InfoNote,
  MetricValue,
  Modal,
  PageHeader,
  Spinner,
  StatCard,
  severityTone,
} from '../components/ui'
import { useAsync, useMutation, useTitle } from '../hooks'
import type { Disagreement, DisagreementDetail } from '../types'

const KIND_LABEL: Record<string, string> = {
  opposite_categorical: 'Opposite categorical judgment',
  major_score_gap: 'Major score gap',
  minor_score_gap: 'Minor score gap',
  boundary_confusion: 'Adjacent-scale boundary confusion',
  expert_mismatch: 'Reviewer vs expert mismatch',
  rubric_interpretation: 'Inconsistent rubric interpretation',
}

export default function DisagreementsPage() {
  const { projectId = '' } = useParams()
  useTitle('Disagreements')
  const [status, setStatus] = useState('open')
  const [kind, setKind] = useState('')
  const [severityClass, setSeverityClass] = useState('')
  const [detailId, setDetailId] = useState<string | null>(null)

  const { data, loading, error, reload } = useAsync<Disagreement[]>(
    () =>
      api.get<Disagreement[]>(
        `/api/projects/${projectId}/disagreements${buildQuery({ status, kind, severity_class: severityClass, limit: 300 })}`,
      ),
    [projectId, status, kind, severityClass],
  )
  const { data: summary } = useAsync<{ total: number; open: number; by_class: Record<string, number>; by_kind: Record<string, number> }>(
    () => api.get(`/api/projects/${projectId}/disagreements/summary`),
    [projectId, data],
  )
  const scan = useMutation(() => api.post(`/api/projects/${projectId}/disagreements/scan`))

  return (
    <>
      <PageHeader
        title="Disagreement queue"
        subtitle="Automatically detected scoring disagreements, ranked by a transparent, scale-relative severity score."
        backTo={`/projects/${projectId}`}
        actions={
          <button
            type="button"
            className="btn-primary"
            disabled={scan.loading}
            onClick={async () => {
              await scan.run()
              reload()
            }}
          >
            {scan.loading ? 'Scanning…' : 'Re-run detection'}
          </button>
        }
      />

      {summary && (
        <div className="mb-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <StatCard label="Total detected" value={summary.total} />
          <StatCard label="Open" value={summary.by_class ? summary.open : 0} tone={summary.open > 0 ? 'warn' : 'good'} />
          <StatCard label="Critical" value={summary.by_class?.critical ?? 0} tone={(summary.by_class?.critical ?? 0) > 0 ? 'bad' : 'neutral'} />
          <StatCard label="Major" value={summary.by_class?.major ?? 0} tone={(summary.by_class?.major ?? 0) > 0 ? 'warn' : 'neutral'} />
        </div>
      )}

      {scan.error && <p className="mb-4 text-sm text-rose-600">{scan.error}</p>}

      <Card
        title="Queue"
        subtitle="Highest priority first: severity × reviewer coverage × category weight."
        actions={
          <div className="flex flex-wrap gap-2">
            <select className="input w-auto" value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Filter by status">
              <option value="">All statuses</option>
              <option value="open">Open</option>
              <option value="in_review">In review</option>
              <option value="resolved">Resolved</option>
              <option value="dismissed">Dismissed</option>
            </select>
            <select className="input w-auto" value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Filter by type">
              <option value="">All types</option>
              {Object.entries(KIND_LABEL).map(([k, label]) => (
                <option key={k} value={k}>
                  {label}
                </option>
              ))}
            </select>
            <select
              className="input w-auto"
              value={severityClass}
              onChange={(e) => setSeverityClass(e.target.value)}
              aria-label="Filter by severity"
            >
              <option value="">All severities</option>
              <option value="critical">Critical</option>
              <option value="major">Major</option>
              <option value="minor">Minor</option>
            </select>
          </div>
        }
      >
        {loading && <Spinner label="Loading disagreements…" />}
        {error && <ErrorState message={error} onRetry={reload} />}
        {data && data.length === 0 && (
          <EmptyState
            title="No disagreements match these filters"
            body="Run detection after reviewers submit ratings, or widen the filters."
          />
        )}
        {data && data.length > 0 && (
          <div className="overflow-x-auto">
            <table className="table-base">
              <thead>
                <tr>
                  <th className="th" scope="col">Priority</th>
                  <th className="th" scope="col">Type</th>
                  <th className="th" scope="col">Category</th>
                  <th className="th" scope="col">Severity</th>
                  <th className="th text-right" scope="col">Score</th>
                  <th className="th" scope="col">Status</th>
                  <th className="th" scope="col">Item</th>
                  <th className="th" scope="col"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {data.map((d) => (
                  <tr key={d.id} className="hover:bg-slate-50">
                    <td className="td font-semibold tabular-nums text-slate-800">
                      <MetricValue value={d.priority_score} digits={2} />
                    </td>
                    <td className="td">{KIND_LABEL[d.kind] ?? d.kind}</td>
                    <td className="td font-mono text-xs">{d.category_key ?? '—'}</td>
                    <td className="td">
                      <Badge tone={severityTone(d.severity_class)}>{d.severity_class}</Badge>
                    </td>
                    <td className="td text-right tabular-nums">
                      <MetricValue value={d.severity_score} digits={3} />
                    </td>
                    <td className="td">
                      <Badge tone={d.status === 'resolved' ? 'green' : d.status === 'open' ? 'amber' : 'slate'}>
                        {d.status.replace('_', ' ')}
                      </Badge>
                    </td>
                    <td className="td font-mono text-xs text-slate-500">{d.task_id.slice(0, 8)}</td>
                    <td className="td">
                      <button type="button" className="btn-secondary px-2.5 py-1 text-xs" onClick={() => setDetailId(d.id)}>
                        Review
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {detailId && (
        <DetailModal
          projectId={projectId}
          disagreementId={detailId}
          onClose={() => setDetailId(null)}
          onChanged={reload}
        />
      )}
    </>
  )
}

function DetailModal({
  projectId,
  disagreementId,
  onClose,
  onChanged,
}: {
  projectId: string
  disagreementId: string
  onClose: () => void
  onChanged: () => void
}) {
  const { data, loading, error, reload } = useAsync<DisagreementDetail>(
    () => api.get<DisagreementDetail>(`/api/projects/${projectId}/disagreements/${disagreementId}`),
    [projectId, disagreementId],
  )
  const setStatus = useMutation((s: string) =>
    api.post(`/api/projects/${projectId}/disagreements/${disagreementId}/status?status=${s}`),
  )
  const [aiSummary, setAiSummary] = useState<Record<string, unknown> | null>(null)
  const [aiLoading, setAiLoading] = useState(false)
  const ai = useMutation(() =>
    api.post<Record<string, unknown>>(
      `/api/llm/summarize-case?project_id=${projectId}&task_id=${data?.disagreement.task_id}`,
    ),
  )

  if (loading) return <Spinner label="Loading case…" />
  if (error) return <ErrorState message={error} onRetry={reload} />
  if (!data) return null

  const d = data.disagreement
  const details = (d.details ?? {}) as Record<string, unknown>

  return (
    <Modal open title={`Disagreement · ${d.category_key ?? 'general'}`} onClose={onClose} wide
      footer={
        <>
          {d.status !== 'dismissed' && (
            <button
              type="button"
              className="btn-secondary"
              disabled={setStatus.loading}
              onClick={async () => {
                await setStatus.run('dismissed')
                onChanged()
                reload()
              }}
            >
              Dismiss
            </button>
          )}
          <Link
            to={`/projects/${projectId}/adjudication?disagreement=${d.id}&task=${d.task_id}`}
            className="btn-primary"
          >
            Adjudicate this case
          </Link>
        </>
      }
    >
      <div className="space-y-4">
        <div className="flex flex-wrap gap-2">
          <Badge tone={severityTone(d.severity_class)}>{d.severity_class}</Badge>
          <Badge tone="slate">{KIND_LABEL[d.kind] ?? d.kind}</Badge>
          <Badge tone="blue">severity {d.severity_score.toFixed(3)}</Badge>
          <Badge tone="blue">priority {d.priority_score.toFixed(3)}</Badge>
          <Badge tone={d.status === 'resolved' ? 'green' : 'amber'}>{d.status.replace('_', ' ')}</Badge>
        </div>

        <InfoNote tone="slate">
          <strong className="font-semibold">How severity is computed.</strong> {data.severity_formula}
        </InfoNote>

        <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Prompt</p>
          <p className="whitespace-pre-wrap text-sm text-slate-800">{data.task.prompt}</p>
        </div>
        <div className="rounded-lg border border-slate-200 p-3">
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Response</p>
          <p className="max-h-52 overflow-y-auto whitespace-pre-wrap text-sm text-slate-700">{data.task.response_a}</p>
        </div>
        {data.task.reference_answer && (
          <div className="rounded-lg border border-slate-200 p-3">
            <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Reference answer</p>
            <p className="whitespace-pre-wrap text-sm text-slate-600">{data.task.reference_answer}</p>
          </div>
        )}

        <div>
          <p className="mb-2 text-sm font-semibold text-slate-800">Independent ratings</p>
          <div className="space-y-2">
            {data.ratings.map((r) => (
              <div key={r.id} className="rounded-lg border border-slate-200 p-3">
                <div className="mb-1.5 flex flex-wrap items-center gap-2">
                  <span className="text-sm font-medium text-slate-800">{r.reviewer_name}</span>
                  {r.abstained && <Badge tone="amber">abstained</Badge>}
                  {r.version > 1 && <Badge tone="slate">v{r.version}</Badge>}
                  {r.confidence !== null && (
                    <span className="text-xs text-slate-500">confidence {(r.confidence * 100).toFixed(0)}%</span>
                  )}
                </div>
                {r.scores && (
                  <dl className="mb-1.5 flex flex-wrap gap-1.5">
                    {Object.entries(r.scores).map(([k, v]) => (
                      <span
                        key={k}
                        className={`rounded px-2 py-0.5 text-xs ${
                          k === d.category_key ? 'bg-amber-100 font-semibold text-amber-900' : 'bg-slate-100 text-slate-700'
                        }`}
                      >
                        {k}: {String(v)}
                      </span>
                    ))}
                  </dl>
                )}
                {r.rationale && <p className="text-sm text-slate-600">{r.rationale}</p>}
                {r.evidence && <p className="mt-1 text-xs italic text-slate-500">Evidence: {r.evidence}</p>}
              </div>
            ))}
          </div>
        </div>

        {typeof details.gap === 'number' && (
          <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600">
            <p className="font-semibold text-slate-700">Divergence detail</p>
            <p>
              gap {String(details.gap)} on a scale of {String(details.scale_min)}–{String(details.scale_max)} (range{' '}
              {String(details.scale_range)}) → normalised gap {String(details.gap_norm)}, spread {String(details.spread_norm)}
            </p>
            {details.expert_mismatch === true && <p className="mt-1 text-rose-700">Deviates from the expert gold label.</p>}
            {details.adjacent_only === true && (
              <p className="mt-1 text-amber-700">Ratings differ by exactly one scale step — a boundary-definition problem.</p>
            )}
          </div>
        )}

        <div>
          <button
            type="button"
            className="btn-secondary"
            disabled={aiLoading}
            onClick={async () => {
              setAiLoading(true)
              const res = await ai.run()
              setAiSummary(res)
              setAiLoading(false)
            }}
          >
            {aiLoading ? 'Analysing…' : 'Summarise this case'}
          </button>
          {aiSummary && (
            <div className="mt-3 rounded-lg border border-violet-200 bg-violet-50 p-3">
              <p className="mb-1 flex items-center gap-2 text-xs font-semibold text-violet-900">
                Case summary
                <Badge tone="violet">{String(aiSummary.mode)}</Badge>
                {aiSummary.ai_generated === true && <Badge tone="amber">AI-generated</Badge>}
              </p>
              {Array.isArray(aiSummary.divergent_categories) && (
                <ul className="mb-2 space-y-1 text-xs text-violet-900">
                  {(aiSummary.divergent_categories as Array<Record<string, unknown>>).map((c, i) => (
                    <li key={i}>
                      <strong>{String(c.category)}</strong>: {String((c.values as string[])?.join(' vs '))} (spread{' '}
                      {String(c.spread)})
                    </li>
                  ))}
                </ul>
              )}
              {typeof aiSummary.ai_summary === 'string' && (
                <p className="text-xs text-violet-900">{aiSummary.ai_summary}</p>
              )}
              <p className="mt-2 text-[11px] text-violet-700">{String(aiSummary.note ?? '')}</p>
            </div>
          )}
          {ai.error && <p className="mt-2 text-xs text-rose-600">{ai.error}</p>}
        </div>
      </div>
    </Modal>
  )
}
