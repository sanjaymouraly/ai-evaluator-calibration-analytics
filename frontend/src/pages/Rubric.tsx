import { useState } from 'react'
import { useParams } from 'react-router-dom'
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
} from '../components/ui'
import { useAsync, useMutation, useTitle } from '../hooks'
import type { ChangeRequest, Rubric, RubricCategory, User } from '../types'

const STATUS_TONE: Record<string, string> = {
  draft: 'slate',
  active: 'green',
  superseded: 'amber',
  archived: 'slate',
  pending: 'amber',
  approved: 'green',
  rejected: 'rose',
}

export default function RubricPage() {
  const { projectId = '' } = useParams()
  useTitle('Rubric')
  const { user } = useAuth()
  const { data: rubrics, loading, error, reload } = useAsync<Rubric[]>(
    () => api.get<Rubric[]>(`/api/projects/${projectId}/rubrics`),
    [projectId],
  )
  const { data: users } = useAsync<User[]>(() => api.get<User[]>('/api/auth/users').catch(() => [] as User[]), [])
  const [showCreate, setShowCreate] = useState(false)

  const active = rubrics?.find((r) => r.status === 'active') ?? null
  const nameOf = (id: string | null) => (id ? (users?.find((u) => u.id === id)?.full_name ?? id.slice(0, 8)) : '—')

  return (
    <>
      <PageHeader
        title="Rubric"
        subtitle="Scoring criteria, scales, weights and anchors. Every change creates a new version and requires human approval — existing ratings are never altered."
        backTo={`/projects/${projectId}`}
        actions={
          can.manageRubric(user) ? (
            <button type="button" className="btn-primary" onClick={() => setShowCreate(true)}>
              + New rubric version
            </button>
          ) : undefined
        }
      />

      {loading && <Spinner label="Loading rubrics…" />}
      {error && <ErrorState message={error} onRetry={reload} />}

      {rubrics && rubrics.length === 0 && (
        <EmptyState
          title="No rubric configured"
          body="Reviewers cannot submit ratings until an active rubric exists. Create one with at least one scoring category."
          action={
            can.manageRubric(user) ? (
              <button type="button" className="btn-primary" onClick={() => setShowCreate(true)}>
                + Create rubric
              </button>
              ) : undefined
          }
        />
      )}

      {active && (
        <Card
          title={`${active.name} · v${active.version}`}
          subtitle={active.description ?? undefined}
          className="mb-5"
          actions={
            <>
              <Badge tone={STATUS_TONE[active.status]}>{active.status}</Badge>
              <span className="text-xs text-slate-500">approved by {nameOf(active.approved_by ?? null)}</span>
            </>
          }
        >
          <div className="space-y-4">
            {active.categories.map((c) => (
              <CategoryCard key={c.id} category={c} />
            ))}
          </div>
        </Card>
      )}

      {rubrics && rubrics.length > 1 && (
        <Card title="Version history" subtitle="Superseded versions are retained so historical ratings stay interpretable." className="mb-5">
          <div className="overflow-x-auto">
            <table className="table-base">
              <thead>
                <tr>
                  <th className="th" scope="col">Version</th>
                  <th className="th" scope="col">Status</th>
                  <th className="th" scope="col">Change note</th>
                  <th className="th" scope="col">Approved</th>
                  <th className="th" scope="col">Created</th>
                </tr>
              </thead>
              <tbody>
                {[...rubrics]
                  .sort((a, b) => b.version - a.version)
                  .map((r) => (
                    <tr key={r.id}>
                      <td className="td font-semibold">v{r.version}</td>
                      <td className="td">
                        <Badge tone={STATUS_TONE[r.status] ?? 'slate'}>{r.status}</Badge>
                      </td>
                      <td className="td text-xs text-slate-600">{r.change_note ?? '—'}</td>
                      <td className="td text-xs text-slate-500">
                        {r.approved_at ? new Date(r.approved_at).toLocaleString() : '—'}
                      </td>
                      <td className="td text-xs text-slate-500">{new Date(r.created_at).toLocaleDateString()}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      <ChangeRequests projectId={projectId} rubrics={rubrics ?? []} onChanged={reload} />

      <CreateRubricModal
        open={showCreate}
        projectId={projectId}
        existing={active}
        onClose={() => setShowCreate(false)}
        onCreated={reload}
      />
    </>
  )
}

function CategoryCard({ category }: { category: RubricCategory }) {
  return (
    <div className="rounded-lg border border-slate-200 p-3">
      <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-semibold text-slate-800">
          {category.name} <span className="font-mono text-[11px] text-slate-400">({category.key})</span>
        </p>
        <div className="flex gap-2">
          <Badge tone="slate">{category.scale_type}</Badge>
          <Badge tone="blue">weight {category.weight}</Badge>
        </div>
      </div>
      {category.definition ? (
        <p className="mb-1 text-sm text-slate-600">{category.definition}</p>
      ) : (
        <p className="mb-1 text-sm italic text-amber-700">No definition — a common source of disagreement.</p>
      )}
      {category.guidance && <p className="mb-2 text-xs italic text-slate-500">{category.guidance}</p>}

      {category.options && category.options.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {category.options.map((o) => (
            <span key={String(o.value)} className="rounded bg-slate-100 px-2 py-1 text-xs text-slate-700" title={o.example ?? undefined}>
              <strong>{String(o.value)}</strong> · {o.label}
            </span>
          ))}
        </div>
      )}
      {category.scale_type === 'numerical' && (
        <p className="mt-2 text-xs text-slate-500">
          Continuous range {category.min_value} – {category.max_value}
        </p>
      )}
      {category.anchors && category.anchors.length > 0 && (
        <details className="mt-2">
          <summary className="cursor-pointer text-xs font-medium text-brand-600 hover:underline">
            Anchors ({category.anchors.length})
          </summary>
          <ul className="mt-1.5 space-y-1">
            {category.anchors.map((a) => (
              <li key={String(a.value)} className="rounded bg-slate-50 px-2 py-1 text-xs text-slate-600">
                <strong>{String(a.value)} — {a.label}</strong>
                {a.example && <span className="block text-slate-500">{a.example}</span>}
              </li>
            ))}
          </ul>
        </details>
      )}
      {(!category.anchors || category.anchors.length === 0) && (
        <p className="mt-2 text-xs text-amber-700">No scoring anchors defined for this category.</p>
      )}
    </div>
  )
}

function ChangeRequests({
  projectId,
  rubrics,
  onChanged,
}: {
  projectId: string
  rubrics: Rubric[]
  onChanged: () => void
}) {
  const { user } = useAuth()
  const { data: requests, loading, reload } = useAsync<ChangeRequest[]>(async () => {
    // Change requests live under the rubric router; fetch for the active rubric.
    const active = rubrics.find((r) => r.status === 'active') ?? rubrics[0]
    if (!active) return []
    return api.get<ChangeRequest[]>(`/api/projects/${projectId}/rubrics/change-requests`).catch(() => [])
  }, [projectId, rubrics])

  const review = useMutation((id: string, decision: string, note: string) =>
    api.post(`/api/projects/${projectId}/rubrics/change-requests/${id}/review?decision=${decision}&note=${encodeURIComponent(note)}`),
  )
  const apply = useMutation((id: string) => api.post<Rubric>(`/api/projects/${projectId}/rubrics/change-requests/${id}/apply`))
  void loading

  return (
    <Card
      title="Rubric change requests"
      subtitle="Proposals require explicit human approval. Applying an approved request creates a new rubric version; historical ratings keep their original version."
      actions={<button type="button" className="btn-secondary" onClick={reload}>Refresh</button>}
    >
      {requests && requests.length === 0 && <EmptyState title="No change requests" body="Proposals can be raised from the Rubric insights page." />}
      {requests && requests.length > 0 && (
        <ul className="space-y-3">
          {requests.map((r) => (
            <li key={r.id} className="rounded-lg border border-slate-200 p-3">
              <div className="mb-2 flex flex-wrap items-center gap-2">
                <Badge tone={STATUS_TONE[r.status] ?? 'slate'}>{r.status}</Badge>
                <Badge tone="slate">{r.source}</Badge>
                {r.is_ai_generated && <Badge tone="violet">AI-suggested</Badge>}
                <span className="text-xs text-slate-500">{new Date(r.created_at).toLocaleString()}</span>
              </div>
              <p className="mb-2 text-sm text-slate-700">{r.rationale}</p>
              <pre className="mb-2 overflow-x-auto rounded bg-slate-50 p-2 font-mono text-[11px] text-slate-600">
                {JSON.stringify(r.proposed_changes, null, 2)}
              </pre>
              {r.status === 'pending' && can.manageRubric(user) && (
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    className="btn-primary px-3 py-1.5 text-xs"
                    disabled={review.loading}
                    onClick={async () => {
                      await review.run(r.id, 'approved', 'Approved via rubric page')
                      reload()
                      onChanged()
                    }}
                  >
                    Approve
                  </button>
                  <button
                    type="button"
                    className="btn-secondary px-3 py-1.5 text-xs"
                    disabled={review.loading}
                    onClick={async () => {
                      await review.run(r.id, 'rejected', 'Rejected via rubric page')
                      reload()
                      onChanged()
                    }}
                  >
                    Reject
                  </button>
                </div>
              )}
              {r.status === 'approved' && !r.review_note?.includes('applied') && can.manageRubric(user) && (
                <button
                  type="button"
                  className="btn-primary mt-2 px-3 py-1.5 text-xs"
                  disabled={apply.loading}
                  onClick={async () => {
                    const res = await apply.run(r.id)
                    if (res) {
                      reload()
                      onChanged()
                    }
                  }}
                >
                  Apply as new version
                </button>
              )}
              {(review.error || apply.error) && (
                <p className="mt-2 text-xs text-rose-600">{review.error ?? apply.error}</p>
              )}
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

interface DraftCategory {
  key: string
  name: string
  scale_type: 'categorical' | 'ordinal' | 'numerical'
  definition: string
  weight: number
  min_value: number
  max_value: number
  options: string
  anchors: string
}

const EMPTY_CATEGORY: DraftCategory = {
  key: '',
  name: '',
  scale_type: 'ordinal',
  definition: '',
  weight: 1,
  min_value: 1,
  max_value: 5,
  options: '1,2,3,4,5',
  anchors: '',
}

function CreateRubricModal({
  open,
  projectId,
  existing,
  onClose,
  onCreated,
}: {
  open: boolean
  projectId: string
  existing: Rubric | null
  onClose: () => void
  onCreated: () => void
}) {
  const [name, setName] = useState(existing?.name ?? '')
  const [description, setDescription] = useState(existing?.description ?? '')
  const [categories, setCategories] = useState<DraftCategory[]>(
    existing
      ? existing.categories.map((c) => ({
          key: c.key,
          name: c.name,
          scale_type: c.scale_type,
          definition: c.definition ?? '',
          weight: c.weight,
          min_value: c.min_value ?? 1,
          max_value: c.max_value ?? 5,
          options: (c.options ?? []).map((o) => String(o.value)).join(','),
          anchors: (c.anchors ?? [])
            .map((a) => `${a.value}:${a.label}${a.example ? `:${a.example}` : ''}`)
            .join(' | '),
        }))
      : [{ ...EMPTY_CATEGORY, key: 'accuracy', name: 'Accuracy' }],
  )
  const create = useMutation((payload: unknown) => api.post<Rubric>(`/api/projects/${projectId}/rubrics`, payload))
  const activate = useMutation((id: string) =>
    api.post(`/api/projects/${projectId}/rubrics/${id}/activate`, { change_note: 'Created via UI' }),
  )

  function parseOptions(raw: string, scaleType: string) {
    return raw
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean)
      .map((s) => (scaleType === 'categorical' ? { value: s, label: s } : { value: Number(s), label: s }))
  }

  function parseAnchors(raw: string) {
    return raw
      .split('|')
      .map((s) => s.trim())
      .filter(Boolean)
      .map((entry) => {
        const [value, label, example] = entry.split(':').map((x) => x?.trim())
        return { value: Number.isNaN(Number(value)) ? value : Number(value), label: label ?? value, example }
      })
  }

  async function submit() {
    const payload = {
      name,
      description: description || null,
      categories: categories.map((c, i) => ({
        key: c.key.trim().toLowerCase(),
        name: c.name.trim(),
        definition: c.definition.trim() || null,
        scale_type: c.scale_type,
        weight: c.weight,
        min_value: c.scale_type === 'categorical' ? null : c.min_value,
        max_value: c.scale_type === 'categorical' ? null : c.max_value,
        options: c.scale_type === 'numerical' ? null : parseOptions(c.options, c.scale_type),
        anchors: c.anchors.trim() ? parseAnchors(c.anchors) : null,
        item_order: i,
      })),
    }
    const created = await create.run(payload)
    if (created) {
      const activated = await activate.run(created.id)
      if (activated) {
        onCreated()
        onClose()
      }
    }
  }

  return (
    <Modal
      open={open}
      title={existing ? `New version of “${existing.name}”` : 'Create rubric'}
      onClose={onClose}
      wide
      footer={
        <>
          <button type="button" className="btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button type="button" className="btn-primary" onClick={submit} disabled={create.loading || activate.loading || !name.trim()}>
            {create.loading || activate.loading ? 'Saving…' : 'Create & activate'}
          </button>
        </>
      }
    >
      <InfoNote tone="amber">
        Creating a new version <strong className="font-semibold">supersedes</strong> the current one but never deletes
        it. Ratings already submitted keep referencing the version they were scored against.
      </InfoNote>

      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <Field label="Rubric name" htmlFor="r-name">
          <input id="r-name" className="input" value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="Description" htmlFor="r-desc">
          <input id="r-desc" className="input" value={description} onChange={(e) => setDescription(e.target.value)} />
        </Field>
      </div>

      <div className="mt-5 space-y-4">
        {categories.map((c, idx) => (
          <div key={idx} className="rounded-lg border border-slate-200 p-3">
            <div className="mb-3 flex items-center justify-between">
              <p className="text-sm font-semibold text-slate-800">Category {idx + 1}</p>
              {categories.length > 1 && (
                <button
                  type="button"
                  className="btn-ghost px-2 py-1 text-xs text-rose-600"
                  onClick={() => setCategories((cs) => cs.filter((_, i) => i !== idx))}
                >
                  Remove
                </button>
              )}
            </div>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Field label="Key" htmlFor={`c-key-${idx}`} hint="lowercase, a-z 0-9 _">
                <input
                  id={`c-key-${idx}`}
                  className="input font-mono text-xs"
                  value={c.key}
                  onChange={(e) => setCategories((cs) => cs.map((x, i) => (i === idx ? { ...x, key: e.target.value } : x)))}
                />
              </Field>
              <Field label="Display name" htmlFor={`c-name-${idx}`}>
                <input
                  id={`c-name-${idx}`}
                  className="input"
                  value={c.name}
                  onChange={(e) => setCategories((cs) => cs.map((x, i) => (i === idx ? { ...x, name: e.target.value } : x)))}
                />
              </Field>
              <Field label="Scale type" htmlFor={`c-scale-${idx}`}>
                <select
                  id={`c-scale-${idx}`}
                  className="input"
                  value={c.scale_type}
                  onChange={(e) =>
                    setCategories((cs) =>
                      cs.map((x, i) =>
                        i === idx
                          ? {
                              ...x,
                              scale_type: e.target.value as DraftCategory['scale_type'],
                              options: e.target.value === 'categorical' ? 'safe,borderline,unsafe' : '1,2,3,4,5',
                            }
                          : x,
                      ),
                    )
                  }
                >
                  <option value="ordinal">Ordinal (1–5 style)</option>
                  <option value="categorical">Categorical (labels)</option>
                  <option value="numerical">Numerical (continuous)</option>
                </select>
              </Field>
              <Field label="Weight" htmlFor={`c-weight-${idx}`}>
                <input
                  id={`c-weight-${idx}`}
                  type="number"
                  step={0.1}
                  min={0.1}
                  className="input"
                  value={c.weight}
                  onChange={(e) => setCategories((cs) => cs.map((x, i) => (i === idx ? { ...x, weight: Number(e.target.value) } : x)))}
                />
              </Field>
            </div>

            <div className="mt-3">
              <Field label="Definition" htmlFor={`c-def-${idx}`} hint="Operational definition — what exactly is being judged?">
                <textarea
                  id={`c-def-${idx}`}
                  className="input min-h-[60px]"
                  value={c.definition}
                  onChange={(e) => setCategories((cs) => cs.map((x, i) => (i === idx ? { ...x, definition: e.target.value } : x)))}
                />
              </Field>
            </div>

            {c.scale_type !== 'numerical' && (
              <div className="mt-3">
                <Field
                  label="Options (comma separated)"
                  htmlFor={`c-opt-${idx}`}
                  hint={c.scale_type === 'categorical' ? 'Labels, e.g. safe,borderline,unsafe' : 'Ordered numbers, e.g. 1,2,3,4,5'}
                >
                  <input
                    id={`c-opt-${idx}`}
                    className="input font-mono text-xs"
                    value={c.options}
                    onChange={(e) => setCategories((cs) => cs.map((x, i) => (i === idx ? { ...x, options: e.target.value } : x)))}
                  />
                </Field>
              </div>
            )}

            {c.scale_type !== 'categorical' && (
              <div className="mt-3 grid gap-3 sm:grid-cols-2">
                <Field label="Minimum" htmlFor={`c-min-${idx}`}>
                  <input
                    id={`c-min-${idx}`}
                    type="number"
                    step={0.1}
                    className="input"
                    value={c.min_value}
                    onChange={(e) => setCategories((cs) => cs.map((x, i) => (i === idx ? { ...x, min_value: Number(e.target.value) } : x)))}
                  />
                </Field>
                <Field label="Maximum" htmlFor={`c-max-${idx}`}>
                  <input
                    id={`c-max-${idx}`}
                    type="number"
                    step={0.1}
                    className="input"
                    value={c.max_value}
                    onChange={(e) => setCategories((cs) => cs.map((x, i) => (i === idx ? { ...x, max_value: Number(e.target.value) } : x)))}
                  />
                </Field>
              </div>
            )}

            <div className="mt-3">
              <Field
                label="Anchors (optional)"
                htmlFor={`c-anch-${idx}`}
                hint="Format: value:label:example separated by | — e.g. 5:Fully accurate:All claims verifiable | 1:Mostly false:Central claim wrong"
              >
                <input
                  id={`c-anch-${idx}`}
                  className="input font-mono text-xs"
                  value={c.anchors}
                  onChange={(e) => setCategories((cs) => cs.map((x, i) => (i === idx ? { ...x, anchors: e.target.value } : x)))}
                />
              </Field>
            </div>
          </div>
        ))}
      </div>

      <button
        type="button"
        className="btn-secondary mt-4"
        onClick={() => setCategories((cs) => [...cs, { ...EMPTY_CATEGORY }])}
      >
        + Add category
      </button>

      {(create.error || activate.error) && (
        <p className="mt-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700" role="alert">
          {create.error ?? activate.error}
        </p>
      )}
    </Modal>
  )
}
