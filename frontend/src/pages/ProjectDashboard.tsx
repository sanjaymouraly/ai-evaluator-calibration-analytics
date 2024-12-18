import { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import {
  CategoryPieChart,
  ConfusionMatrix,
  GroupedBarChart,
  SimpleBarChart,
  TrendLineChart,
} from '../components/charts'
import {
  Badge,
  Card,
  EmptyState,
  ErrorState,
  InfoNote,
  MetricValue,
  PageHeader,
  ProgressBar,
  Spinner,
  StatCard,
  WarningList,
} from '../components/ui'
import { useAsync, useTitle } from '../hooks'
import type {
  ActivityPoint,
  Dashboard,
  PairwiseAgreement,
  Project,
  ScoreDistribution,
  User,
} from '../types'

const METRIC_HELP: Record<string, string> = {
  fleiss_kappa:
    "Fleiss' κ — chance-corrected agreement across multiple raters per item (categorical). 1 = perfect, 0 = chance.",
  krippendorff_alpha:
    "Krippendorff's α — chance-corrected disagreement, missing-data tolerant. Below 0.667 only tentative conclusions are safe.",
  icc_2_1: 'ICC(2,1) — two-way random-effects intraclass correlation for absolute agreement on numeric scores.',
  raw_agreement: 'Raw agreement — fraction of paired ratings that match exactly (no chance correction).',
  mad: 'Mean absolute difference — average numeric gap between paired ratings.',
}

function metricLabel(m: { metric?: string }): string {
  switch (m.metric) {
    case 'fleiss_kappa':
      return "Fleiss' κ"
    case 'krippendorff_alpha_ordinal':
      return "Krippendorff's α (ordinal)"
    case 'icc_2_1':
      return 'ICC(2,1)'
    default:
      return m.metric ?? 'metric'
  }
}

function metricValue(m: Record<string, unknown>): number | null {
  for (const key of ['fleiss_kappa', 'krippendorff_alpha', 'icc_2_1']) {
    if (key in m) return (m[key] as number | null) ?? null
  }
  return null
}

export default function ProjectDashboard() {
  const { projectId = '' } = useParams()
  useTitle('Dashboard')
  const { data: project } = useAsync<Project>(() => api.get<Project>(`/api/projects/${projectId}`), [projectId])
  const { data, loading, error, reload } = useAsync<Dashboard>(
    () => api.get<Dashboard>(`/api/projects/${projectId}/analytics/dashboard`),
    [projectId],
  )
  const { data: activity } = useAsync<ActivityPoint[]>(
    () => api.get<ActivityPoint[]>(`/api/projects/${projectId}/analytics/activity-trend`),
    [projectId],
  )
  const { data: pairwise } = useAsync<PairwiseAgreement[]>(
    () => api.get<PairwiseAgreement[]>(`/api/projects/${projectId}/analytics/pairwise-agreement`),
    [projectId],
  )
  const { data: users } = useAsync<User[]>(() => api.get<User[]>('/api/auth/users').catch(() => [] as User[]), [])
  const { data: distributions } = useAsync<Record<string, ScoreDistribution>>(
    () => api.get<Record<string, ScoreDistribution>>(`/api/projects/${projectId}/analytics/distributions`),
    [projectId],
  )
  const { data: filters } = useAsync<{ models: string[]; reviewers: string[] }>(
    () => api.get<{ models: string[]; reviewers: string[] }>(`/api/projects/${projectId}/analytics/filters`),
    [projectId],
  )
  const [modelFilter, setModelFilter] = useState<string>('')

  const nameOf = useMemo(() => {
    const map = new Map<string, string>()
    users?.forEach((u) => map.set(u.id, u.full_name))
    return (id: string) => map.get(id) ?? id.slice(0, 8)
  }, [users])

  if (loading) return <Spinner label="Computing analytics…" />
  if (error) return <ErrorState message={error} onRetry={reload} />
  if (!data) return null

  const cats = data.metrics.categories ?? {}
  const categoryEntries = Object.entries(cats).filter(([, m]) => (m.n_items ?? 0) > 0)

  const reliabilityChart = categoryEntries.map(([key, m]) => ({
    name: key,
    value: Number((metricValue(m as unknown as Record<string, unknown>) ?? 0).toFixed(3)),
  }))

  const disagreementByClass = Object.entries(data.disagreements.by_class ?? {}).map(([name, value]) => ({
    name,
    value,
  }))
  const disagreementByKind = Object.entries(data.disagreements.by_kind ?? {}).map(([name, value]) => ({ name, value }))
  const disagreementByCategory = Object.entries(data.disagreements.by_category ?? {})
    .map(([name, value]) => ({ name, value }))
    .sort((a, b) => b.value - a.value)

  const activityRows = (activity ?? []).map((p) => ({ date: p.date, ratings: p.ratings }))

  const biasChart = data.reviewer_bias.map((b) => ({
    name: nameOf(b.reviewer_id),
    value: Number(b.mean_deviation.toFixed(3)),
  }))

  const goldRows = Object.entries(data.accuracy_vs_gold.by_reviewer ?? {}).map(([rid, s]) => ({
    name: nameOf(rid),
    accuracy: s.accuracy === null ? null : Number((s.accuracy * 100).toFixed(1)),
    mae: s.mae_vs_gold === null ? null : Number(s.mae_vs_gold.toFixed(2)),
  }))

  return (
    <>
      <PageHeader
        title={project?.name ?? 'Project dashboard'}
        subtitle={project?.description ?? undefined}
        backTo="/projects"
        actions={
          <>
            <Badge tone={project?.status === 'active' ? 'green' : 'slate'}>{project?.status}</Badge>
            <Link to={`/projects/${projectId}/reports`} className="btn-secondary">
              Export report
            </Link>
          </>
        }
      />

      {filters && filters.models.length > 1 && (
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <label className="text-xs font-medium text-slate-600" htmlFor="model-filter">
            Filter by model
          </label>
          <select
            id="model-filter"
            className="input w-auto"
            value={modelFilter}
            onChange={(e) => setModelFilter(e.target.value)}
          >
            <option value="">All models ({filters.models.length})</option>
            {filters.models.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
          {modelFilter && (
            <InfoNote tone="amber">
              Model filtering applies to the task list and disagreement drill-downs; reliability metrics below are
              computed across the whole project.
            </InfoNote>
          )}
        </div>
      )}

      <div className="mb-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Review progress"
          value={`${data.progress.completion_pct.toFixed(0)}%`}
          hint={`${data.progress.completed_tasks} of ${data.progress.total_tasks} tasks complete`}
        />
        <StatCard label="Submitted ratings" value={data.metrics.n_ratings} hint={`${data.progress.reviewers} reviewers`} />
        <StatCard
          label="Open disagreements"
          value={data.disagreements.by_status?.open ?? 0}
          tone={(data.disagreements.by_status?.open ?? 0) > 0 ? 'warn' : 'good'}
          hint={`${data.disagreements.total} detected in total`}
        />
        <StatCard
          label="Adjudications finalised"
          value={data.adjudication.final}
          tone={data.adjudication.pending > 0 ? 'warn' : 'good'}
          hint={`${data.adjudication.pending} pending · ${data.adjudication.escalated} escalated`}
        />
      </div>

      <div className="mb-5">
        <ProgressBar
          value={data.progress.completion_pct}
          label="Overall completion"
        />
      </div>

      {data.metrics.n_ratings === 0 ? (
        <EmptyState
          title="No ratings collected yet"
          body="Assign reviewers and collect independent ratings — agreement, bias and disagreement analytics will appear here automatically."
          action={
            <Link to={`/projects/${projectId}/tasks`} className="btn-primary">
              Go to tasks &amp; data
            </Link>
          }
        />
      ) : (
        <div className="space-y-5">
          <Card
            title="Inter-reviewer reliability by rubric category"
            subtitle="The right statistic depends on the scale: Fleiss' κ for categorical, Krippendorff's α for ordinal, ICC(2,1) for numeric."
          >
            {categoryEntries.length === 0 ? (
              <EmptyState title="No category has two or more ratings per item yet" />
            ) : (
              <>
                <SimpleBarChart
                  data={reliabilityChart}
                  domain={[-0.2, 1]}
                  valueLabel="reliability"
                  height={260}
                  formatValue={(v) => v.toFixed(3)}
                />
                <div className="mt-4 overflow-x-auto">
                  <table className="table-base">
                    <thead>
                      <tr>
                        <th className="th" scope="col">Category</th>
                        <th className="th" scope="col">Scale</th>
                        <th className="th" scope="col">Metric</th>
                        <th className="th text-right" scope="col">Value</th>
                        <th className="th text-right" scope="col">Raw agreement</th>
                        <th className="th text-right" scope="col">Items</th>
                        <th className="th text-right" scope="col">Ratings</th>
                      </tr>
                    </thead>
                    <tbody>
                      {categoryEntries.map(([key, m]) => {
                        const rec = m as unknown as Record<string, unknown>
                        const value = metricValue(rec)
                        return (
                          <tr key={key}>
                            <td className="td font-medium text-slate-800">{key}</td>
                            <td className="td">
                              <Badge tone="slate">{m.scale_type}</Badge>
                            </td>
                            <td className="td" title={METRIC_HELP[m.metric ?? ''] ?? ''}>
                              {metricLabel(m)}
                            </td>
                            <td className="td text-right font-semibold">
                              <MetricValue value={value} />
                            </td>
                            <td className="td text-right">
                              <MetricValue value={m.raw_agreement} />
                            </td>
                            <td className="td text-right tabular-nums">{m.n_items}</td>
                            <td className="td text-right tabular-nums">{m.n_ratings ?? 0}</td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
                <div className="mt-3 space-y-2">
                  {categoryEntries.map(([key, m]) =>
                    m.warnings && m.warnings.length > 0 ? (
                      <div key={key}>
                        <p className="text-xs font-semibold text-slate-700">{key}</p>
                        <WarningList warnings={m.warnings} />
                      </div>
                    ) : null,
                  )}
                </div>
                <InfoNote>
                  <strong className="font-semibold">Interpretation.</strong> Reliability measures whether reviewers are
                  <em> consistent with each other</em>. It is not the same as accuracy against expert labels, reviewer
                  bias, or calibration — those are reported separately below.
                </InfoNote>
              </>
            )}
          </Card>

          <div className="grid gap-5 lg:grid-cols-2">
            <Card title="Disagreements by severity" subtitle="Severity is scale-relative, not a single global threshold.">
              {disagreementByClass.length === 0 ? (
                <EmptyState title="No disagreements detected" />
              ) : (
                <CategoryPieChart data={disagreementByClass} name="severity" />
              )}
            </Card>
            <Card title="Disagreements by type">
              {disagreementByKind.length === 0 ? (
                <EmptyState title="No disagreements detected" />
              ) : (
                <SimpleBarChart data={disagreementByKind} height={240} valueLabel="count" />
              )}
            </Card>
          </div>

          <Card
            title="High-risk rubric categories"
            subtitle="Categories generating the most disagreement — the usual starting point for rubric improvement."
            actions={
              <Link to={`/projects/${projectId}/insights`} className="btn-secondary">
                Open rubric insights
              </Link>
            }
          >
            {disagreementByCategory.length === 0 ? (
              <EmptyState title="No category-level disagreements yet" />
            ) : (
              <SimpleBarChart data={disagreementByCategory} height={240} valueLabel="disagreements" />
            )}
          </Card>

          <div className="grid gap-5 lg:grid-cols-2">
            <Card
              title="Reviewer bias (severity / leniency)"
              subtitle="Mean signed deviation from per-item consensus. Positive = harsher than peers, negative = more lenient."
            >
              {biasChart.length === 0 ? (
                <EmptyState title="Not enough paired scores to estimate bias" />
              ) : (
                <>
                  <SimpleBarChart data={biasChart} height={240} valueLabel="mean deviation from consensus" color="#2643e5" />
                  <InfoNote>
                    Bias is only comparable between reviewers who rated a similar mix of tasks. Check task coverage
                    before acting on these numbers.
                  </InfoNote>
                </>
              )}
            </Card>

            <Card
              title="Accuracy vs expert gold labels"
              subtitle="Correctness against adjudicated reference labels — distinct from inter-reviewer agreement."
              actions={
                <Link to={`/projects/${projectId}/calibration`} className="btn-secondary">
                  Calibration
                </Link>
              }
            >
              {data.accuracy_vs_gold.n_gold_tasks === 0 ? (
                <EmptyState
                  title="No gold-labelled items yet"
                  body="Approve reference labels on a few tasks to measure reviewer accuracy."
                />
              ) : (
                <>
                  <p className="mb-3 text-xs text-slate-500">
                    {data.accuracy_vs_gold.n_gold_tasks} gold-labelled tasks · overall accuracy{' '}
                    <MetricValue value={data.accuracy_vs_gold.overall_accuracy === null ? null : data.accuracy_vs_gold.overall_accuracy * 100} digits={1} suffix="%" />
                  </p>
                  <GroupedBarChart data={goldRows} keys={['accuracy', 'mae']} height={240} />
                </>
              )}
            </Card>
          </div>

          <div className="grid gap-5 lg:grid-cols-2">
            <Card title="Rating activity over time" subtitle="Submitted ratings per day.">
              <TrendLineChart data={activityRows} xKey="date" yKey="ratings" label="ratings" />
            </Card>

            <Card
              title="Pairwise reviewer agreement"
              subtitle="Exact-match rate on items two reviewers both rated."
              actions={
                <Link to={`/projects/${projectId}/disagreements`} className="btn-secondary">
                  Disagreement queue
                </Link>
              }
            >
              {!pairwise || pairwise.length === 0 ? (
                <EmptyState title="No reviewer pairs share items yet" />
              ) : (
                <div className="overflow-x-auto">
                  <table className="table-base">
                    <thead>
                      <tr>
                        <th className="th" scope="col">Reviewer pair</th>
                        <th className="th text-right" scope="col">Shared items</th>
                        <th className="th text-right" scope="col">Exact agreement</th>
                        <th className="th text-right" scope="col">Mean |Δ|</th>
                      </tr>
                    </thead>
                    <tbody>
                      {pairwise.slice(0, 12).map((p) => (
                        <tr key={`${p.reviewer_a}-${p.reviewer_b}`}>
                          <td className="td">
                            {nameOf(p.reviewer_a)} ↔ {nameOf(p.reviewer_b)}
                          </td>
                          <td className="td text-right tabular-nums">{p.shared_items}</td>
                          <td className="td text-right">
                            <MetricValue
                              value={p.exact_agreement === null ? null : p.exact_agreement * 100}
                              digits={1}
                              suffix="%"
                            />
                          </td>
                          <td className="td text-right">
                            <MetricValue value={p.mean_abs_diff} digits={2} />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Card>
          </div>

          {distributions && Object.keys(distributions).length > 0 && (
            <Card title="Score distributions" subtitle="How each rubric category is being used across the project.">
              <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
                {Object.entries(distributions).map(([key, d]) => (
                  <div key={key} className="rounded-lg border border-slate-200 p-3">
                    <p className="mb-1 text-sm font-semibold text-slate-800">{key}</p>
                    <p className="mb-2 text-[11px] uppercase tracking-wide text-slate-400">
                      {d.scale_type} · n={d.n}
                    </p>
                    {d.scale_type === 'categorical' ? (
                      <CategoryPieChart
                        data={Object.entries(d.counts ?? {}).map(([name, value]) => ({ name, value }))}
                        height={180}
                        name={key}
                      />
                    ) : (
                      <>
                        <SimpleBarChart
                          data={Object.entries(d.histogram ?? {}).map(([name, value]) => ({
                            name,
                            value,
                          }))}
                          height={180}
                          valueLabel="ratings"
                          color="#2643e5"
                        />
                        <p className="mt-2 text-[11px] text-slate-500">
                          mean <MetricValue value={d.mean} digits={2} /> · median{' '}
                          <MetricValue value={d.median} digits={2} /> · sd <MetricValue value={d.std} digits={2} />
                        </p>
                      </>
                    )}
                  </div>
                ))}
              </div>
            </Card>
          )}

          <ConfusionCard projectId={projectId} categories={categoryEntries.map(([k]) => k)} />
        </div>
      )}
    </>
  )
}

function ConfusionCard({ projectId, categories }: { projectId: string; categories: string[] }) {
  const [category, setCategory] = useState<string>(categories[0] ?? '')
  const { data } = useAsync<{ matrix: number[][]; labels: string[]; accuracy: number | null }>(
    () =>
      category
        ? api.get(`/api/projects/${projectId}/analytics/confusion-matrix?category_key=${encodeURIComponent(category)}`)
        : Promise.resolve({ matrix: [], labels: [], accuracy: null }),
    [projectId, category],
  )

  if (categories.length === 0) return null

  return (
    <Card
      title="Confusion matrix vs gold labels"
      subtitle="Rows are expert-approved reference labels, columns are reviewer ratings. The diagonal is correct."
      actions={
        <select className="input w-auto" value={category} onChange={(e) => setCategory(e.target.value)} aria-label="Rubric category">
          {categories.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      }
    >
      {data && data.matrix.length > 0 && (
        <p className="mb-3 text-xs text-slate-500">
          Accuracy <MetricValue value={data.accuracy === null ? null : data.accuracy * 100} digits={1} suffix="%" />
        </p>
      )}
      <ConfusionMatrix matrix={data?.matrix ?? []} labels={data?.labels ?? []} />
    </Card>
  )
}
