import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { useAsync, useMutation, useTitle } from '../hooks'
import type { Project, ProjectProgress } from '../types'
import { Badge, EmptyState, ErrorState, Field, Modal, PageHeader, ProgressBar, Spinner } from '../components/ui'

const STATUS_TONE: Record<string, string> = {
  draft: 'slate',
  active: 'green',
  completed: 'blue',
  archived: 'slate',
}

export default function ProjectsPage() {
  useTitle('Projects')
  const [includeArchived, setIncludeArchived] = useState(false)
  const { data, loading, error, reload } = useAsync<Project[]>(
    () => api.get<Project[]>(`/api/projects${includeArchived ? '?include_archived=true' : ''}`),
    [includeArchived],
  )
  const [showCreate, setShowCreate] = useState(false)

  return (
    <>
      <PageHeader
        title="Evaluation projects"
        subtitle="Each project owns its datasets, rubric versions, reviewer assignments, ratings and analytics."
        actions={
          <button type="button" className="btn-primary" onClick={() => setShowCreate(true)}>
            + New project
          </button>
        }
      />

      {loading && <Spinner label="Loading projects…" />}
      {error && <ErrorState message={error} onRetry={reload} />}

      {data && data.length === 0 && (
        <EmptyState
          title="No projects yet"
          body="Create your first evaluation project, then import a dataset and configure a rubric."
          action={
            <button type="button" className="btn-primary" onClick={() => setShowCreate(true)}>
              + New project
            </button>
          }
        />
      )}

      {data && data.length > 0 && (
        <>
          <label className="mb-4 flex items-center gap-2 text-sm text-slate-600">
            <input
              type="checkbox"
              checked={includeArchived}
              onChange={(e) => setIncludeArchived(e.target.checked)}
              className="h-4 w-4 rounded border-slate-300"
            />
            Include archived projects
          </label>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {data.map((p) => (
              <ProjectCard key={p.id} project={p} />
            ))}
          </div>
        </>
      )}

      <CreateProjectModal open={showCreate} onClose={() => setShowCreate(false)} onCreated={reload} />
    </>
  )
}

function ProjectCard({ project }: { project: Project }) {
  const { data } = useAsync<ProjectProgress>(
    () => api.get<ProjectProgress>(`/api/projects/${project.id}/progress`),
    [project.id],
  )
  return (
    <Link to={`/projects/${project.id}`} className="card card-pad block transition-shadow hover:shadow-md">
      <div className="mb-2 flex items-start justify-between gap-2">
        <h3 className="text-sm font-semibold text-slate-900">{project.name}</h3>
        <Badge tone={STATUS_TONE[project.status] ?? 'slate'}>{project.status}</Badge>
      </div>
      <p className="mb-4 line-clamp-2 min-h-[2.5rem] text-xs text-slate-500">
        {project.description || 'No description.'}
      </p>
      {data ? (
        <div className="space-y-3">
          <ProgressBar value={data.completion_pct} label={`${data.completed_tasks}/${data.total_tasks} tasks complete`} />
          <dl className="grid grid-cols-3 gap-2 text-center">
            <div>
              <dt className="text-[11px] text-slate-500">Ratings</dt>
              <dd className="text-sm font-semibold tabular-nums text-slate-800">{data.submitted_ratings}</dd>
            </div>
            <div>
              <dt className="text-[11px] text-slate-500">Reviewers</dt>
              <dd className="text-sm font-semibold tabular-nums text-slate-800">{data.reviewers}</dd>
            </div>
            <div>
              <dt className="text-[11px] text-slate-500">Mode</dt>
              <dd className="text-sm font-semibold text-slate-800">{project.mode}</dd>
            </div>
          </dl>
        </div>
      ) : (
        <p className="text-xs text-slate-400">Loading progress…</p>
      )}
    </Link>
  )
}

function CreateProjectModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean
  onClose: () => void
  onCreated: () => void
}) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [mode, setMode] = useState<'single' | 'pairwise'>('single')
  const [minRatings, setMinRatings] = useState(2)
  const [minor, setMinor] = useState(0.25)
  const [major, setMajor] = useState(0.5)
  const [consensus, setConsensus] = useState<'majority' | 'median' | 'expert'>('expert')
  const create = useMutation((payload: Record<string, unknown>) => api.post<Project>('/api/projects', payload))

  async function submit() {
    const project = await create.run({
      name,
      description: description || null,
      mode,
      min_ratings_per_item: minRatings,
      disagreement_minor_fraction: minor,
      disagreement_major_fraction: major,
      consensus_strategy: consensus,
    })
    if (project) {
      onCreated()
      onClose()
      setName('')
      setDescription('')
    }
  }

  return (
    <Modal
      open={open}
      title="New evaluation project"
      onClose={onClose}
      wide
      footer={
        <>
          <button type="button" className="btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button type="button" className="btn-primary" onClick={submit} disabled={create.loading || !name.trim()}>
            {create.loading ? 'Creating…' : 'Create project'}
          </button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="sm:col-span-2">
          <Field label="Project name" htmlFor="p-name">
            <input id="p-name" className="input" value={name} onChange={(e) => setName(e.target.value)} required />
          </Field>
        </div>
        <div className="sm:col-span-2">
          <Field label="Description" htmlFor="p-desc">
            <textarea
              id="p-desc"
              className="input min-h-[70px]"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </Field>
        </div>
        <Field label="Evaluation mode" htmlFor="p-mode" hint="Pairwise compares two responses per item.">
          <select
            id="p-mode"
            className="input"
            value={mode}
            onChange={(e) => setMode(e.target.value as 'single' | 'pairwise')}
          >
            <option value="single">Single response</option>
            <option value="pairwise">Pairwise comparison</option>
          </select>
        </Field>
        <Field label="Ratings required per item" htmlFor="p-min">
          <input
            id="p-min"
            type="number"
            min={1}
            max={20}
            className="input"
            value={minRatings}
            onChange={(e) => setMinRatings(Number(e.target.value))}
          />
        </Field>
        <Field
          label="Minor disagreement threshold"
          htmlFor="p-minor"
          hint="Fraction of the scale range (0–1) treated as a minor gap."
        >
          <input
            id="p-minor"
            type="number"
            step={0.05}
            min={0.01}
            max={1}
            className="input"
            value={minor}
            onChange={(e) => setMinor(Number(e.target.value))}
          />
        </Field>
        <Field label="Major disagreement threshold" htmlFor="p-major" hint="Must be greater than the minor threshold.">
          <input
            id="p-major"
            type="number"
            step={0.05}
            min={0.01}
            max={1}
            className="input"
            value={major}
            onChange={(e) => setMajor(Number(e.target.value))}
          />
        </Field>
        <div className="sm:col-span-2">
          <Field
            label="Consensus strategy"
            htmlFor="p-consensus"
            hint="Advisory only — a human adjudication is always required to set an authoritative label."
          >
            <select
              id="p-consensus"
              className="input"
              value={consensus}
              onChange={(e) => setConsensus(e.target.value as 'majority' | 'median' | 'expert')}
            >
              <option value="majority">Majority vote</option>
              <option value="median">Median (ordinal / numeric)</option>
              <option value="expert">Expert gold label when available</option>
            </select>
          </Field>
        </div>
      </div>
      {create.error && (
        <p className="mt-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700" role="alert">
          {create.error}
        </p>
      )}
    </Modal>
  )
}
