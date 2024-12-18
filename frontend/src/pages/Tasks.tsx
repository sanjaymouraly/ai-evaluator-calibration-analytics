import { useEffect, useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import { api, buildQuery } from '../api/client'
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
import type { ImportResult, Project, Task, User } from '../types'

const STATUS_TONE: Record<string, string> = {
  pending: 'slate',
  in_progress: 'amber',
  completed: 'green',
  adjudicated: 'violet',
}

export default function TasksPage() {
  const { projectId = '' } = useParams()
  useTitle('Tasks & data')
  const [q, setQ] = useState('')
  const [status, setStatus] = useState('')
  const [model, setModel] = useState('')
  const [showImport, setShowImport] = useState(false)
  const [showAssign, setShowAssign] = useState(false)

  const { data: project } = useAsync<Project>(() => api.get<Project>(`/api/projects/${projectId}`), [projectId])
  const { data: filters } = useAsync<{ models: string[] }>(
    () => api.get<{ models: string[] }>(`/api/projects/${projectId}/analytics/filters`),
    [projectId],
  )
  const { data: tasks, loading, error, reload } = useAsync<Task[]>(
    () => api.get<Task[]>(`/api/projects/${projectId}/tasks${buildQuery({ q, status, model_name: model, limit: 200 })}`),
    [projectId, q, status, model],
  )
  const { data: datasets } = useAsync<Array<Record<string, unknown>>>(
    () => api.get(`/api/projects/${projectId}/datasets-summary`),
    [projectId],
  )

  const counts = useMemo(() => {
    const base = { total: tasks?.length ?? 0, gold: 0, adjudicated: 0, completed: 0 }
    tasks?.forEach((t) => {
      if (t.gold_label) base.gold += 1
      if (t.status === 'adjudicated') base.adjudicated += 1
      if (t.status === 'completed') base.completed += 1
    })
    return base
  }, [tasks])

  return (
    <>
      <PageHeader
        title="Tasks & data"
        subtitle="Import evaluation items, review dataset provenance, assign reviewers and approve gold-standard labels."
        backTo={`/projects/${projectId}`}
        actions={
          <>
            <button type="button" className="btn-secondary" onClick={() => setShowAssign(true)}>
              Assign reviewers
            </button>
            <button type="button" className="btn-primary" onClick={() => setShowImport(true)}>
              Import dataset
            </button>
          </>
        }
      />

      <div className="mb-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Tasks" value={counts.total} />
        <StatCard label="Rated (complete)" value={counts.completed} tone="good" />
        <StatCard label="Adjudicated" value={counts.adjudicated} tone={counts.adjudicated ? 'good' : 'neutral'} />
        <StatCard label="Gold-labelled" value={counts.gold} hint="Used for calibration & accuracy" />
      </div>

      {datasets && datasets.length > 0 && (
        <Card title="Datasets" subtitle="Import provenance is retained for every dataset." className="mb-5">
          <div className="overflow-x-auto">
            <table className="table-base">
              <thead>
                <tr>
                  <th className="th" scope="col">Name</th>
                  <th className="th" scope="col">Source file</th>
                  <th className="th" scope="col">Format</th>
                  <th className="th text-right" scope="col">Items</th>
                  <th className="th" scope="col">Imported</th>
                </tr>
              </thead>
              <tbody>
                {datasets.map((d) => (
                  <tr key={String(d.id)}>
                    <td className="td font-medium text-slate-800">{String(d.name)}</td>
                    <td className="td font-mono text-xs">{String(d.source_file_name ?? '—')}</td>
                    <td className="td">
                      <Badge tone="slate">{String(d.source_format)}</Badge>
                    </td>
                    <td className="td text-right tabular-nums">{String(d.item_count)}</td>
                    <td className="td text-xs text-slate-500">{new Date(String(d.created_at)).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      <Card
        title="Evaluation tasks"
        subtitle="Search and filter the items in this project."
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <input
              className="input w-44"
              placeholder="Search prompts…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              aria-label="Search tasks"
            />
            <select className="input w-auto" value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Filter by status">
              <option value="">All statuses</option>
              <option value="pending">Pending</option>
              <option value="in_progress">In progress</option>
              <option value="completed">Completed</option>
              <option value="adjudicated">Adjudicated</option>
            </select>
            {filters && filters.models.length > 0 && (
              <select className="input w-auto" value={model} onChange={(e) => setModel(e.target.value)} aria-label="Filter by model">
                <option value="">All models</option>
                {filters.models.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
            )}
          </div>
        }
      >
        {loading && <Spinner label="Loading tasks…" />}
        {error && <ErrorState message={error} onRetry={reload} />}
        {tasks && tasks.length === 0 && (
          <EmptyState
            title="No tasks match"
            body="Import a CSV, JSON or JSONL dataset to create evaluation items."
            action={
              <button type="button" className="btn-primary" onClick={() => setShowImport(true)}>
                Import dataset
              </button>
            }
          />
        )}
        {tasks && tasks.length > 0 && (
          <div className="space-y-3">
            {tasks.map((t) => (
              <TaskRow key={t.id} task={t} projectId={projectId} onChanged={reload} />
            ))}
          </div>
        )}
      </Card>

      <ImportModal
        open={showImport}
        projectId={projectId}
        mode={project?.mode ?? 'single'}
        onClose={() => setShowImport(false)}
        onImported={reload}
      />
      <AssignModal open={showAssign} projectId={projectId} onClose={() => setShowAssign(false)} onAssigned={reload} />
    </>
  )
}

function TaskRow({ task, projectId, onChanged }: { task: Task; projectId: string; onChanged: () => void }) {
  const [expanded, setExpanded] = useState(false)
  const [goldOpen, setGoldOpen] = useState(false)

  return (
    <article className="rounded-lg border border-slate-200">
      <div className="flex flex-wrap items-start justify-between gap-3 p-3">
        <div className="min-w-0 flex-1">
          <div className="mb-1 flex flex-wrap items-center gap-2">
            <Badge tone={STATUS_TONE[task.status] ?? 'slate'}>{task.status}</Badge>
            {task.external_id && <span className="font-mono text-[11px] text-slate-400">{task.external_id}</span>}
            {task.model_name && <Badge tone="blue">{task.model_name}</Badge>}
            {task.task_type && <Badge tone="slate">{task.task_type}</Badge>}
            {task.language && <Badge tone="slate">{task.language}</Badge>}
            {task.gold_label && <Badge tone="green">gold label</Badge>}
          </div>
          <p className="line-clamp-2 text-sm text-slate-800">{task.prompt}</p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <button type="button" className="btn-secondary" onClick={() => setGoldOpen(true)}>
            {task.gold_label ? 'Edit gold label' : 'Set gold label'}
          </button>
          <button
            type="button"
            className="btn-ghost"
            onClick={() => setExpanded((v) => !v)}
            aria-expanded={expanded}
          >
            {expanded ? 'Hide' : 'Details'}
          </button>
        </div>
      </div>
      {expanded && (
        <div className="space-y-3 border-t border-slate-200 bg-slate-50/60 p-3 text-sm">
          <div>
            <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Prompt</p>
            <p className="whitespace-pre-wrap text-slate-700">{task.prompt}</p>
          </div>
          <div>
            <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Response A</p>
            <p className="whitespace-pre-wrap text-slate-700">{task.response_a}</p>
          </div>
          {task.response_b && (
            <div>
              <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Response B</p>
              <p className="whitespace-pre-wrap text-slate-700">{task.response_b}</p>
            </div>
          )}
          {task.reference_answer && (
            <div>
              <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Reference answer</p>
              <p className="whitespace-pre-wrap text-slate-700">{task.reference_answer}</p>
            </div>
          )}
          {task.gold_label && (
            <div>
              <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Gold label</p>
              <pre className="overflow-x-auto rounded bg-white p-2 font-mono text-xs text-slate-700">
                {JSON.stringify(task.gold_label, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}
      {goldOpen && (
        <GoldLabelModal
          open={goldOpen}
          projectId={projectId}
          task={task}
          onClose={() => setGoldOpen(false)}
          onSaved={onChanged}
        />
      )}
    </article>
  )
}

function GoldLabelModal({
  open,
  projectId,
  task,
  onClose,
  onSaved,
}: {
  open: boolean
  projectId: string
  task: Task
  onClose: () => void
  onSaved: () => void
}) {
  const { data: rubrics } = useAsync<Array<{ id: string; status: string; categories: Array<Record<string, unknown>> }>>(
    () => (open ? api.get(`/api/projects/${projectId}/rubrics`) : Promise.resolve([])),
    [open, projectId],
  )
  // Memoised so its identity is stable across renders (keeps the
  // downstream useMemo/useEffect dependency arrays honest).
  const categories = useMemo(
    () => {
      const active = rubrics?.find((r) => r.status === 'active') ?? rubrics?.[0]
      return (active?.categories ?? []) as Array<{
        key: string
        name: string
        scale_type: string
        min_value: number | null
        max_value: number | null
        options: Array<{ value: number | string; label: string }> | null
      }>
    },
    [rubrics],
  )

  const initial = useMemo(() => {
    const existing = (task.gold_label?.scores ?? {}) as Record<string, number | string>
    const out: Record<string, number | string> = {}
    categories.forEach((c) => {
      out[c.key] = existing[c.key] ?? (c.scale_type === 'categorical' ? (c.options?.[0]?.value ?? '') : (c.min_value ?? 1))
    })
    return out
  }, [categories, task.gold_label])

  const [scores, setScores] = useState<Record<string, number | string>>(initial)
  const [rationale, setRationale] = useState(task.gold_label?.rationale ?? '')
  const save = useMutation((payload: unknown) =>
    api.post(`/api/projects/${projectId}/tasks/${task.id}/gold-label`, payload),
  )

  // Re-sync local state when the rubric categories load or the task changes.
  // NOTE: this must be an effect — calling a state setter during render
  // (e.g. inside useMemo) crashes React.
  useEffect(() => {
    setScores(initial)
  }, [initial])
  useEffect(() => {
    setRationale(task.gold_label?.rationale ?? '')
  }, [task.gold_label])

  async function submit() {
    const res = await save.run({ scores, rationale: rationale || null })
    if (res !== null) {
      onSaved()
      onClose()
    }
  }

  return (
    <Modal
      open={open}
      title="Expert-approved reference label"
      onClose={onClose}
      wide
      footer={
        <>
          <button type="button" className="btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button type="button" className="btn-primary" onClick={submit} disabled={save.loading || categories.length === 0}>
            {save.loading ? 'Saving…' : 'Approve gold label'}
          </button>
        </>
      }
    >
      <InfoNote tone="amber">
        Gold labels are used to measure reviewer <strong className="font-semibold">accuracy</strong> and to run
        calibration sessions. They never overwrite reviewer ratings — original scores stay intact.
      </InfoNote>
      {categories.length === 0 && (
        <p className="mt-3 text-sm text-slate-500">No active rubric configured yet.</p>
      )}
      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        {categories.map((c) => (
          <Field key={c.key} label={`${c.name} (${c.key})`} htmlFor={`gold-${c.key}`}>
            {c.scale_type === 'categorical' ? (
              <select
                id={`gold-${c.key}`}
                className="input"
                value={String(scores[c.key] ?? '')}
                onChange={(e) => setScores((s) => ({ ...s, [c.key]: e.target.value }))}
              >
                {(c.options ?? []).map((o) => (
                  <option key={String(o.value)} value={String(o.value)}>
                    {o.label}
                  </option>
                ))}
              </select>
            ) : (
              <input
                id={`gold-${c.key}`}
                type="number"
                step={c.scale_type === 'ordinal' ? 1 : 0.1}
                min={c.min_value ?? undefined}
                max={c.max_value ?? undefined}
                className="input"
                value={Number(scores[c.key] ?? 0)}
                onChange={(e) => setScores((s) => ({ ...s, [c.key]: Number(e.target.value) }))}
              />
            )}
          </Field>
        ))}
        <div className="sm:col-span-2">
          <Field label="Rationale (optional)" htmlFor="gold-rationale">
            <textarea
              id="gold-rationale"
              className="input min-h-[70px]"
              value={rationale}
              onChange={(e) => setRationale(e.target.value)}
            />
          </Field>
        </div>
      </div>
      {save.error && (
        <p className="mt-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700" role="alert">
          {save.error}
        </p>
      )}
    </Modal>
  )
}

function ImportModal({
  open,
  projectId,
  mode,
  onClose,
  onImported,
}: {
  open: boolean
  projectId: string
  mode: string
  onClose: () => void
  onImported: () => void
}) {
  const [content, setContent] = useState('')
  const [filename, setFilename] = useState('')
  const [format, setFormat] = useState<'csv' | 'json' | 'jsonl'>('csv')
  const [result, setResult] = useState<ImportResult | null>(null)
  const [dryBusy, setDryBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const runImport = useMutation((dry: boolean) =>
    api.post<ImportResult>(`/api/projects/${projectId}/import`, {
      filename: filename || `upload.${format}`,
      file_format: format,
      content,
      dry_run: dry,
    }),
  )

  function reset() {
    setContent('')
    setFilename('')
    setResult(null)
    setErr(null)
  }

  async function onFile(file: File) {
    setErr(null)
    const ext = file.name.split('.').pop()?.toLowerCase()
    const detected = ext === 'jsonl' ? 'jsonl' : ext === 'json' ? 'json' : 'csv'
    setFormat(detected)
    setFilename(file.name)
    if (file.size > 25 * 1024 * 1024) {
      setErr('File exceeds the 25 MB limit.')
      return
    }
    const text = await file.text()
    setContent(text)
  }

  async function validate() {
    setDryBusy(true)
    setErr(null)
    setResult(null)
    try {
      const res = await api.post<ImportResult>(`/api/projects/${projectId}/import`, {
        filename: filename || `upload.${format}`,
        file_format: format,
        content,
        dry_run: true,
      })
      setResult(res)
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setDryBusy(false)
    }
  }

  async function commit() {
    const res = await runImport.run(false)
    if (res) {
      setResult(res)
      onImported()
    }
  }

  return (
    <Modal
      open={open}
      title="Import dataset"
      onClose={() => {
        reset()
        onClose()
      }}
      wide
      footer={
        <>
          <button
            type="button"
            className="btn-secondary"
            onClick={() => {
              reset()
              onClose()
            }}
          >
            Close
          </button>
          <button type="button" className="btn-secondary" onClick={validate} disabled={!content || dryBusy}>
            {dryBusy ? 'Validating…' : 'Validate (dry run)'}
          </button>
          <button
            type="button"
            className="btn-primary"
            onClick={commit}
            disabled={!content || runImport.loading || (result ? result.valid_rows === 0 : false)}
          >
            {runImport.loading ? 'Importing…' : 'Import rows'}
          </button>
        </>
      }
    >
      <div className="space-y-4">
        <InfoNote>
          Columns are auto-mapped (<code className="font-mono">prompt/question/input</code>,{' '}
          <code className="font-mono">response/answer/output</code>, <code className="font-mono">model</code>,{' '}
          <code className="font-mono">reference_answer</code>…). Unmapped columns are preserved as task metadata.
          Re-importing the same file is safe: duplicates are skipped, never overwritten.
          {mode === 'pairwise' && ' This project is pairwise — include a response_b column.'}
        </InfoNote>

        <Field label="File" htmlFor="import-file" hint="CSV, JSON (array or {items: [...]}) or JSONL, up to 25 MB.">
          <input
            id="import-file"
            type="file"
            accept=".csv,.json,.jsonl,text/csv,application/json"
            className="input"
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f) void onFile(f)
            }}
          />
        </Field>

        <div className="grid gap-4 sm:grid-cols-3">
          <Field label="Format" htmlFor="import-format">
            <select
              id="import-format"
              className="input"
              value={format}
              onChange={(e) => setFormat(e.target.value as 'csv' | 'json' | 'jsonl')}
            >
              <option value="csv">CSV</option>
              <option value="json">JSON</option>
              <option value="jsonl">JSONL</option>
            </select>
          </Field>
          <div className="sm:col-span-2">
            <Field label="File name (used for provenance)" htmlFor="import-name">
              <input id="import-name" className="input" value={filename} onChange={(e) => setFilename(e.target.value)} />
            </Field>
          </div>
        </div>

        <Field label="Or paste content" htmlFor="import-content">
          <textarea
            id="import-content"
            className="input min-h-[140px] font-mono text-xs"
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder={'prompt,response,model_name\nWhy is the sky blue?,Rayleigh scattering…,Atlas-Mini'}
          />
        </Field>

        {err && (
          <p className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700" role="alert">
            {err}
          </p>
        )}
        {runImport.error && (
          <p className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700" role="alert">
            {runImport.error}
          </p>
        )}

        {result && (
          <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
            <div className="mb-2 flex flex-wrap gap-2">
              <Badge tone={result.dry_run ? 'amber' : 'green'}>{result.dry_run ? 'Dry run' : 'Imported'}</Badge>
              <Badge tone="slate">{result.total_rows} rows</Badge>
              <Badge tone="green">{result.valid_rows} valid</Badge>
              <Badge tone={result.error_rows ? 'rose' : 'slate'}>{result.error_rows} errors</Badge>
              <Badge tone={result.duplicates_skipped ? 'amber' : 'slate'}>
                {result.duplicates_skipped} duplicates skipped
              </Badge>
            </div>
            {result.errors.length > 0 && (
              <ul className="mb-2 max-h-32 space-y-1 overflow-y-auto text-xs text-rose-700">
                {result.errors.slice(0, 40).map((e, i) => (
                  <li key={i}>
                    Row {e.row}: {e.error}
                  </li>
                ))}
              </ul>
            )}
            {result.preview.length > 0 && (
              <div className="max-h-52 overflow-auto rounded border border-slate-200 bg-white">
                <table className="table-base">
                  <thead>
                    <tr>
                      <th className="th" scope="col">#</th>
                      <th className="th" scope="col">Status</th>
                      <th className="th" scope="col">Preview</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.preview.slice(0, 25).map((row) => (
                      <tr key={row.row_number}>
                        <td className="td tabular-nums">{row.row_number}</td>
                        <td className="td">
                          {row.valid ? <Badge tone="green">ok</Badge> : <Badge tone="rose">invalid</Badge>}
                        </td>
                        <td className="td font-mono text-[11px]">
                          {row.errors.length > 0 ? row.errors.join('; ') : JSON.stringify(row.data).slice(0, 140)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </div>
    </Modal>
  )
}

function AssignModal({
  open,
  projectId,
  onClose,
  onAssigned,
}: {
  open: boolean
  projectId: string
  onClose: () => void
  onAssigned: () => void
}) {
  const { data: users } = useAsync<User[]>(
    () => (open ? api.get<User[]>(`/api/projects/${projectId}/potential-reviewers`) : Promise.resolve([])),
    [open, projectId],
  )
  const { data: members } = useAsync<Array<{ user_id: string; role_on_project: string }>>(
    () => (open ? api.get(`/api/projects/${projectId}/members`) : Promise.resolve([])),
    [open, projectId],
  )
  const [selected, setSelected] = useState<string[]>([])
  const [conflicts, setConflicts] = useState<string[]>([])
  const assign = useMutation((payload: unknown) => api.post(`/api/projects/${projectId}/assign`, payload))
  const addMember = useMutation((userId: string) =>
    api.post(`/api/projects/${projectId}/members`, { user_id: userId, role_on_project: 'reviewer' }),
  )

  const memberIds = new Set((members ?? []).map((m) => m.user_id))
  const candidates = users ?? []

  async function submit() {
    const res = await assign.run({ reviewer_ids: selected, conflict_user_ids: conflicts })
    if (res) {
      onAssigned()
      onClose()
      setSelected([])
      setConflicts([])
    }
  }

  return (
    <Modal
      open={open}
      title="Assign reviewers"
      onClose={onClose}
      wide
      footer={
        <>
          <button type="button" className="btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button type="button" className="btn-primary" onClick={submit} disabled={assign.loading || selected.length === 0}>
            {assign.loading ? 'Assigning…' : `Assign ${selected.length} reviewer(s)`}
          </button>
        </>
      }
    >
      <InfoNote>
        Assignments are round-robin balanced by current workload, always blinded, and reviewers marked as conflicted are
        excluded. Existing assignments are never duplicated.
      </InfoNote>

      {assign.error && (
        <p className="mt-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700" role="alert">
          {assign.error}
        </p>
      )}

      <div className="mt-4 max-h-80 space-y-1 overflow-y-auto">
        {candidates.map((u) => {
          const isMember = memberIds.has(u.id)
          return (
            <div key={u.id} className="flex flex-wrap items-center gap-3 rounded-lg border border-slate-200 p-2.5">
              <label className="flex min-w-0 flex-1 items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  className="h-4 w-4 rounded border-slate-300"
                  checked={selected.includes(u.id)}
                  onChange={(e) =>
                    setSelected((s) => (e.target.checked ? [...s, u.id] : s.filter((x) => x !== u.id)))
                  }
                />
                <span className="truncate font-medium text-slate-800">{u.full_name}</span>
                <span className="truncate text-xs text-slate-500">{u.email}</span>
                <Badge tone="slate">{u.role}</Badge>
                {!isMember && <Badge tone="amber">not a member</Badge>}
              </label>
              <label className="flex items-center gap-1.5 text-xs text-slate-600">
                <input
                  type="checkbox"
                  className="h-3.5 w-3.5 rounded border-slate-300"
                  checked={conflicts.includes(u.id)}
                  onChange={(e) =>
                    setConflicts((s) => (e.target.checked ? [...s, u.id] : s.filter((x) => x !== u.id)))
                  }
                />
                conflict of interest
              </label>
              {!isMember && (
                <button
                  type="button"
                  className="btn-secondary px-2 py-1 text-xs"
                  disabled={addMember.loading}
                  onClick={async () => {
                    await addMember.run(u.id)
                  }}
                >
                  Add to project
                </button>
              )}
            </div>
          )
        })}
        {candidates.length === 0 && <p className="py-6 text-center text-sm text-slate-500">No users found.</p>}
      </div>
      {addMember.error && <p className="mt-2 text-xs text-rose-600">{addMember.error}</p>}
      {assign.error && <p className="mt-2 text-xs text-rose-600">{assign.error}</p>}
    </Modal>
  )
}
