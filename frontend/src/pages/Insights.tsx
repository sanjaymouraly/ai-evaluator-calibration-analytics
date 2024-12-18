import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import { useAuth, can } from '../auth'
import {
  Badge,
  Card,
  EmptyState,
  ErrorState,
  InfoNote,
  MetricValue,
  PageHeader,
  Spinner,
  StatCard,
  severityTone,
} from '../components/ui'
import { useAsync, useMutation, useTitle } from '../hooks'
import type { Rubric, RubricInsight } from '../types'

const ISSUE_LABEL: Record<string, string> = {
  low_reliability: 'Low inter-rater reliability',
  high_disagreement: 'High disagreement frequency',
  boundary_confusion: 'Boundary-score confusion',
  contradictory_rationales: 'Contradictory reviewer rationales',
  weak_definition: 'Weak or overlapping definition',
  missing_anchors: 'Missing scoring anchors',
  scoring_drift: 'Scoring drift over time',
  segment_variation: 'Variation across segments',
}

export default function InsightsPage() {
  const { projectId = '' } = useParams()
  useTitle('Rubric insights')
  const { user } = useAuth()
  const [filter, setFilter] = useState('')

  const { data: insights, loading, error, reload } = useAsync<RubricInsight[]>(
    () => api.get<RubricInsight[]>(`/api/projects/${projectId}/rubrics/insights`),
    [projectId],
  )
  const { data: rubrics } = useAsync<Rubric[]>(() => api.get<Rubric[]>(`/api/projects/${projectId}/rubrics`), [projectId])
  const analyze = useMutation(() => api.post<{ analyzed: number }>(`/api/projects/${projectId}/rubrics/insights/analyze`))
  const fromInsight = useMutation((id: string) =>
    api.post(`/api/projects/${projectId}/rubrics/change-requests/from-insight?insight_id=${id}`),
  )

  const active = rubrics?.find((r) => r.status === 'active')
  const categoryName = (id: string | null) =>
    active?.categories.find((c) => c.id === id)?.name ?? active?.categories.find((c) => c.id === id)?.key ?? '—'

  const visible = (insights ?? []).filter(
    (i) => !filter || i.severity === filter || i.issue_type === filter,
  )

  const counts = {
    total: insights?.length ?? 0,
    critical: insights?.filter((i) => i.severity === 'critical' || i.severity === 'high').length ?? 0,
    open: insights?.filter((i) => i.status === 'open').length ?? 0,
  }

  return (
    <>
      <PageHeader
        title="Rubric ambiguity & improvement"
        subtitle="Evidence-backed detection of rubric weaknesses: unreliable categories, boundary confusion, contradictory rationales, missing anchors and drift."
        backTo={`/projects/${projectId}`}
        actions={
          <button
            type="button"
            className="btn-primary"
            disabled={analyze.loading}
            onClick={async () => {
              await analyze.run()
              reload()
            }}
          >
            {analyze.loading ? 'Analysing…' : 'Run analysis'}
          </button>
        }
      />

      <div className="mb-5 grid gap-4 sm:grid-cols-3">
        <StatCard label="Insights" value={counts.total} />
        <StatCard label="High / critical" value={counts.critical} tone={counts.critical ? 'bad' : 'good'} />
        <StatCard label="Still open" value={counts.open} tone={counts.open ? 'warn' : 'good'} />
      </div>

      <InfoNote>
        Every recommendation below is <strong className="font-semibold">evidence-backed</strong>: sample size, the
        statistic that triggered it, and affected items are shown. Turning an insight into a rubric change always
        requires human approval and creates a new rubric version — existing scores are never modified.
      </InfoNote>

      {loading && <Spinner label="Loading insights…" />}
      {error && <ErrorState message={error} onRetry={reload} />}
      {analyze.error && <p className="mt-4 text-sm text-rose-600">{analyze.error}</p>}

      {insights && insights.length === 0 && (
        <div className="mt-5">
          <EmptyState
            title="No rubric weaknesses detected"
            body="Either the rubric is performing well, or there is not enough rating overlap yet (at least 3 items with 2+ ratings per category are needed before any claim is made)."
          />
        </div>
      )}

      {insights && insights.length > 0 && (
        <>
          <div className="mt-5 mb-4 flex flex-wrap gap-2">
            {['', 'critical', 'high', 'medium', 'low'].map((s) => (
              <button
                key={s || 'all'}
                type="button"
                onClick={() => setFilter(s)}
                className={`rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors ${
                  filter === s ? 'border-brand-500 bg-brand-50 text-brand-800' : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50'
                }`}
              >
                {s === '' ? 'All' : s}
              </button>
            ))}
          </div>

          <div className="space-y-4">
            {visible.map((insight) => {
              const ev = (insight.evidence ?? {}) as Record<string, unknown>
              return (
                <Card
                  key={insight.id}
                  title={
                    <span className="flex flex-wrap items-center gap-2">
                      {ISSUE_LABEL[insight.issue_type] ?? insight.issue_type}
                      <Badge tone={severityTone(insight.severity)}>{insight.severity}</Badge>
                      {insight.source === 'ai_assisted' && <Badge tone="violet">AI-assisted</Badge>}
                      <Badge tone={insight.status === 'open' ? 'amber' : 'green'}>{insight.status}</Badge>
                    </span>
                  }
                  subtitle={`Category: ${categoryName(insight.rubric_category_id)} · sample size ${insight.sample_size} items`}
                >
                  <div className="grid gap-4 lg:grid-cols-2">
                    <div>
                      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Evidence</p>
                      <dl className="space-y-1 text-sm">
                        <EvidenceRow label="Disagreements" value={String(ev.n_disagreements ?? 0)} />
                        <EvidenceRow
                          label="Disagreement rate"
                          value={
                            typeof ev.disagreement_rate === 'number'
                              ? `${(ev.disagreement_rate * 100).toFixed(1)}%`
                              : '—'
                          }
                        />
                        <EvidenceRow
                          label="Krippendorff's α"
                          value={<MetricValue value={typeof ev.krippendorff_alpha === "number" ? ev.krippendorff_alpha : null} />}
                        />
                        <EvidenceRow
                          label="Boundary confusion"
                          value={
                            typeof ev.boundary_confusion_rate === 'number'
                              ? `${(ev.boundary_confusion_rate * 100).toFixed(1)}%`
                              : '—'
                          }
                        />
                        <EvidenceRow label="Rationale conflicts" value={String(ev.rationale_conflicts ?? 0)} />
                        <EvidenceRow
                          label="Drift correlation"
                          value={<MetricValue value={typeof ev.drift_correlation === 'number' ? ev.drift_correlation : null} />}
                        />
                      </dl>
                      {ev.segments ? (
                        <details className="mt-2">
                          <summary className="cursor-pointer text-xs font-medium text-brand-600 hover:underline">
                            Segment breakdown
                          </summary>
                          <pre className="mt-1 overflow-x-auto rounded bg-slate-50 p-2 font-mono text-[11px] text-slate-600">
                            {JSON.stringify(ev.segments, null, 2)}
                          </pre>
                        </details>
                      ) : null}
                      {insight.affected_task_ids && insight.affected_task_ids.length > 0 && (
                        <p className="mt-2 text-xs text-slate-500">
                          {insight.affected_task_ids.length} affected item(s) — review them in the{' '}
                          <Link to={`/projects/${projectId}/disagreements`} className="font-medium text-brand-600 hover:underline">
                            disagreement queue
                          </Link>
                          .
                        </p>
                      )}
                    </div>

                    <div>
                      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
                        Recommended improvement
                      </p>
                      {insight.suggestion?.recommendation && (
                        <p className="mb-2 text-sm text-slate-700">{insight.suggestion.recommendation}</p>
                      )}
                      {insight.suggestion?.proposed_improvements && (
                        <ul className="mb-3 list-disc space-y-1 pl-4 text-xs text-slate-600">
                          {insight.suggestion.proposed_improvements.map((s) => (
                            <li key={s}>{s}</li>
                          ))}
                        </ul>
                      )}
                      {insight.suggestion?.requires_human_approval && (
                        <InfoNote tone="amber">
                          Requires human approval. Raising a change request does not modify the rubric until a lead
                          approves and applies it as a new version.
                        </InfoNote>
                      )}
                      {insight.status === 'open' && can.manageRubric(user) && (
                        <button
                          type="button"
                          className="btn-primary mt-3"
                          disabled={fromInsight.loading}
                          onClick={async () => {
                            const res = await fromInsight.run(insight.id)
                            if (res) reload()
                          }}
                        >
                          Raise change request
                        </button>
                      )}
                      {fromInsight.error && <p className="mt-2 text-xs text-rose-600">{fromInsight.error}</p>}
                    </div>
                  </div>
                </Card>
              )
            })}
          </div>
        </>
      )}
    </>
  )
}

function EvidenceRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-slate-100 pb-1">
      <dt className="text-slate-500">{label}</dt>
      <dd className="font-medium tabular-nums text-slate-800">{value}</dd>
    </div>
  )
}
