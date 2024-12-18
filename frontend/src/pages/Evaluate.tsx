import { useEffect, useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import { api } from '../api/client'
import { useAuth } from '../auth'
import {
  Badge,
  Card,
  EmptyState,
  ErrorState,
  Field,
  InfoNote,
  MetricValue,
  PageHeader,
  Spinner,
} from '../components/ui'
import { useAsync, useMutation, useTitle } from '../hooks'
import type { RubricCategory, Workspace } from '../types'

interface QueueItem {
  task_id: string
  external_id: string | null
  prompt: string
  model_name: string | null
  assignment_status: string
}

type ScoreValue = number | string

export default function EvaluatePage() {
  const { projectId = '' } = useParams()
  useTitle('Evaluate')
  const { user } = useAuth()
  const { data: queue, loading, error, reload } = useAsync<QueueItem[]>(
    () => api.get<QueueItem[]>(`/api/projects/${projectId}/queue`),
    [projectId],
  )
  const [selected, setSelected] = useState<string | null>(null)

  useEffect(() => {
    if (!selected && queue && queue.length > 0) {
      const firstOpen = queue.find((q) => q.assignment_status !== 'completed') ?? queue[0]
      setSelected(firstOpen.task_id)
    }
  }, [queue, selected])

  return (
    <>
      <PageHeader
        title="Evaluation workspace"
        subtitle="Rate your assigned items independently. Other reviewers' scores stay hidden until you submit your own."
        backTo={`/projects/${projectId}`}
      />

      {loading && <Spinner label="Loading your queue…" />}
      {error && <ErrorState message={error} onRetry={reload} />}

      {queue && queue.length === 0 && (
        <EmptyState
          title="No tasks assigned to you yet"
          body="A project lead needs to assign you items before you can rate them."
        />
      )}

      {queue && queue.length > 0 && (
        <div className="grid gap-5 lg:grid-cols-[300px_minmax(0,1fr)]">
          <Card title={`Your queue (${queue.length})`} className="lg:sticky lg:top-4 lg:self-start">
            <ul className="max-h-[70vh] space-y-1 overflow-y-auto pr-1">
              {queue.map((item) => (
                <li key={item.task_id}>
                  <button
                    type="button"
                    onClick={() => setSelected(item.task_id)}
                    aria-current={selected === item.task_id}
                    className={`w-full rounded-lg border p-2.5 text-left transition-colors ${
                      selected === item.task_id
                        ? 'border-brand-300 bg-brand-50'
                        : 'border-slate-200 hover:border-slate-300 hover:bg-slate-50'
                    }`}
                  >
                    <div className="mb-1 flex items-center justify-between gap-2">
                      <span className="font-mono text-[10px] text-slate-400">{item.external_id ?? item.task_id.slice(0, 8)}</span>
                      <Badge tone={item.assignment_status === 'completed' ? 'green' : 'amber'}>
                        {item.assignment_status}
                      </Badge>
                    </div>
                    <p className="line-clamp-2 text-xs text-slate-700">{item.prompt}</p>
                    {item.model_name && <p className="mt-1 text-[10px] text-slate-400">{item.model_name}</p>}
                  </button>
                </li>
              ))}
            </ul>
          </Card>

          <div>
            {selected ? (
              <RatingPanel
                key={selected}
                projectId={projectId}
                taskId={selected}
                reviewerName={user?.full_name ?? 'you'}
                onSubmitted={reload}
              />
            ) : (
              <EmptyState title="Select an item to begin" />
            )}
          </div>
        </div>
      )}
    </>
  )
}

function RatingPanel({
  projectId,
  taskId,
  reviewerName,
  onSubmitted,
}: {
  projectId: string
  taskId: string
  reviewerName: string
  onSubmitted: () => void
}) {
  const { data: ws, loading, error, reload } = useAsync<Workspace>(
    () => api.get<Workspace>(`/api/projects/${projectId}/tasks/${taskId}/evaluate`),
    [projectId, taskId],
  )
  const [scores, setScores] = useState<Record<string, ScoreValue>>({})
  const [rationale, setRationale] = useState('')
  const [evidence, setEvidence] = useState('')
  const [confidence, setConfidence] = useState(0.7)
  const [abstain, setAbstain] = useState(false)
  const [validationError, setValidationError] = useState<string | null>(null)
  const [savedNote, setSavedNote] = useState<string | null>(null)

  // Initialise the form from an existing draft or submitted rating.
  useEffect(() => {
    if (!ws) return
    const source = ws.my_rating ?? ws.my_draft
    if (source?.scores) setScores(source.scores as Record<string, ScoreValue>)
    else {
      const defaults: Record<string, ScoreValue> = {}
      ws.rubric.categories.forEach((c) => {
        defaults[c.key] =
          c.scale_type === 'categorical' ? String(c.options?.[0]?.value ?? '') : Number(c.min_value ?? 1)
      })
      setScores(defaults)
    }
    setRationale(source?.rationale ?? '')
    setEvidence(source?.evidence ?? '')
    setConfidence(source?.confidence ?? 0.7)
    setAbstain(source?.abstained ?? false)
  }, [ws])

  const submit = useMutation((body: unknown) =>
    api.post(`/api/projects/${projectId}/tasks/${taskId}/submit?rubric_id=${ws?.rubric.id}`, body),
  )
  const draft = useMutation((body: unknown) =>
    api.post(`/api/projects/${projectId}/tasks/${taskId}/draft?rubric_id=${ws?.rubric.id}`, body),
  )
  const correct = useMutation((ratingId: string, body: unknown) =>
    api.post(`/api/projects/${projectId}/ratings/${ratingId}/correct`, body),
  )

  const locked = Boolean(ws?.submitted)

  function validate(): string | null {
    if (abstain) {
      if (!rationale.trim()) return 'An abstention requires a rationale explaining why you cannot rate this item.'
      return null
    }
    if (!ws) return 'Workspace not loaded.'
    for (const c of ws.rubric.categories) {
      const v = scores[c.key]
      if (v === undefined || v === null || v === '') return `Score required for "${c.name}".`
      if (c.scale_type !== 'categorical') {
        const num = Number(v)
        if (Number.isNaN(num)) return `"${c.name}" must be numeric.`
        if (c.min_value !== null && num < c.min_value) return `"${c.name}" must be ≥ ${c.min_value}.`
        if (c.max_value !== null && num > c.max_value) return `"${c.name}" must be ≤ ${c.max_value}.`
        if (c.scale_type === 'ordinal') {
          const allowed = (c.options ?? []).map((o) => Number(o.value))
          if (allowed.length > 0 && !allowed.includes(num))
            return `"${c.name}" must be one of ${allowed.join(', ')}.`
        }
      } else {
        const allowed = (c.options ?? []).map((o) => String(o.value))
        if (!allowed.includes(String(v))) return `"${c.name}" must be one of ${allowed.join(', ')}.`
      }
    }
    if (!rationale.trim()) return 'A written rationale is required so disagreements can be adjudicated.'
    return null
  }

  async function onSaveDraft() {
    setValidationError(null)
    setSavedNote(null)
    const res = await draft.run({ scores, rationale, evidence, confidence })
    if (res) setSavedNote('Draft saved.')
  }

  async function onSubmit() {
    setValidationError(null)
    setSavedNote(null)
    const problem = validate()
    if (problem) {
      setValidationError(problem)
      return
    }
    const body = abstain
      ? { abstained: true, scores: {}, rationale, confidence: null }
      : { scores, rationale, evidence, confidence, abstained: false }

    const res = ws?.my_rating
      ? await correct.run(ws.my_rating.id, body)
      : await submit.run(body)
    if (res) {
      onSubmitted()
      reload()
      setSavedNote(ws?.my_rating ? 'Correction saved as a new version — the original is kept in history.' : 'Rating submitted.')
    }
  }

  if (loading) return <Spinner label="Loading task…" />
  if (error) return <ErrorState message={error} onRetry={reload} />
  if (!ws) return null

  const displayError = validationError ?? submit.error ?? correct.error ?? draft.error

  return (
    <div className="space-y-5">
      <Card
        title="Item under review"
        subtitle={
          <span className="flex flex-wrap items-center gap-2">
            {ws.task.external_id && <span className="font-mono text-xs">{ws.task.external_id}</span>}
            {ws.task.model_name && <Badge tone="blue">{ws.task.model_name}</Badge>}
            {ws.task.task_type && <Badge tone="slate">{ws.task.task_type}</Badge>}
            {ws.task.language && <Badge tone="slate">{ws.task.language}</Badge>}
            {ws.blinded ? <Badge tone="amber">blinded</Badge> : <Badge tone="green">unblinded</Badge>}
          </span>
        }
      >
        <div className="space-y-4">
          <Block label="Prompt" text={ws.task.prompt} />
          <Block label="Response A" text={ws.task.response_a} />
          {ws.task.response_b && <Block label="Response B" text={ws.task.response_b} />}
          {ws.task.reference_answer && <Block label="Reference answer" text={ws.task.reference_answer} muted />}
        </div>
      </Card>

      <Card title="Rubric" subtitle={`${ws.rubric.name} · version ${ws.rubric.version}`}>
        <div className="space-y-4">
          {ws.rubric.categories.map((c) => (
            <CategoryControl
              key={c.id}
              category={c}
              value={scores[c.key]}
              disabled={locked}
              onChange={(v) => setScores((s) => ({ ...s, [c.key]: v }))}
            />
          ))}
        </div>
      </Card>

      <Card title="Your assessment" subtitle={`Signing in as ${reviewerName}`}>
        {locked && (
          <InfoNote tone="amber">
            You have already submitted this item (version {ws.my_rating?.version}). Saving changes appends a{' '}
            <strong className="font-semibold">new version</strong> — the original rating is preserved in the audit
            history and is never overwritten.
          </InfoNote>
        )}
        {ws.blinded && (
          <div className="mt-3">
            <InfoNote>
              <strong className="font-semibold">Blinded review.</strong> Other reviewers' scores and rationales are
              hidden until you submit your own rating.
            </InfoNote>
          </div>
        )}

        <div className="mt-4 space-y-4">
          <Field label="Rationale" htmlFor="rationale" hint="Explain what evidence drove your scores. Required.">
            <textarea
              id="rationale"
              className="input min-h-[100px]"
              value={rationale}
              onChange={(e) => setRationale(e.target.value)}
            />
          </Field>
          <Field label="Evidence (optional)" htmlFor="evidence" hint="Quote the exact span that supports your score.">
            <textarea
              id="evidence"
              className="input min-h-[70px]"
              value={evidence}
              onChange={(e) => setEvidence(e.target.value)}
            />
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label={`Confidence: ${(confidence * 100).toFixed(0)}%`} htmlFor="confidence">
              <input
                id="confidence"
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={confidence}
                disabled={abstain}
                onChange={(e) => setConfidence(Number(e.target.value))}
                className="w-full"
              />
            </Field>
            <label className="flex items-end gap-2 pb-2 text-sm text-slate-700">
              <input
                type="checkbox"
                className="h-4 w-4 rounded border-slate-300"
                checked={abstain}
                onChange={(e) => setAbstain(e.target.checked)}
              />
              Abstain from this item (requires a rationale)
            </label>
          </div>
        </div>

        {displayError && (
          <p className="mt-4 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700" role="alert">
            {displayError}
          </p>
        )}
        {savedNote && (
          <p className="mt-4 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700" role="status">
            {savedNote}
          </p>
        )}

        <div className="mt-5 flex flex-wrap gap-2">
          {!locked && (
            <button type="button" className="btn-secondary" onClick={onSaveDraft} disabled={draft.loading || abstain}>
              {draft.loading ? 'Saving…' : 'Save draft'}
            </button>
          )}
          <button
            type="button"
            className="btn-primary"
            onClick={onSubmit}
            disabled={submit.loading || correct.loading}
          >
            {submit.loading || correct.loading
              ? 'Saving…'
              : locked
                ? 'Save correction (new version)'
                : abstain
                  ? 'Submit abstention'
                  : 'Submit rating'}
          </button>
        </div>
      </Card>

      {!ws.blinded && ws.peer_ratings.length > 0 && (
        <Card
          title="Peer ratings (revealed after your submission)"
          subtitle="Compare your reasoning with other reviewers before any adjudication."
        >
          <div className="space-y-3">
            {ws.peer_ratings.map((p) => (
              <div key={p.id} className="rounded-lg border border-slate-200 p-3">
                <div className="mb-2 flex flex-wrap items-center gap-2">
                  <span className="text-sm font-semibold text-slate-800">{p.reviewer_name ?? p.reviewer_id.slice(0, 8)}</span>
                  {p.abstained && <Badge tone="amber">abstained</Badge>}
                  {p.confidence !== null && (
                    <span className="text-xs text-slate-500">
                      confidence <MetricValue value={p.confidence * 100} digits={0} suffix="%" />
                    </span>
                  )}
                  {p.version > 1 && <Badge tone="slate">v{p.version}</Badge>}
                </div>
                {p.scores && (
                  <dl className="mb-2 flex flex-wrap gap-2">
                    {Object.entries(p.scores).map(([k, v]) => (
                      <div key={k} className="rounded bg-slate-100 px-2 py-1 text-xs">
                        <dt className="inline text-slate-500">{k}: </dt>
                        <dd className="inline font-semibold text-slate-800">{String(v)}</dd>
                      </div>
                    ))}
                  </dl>
                )}
                {p.rationale && <p className="text-sm text-slate-600">{p.rationale}</p>}
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  )
}

function Block({ label, text, muted = false }: { label: string; text: string; muted?: boolean }) {
  const [expanded, setExpanded] = useState(false)
  const long = text.length > 700
  const shown = !long || expanded ? text : `${text.slice(0, 700)}…`
  return (
    <div>
      <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</p>
      <p className={`whitespace-pre-wrap text-sm ${muted ? 'text-slate-500' : 'text-slate-800'}`}>{shown}</p>
      {long && (
        <button type="button" className="mt-1 text-xs font-medium text-brand-600 hover:underline" onClick={() => setExpanded((v) => !v)}>
          {expanded ? 'Show less' : 'Show more'}
        </button>
      )}
    </div>
  )
}

function CategoryControl({
  category,
  value,
  disabled,
  onChange,
}: {
  category: RubricCategory
  value: ScoreValue | undefined
  disabled: boolean
  onChange: (v: ScoreValue) => void
}) {
  const anchors = useMemo(() => category.anchors ?? [], [category.anchors])

  return (
    <div className="rounded-lg border border-slate-200 p-3">
      <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-semibold text-slate-800">
          {category.name} <span className="font-mono text-[11px] text-slate-400">({category.key})</span>
        </p>
        <div className="flex items-center gap-2">
          <Badge tone="slate">{category.scale_type}</Badge>
          <Badge tone="blue">weight {category.weight}</Badge>
        </div>
      </div>
      {category.definition && <p className="mb-1 text-xs text-slate-600">{category.definition}</p>}
      {category.guidance && <p className="mb-2 text-xs italic text-slate-500">{category.guidance}</p>}

      {category.scale_type === 'categorical' ? (
        <div className="flex flex-wrap gap-2" role="radiogroup" aria-label={category.name}>
          {(category.options ?? []).map((o) => {
            const active = String(value) === String(o.value)
            return (
              <button
                key={String(o.value)}
                type="button"
                role="radio"
                aria-checked={active}
                disabled={disabled}
                onClick={() => onChange(String(o.value))}
                className={`rounded-lg border px-3 py-1.5 text-sm transition-colors disabled:opacity-60 ${
                  active
                    ? 'border-brand-600 bg-brand-600 text-white'
                    : 'border-slate-300 bg-white text-slate-700 hover:bg-slate-50'
                }`}
              >
                {o.label}
              </button>
            )
          })}
        </div>
      ) : category.scale_type === 'ordinal' ? (
        <div className="flex flex-wrap gap-2" role="radiogroup" aria-label={category.name}>
          {(category.options ?? []).map((o) => {
            const active = Number(value) === Number(o.value)
            return (
              <button
                key={String(o.value)}
                type="button"
                role="radio"
                aria-checked={active}
                disabled={disabled}
                title={o.example ?? o.label}
                onClick={() => onChange(Number(o.value))}
                className={`min-w-[3.5rem] rounded-lg border px-3 py-1.5 text-sm transition-colors disabled:opacity-60 ${
                  active
                    ? 'border-brand-600 bg-brand-600 text-white'
                    : 'border-slate-300 bg-white text-slate-700 hover:bg-slate-50'
                }`}
              >
                <span className="font-semibold">{o.value}</span>
                <span className="ml-1 text-xs opacity-80">{o.label}</span>
              </button>
            )
          })}
        </div>
      ) : (
        <div>
          <input
            type="number"
            className="input max-w-[10rem]"
            min={category.min_value ?? undefined}
            max={category.max_value ?? undefined}
            step={0.1}
            value={value === undefined ? '' : Number(value)}
            disabled={disabled}
            onChange={(e) => onChange(Number(e.target.value))}
            aria-label={category.name}
          />
          <p className="mt-1 text-[11px] text-slate-500">
            Range {category.min_value} – {category.max_value}
          </p>
        </div>
      )}

      {anchors.length > 0 && (
        <details className="mt-2">
          <summary className="cursor-pointer text-xs font-medium text-brand-600 hover:underline">
            Scoring anchors &amp; examples ({anchors.length})
          </summary>
          <ul className="mt-2 space-y-1.5">
            {anchors.map((a) => (
              <li key={String(a.value)} className="rounded bg-slate-50 px-2 py-1.5 text-xs text-slate-600">
                <span className="font-semibold text-slate-800">
                  {String(a.value)} — {a.label}
                </span>
                {a.example && <span className="block text-slate-500">{a.example}</span>}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}
