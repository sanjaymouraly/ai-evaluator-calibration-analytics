import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { api } from '../api/client'
import { useAuth, can } from '../auth'
import {
  Badge,
  Card,
  ErrorState,
  Field,
  InfoNote,
  PageHeader,
  Spinner,
} from '../components/ui'
import { useAsync, useMutation, useTitle } from '../hooks'
import type { Project, ProjectMember, User } from '../types'

const ROLE_TONE: Record<string, string> = {
  lead: 'violet',
  reviewer: 'slate',
  adjudicator: 'blue',
}

export default function SettingsPage() {
  const { projectId = '' } = useParams()
  useTitle('Project settings')
  const { user } = useAuth()
  const { data: project, loading, error, reload } = useAsync<Project>(
    () => api.get<Project>(`/api/projects/${projectId}`),
    [projectId],
  )
  const { data: members, reload: reloadMembers } = useAsync<(ProjectMember & { user?: User })[]>(
    () => api.get(`/api/projects/${projectId}/members`),
    [projectId],
  )
  const { data: allUsers } = useAsync<User[]>(
    () => api.get<User[]>('/api/auth/users').catch(() => [] as User[]),
    [],
  )

  const [status, setStatus] = useState('')
  const [minRatings, setMinRatings] = useState<number | null>(null)
  const [minor, setMinor] = useState<number | null>(null)
  const [major, setMajor] = useState<number | null>(null)
  const [consensus, setConsensus] = useState('')
  const [addUserId, setAddUserId] = useState('')
  const [addRole, setAddRole] = useState('reviewer')
  const [note, setNote] = useState<string | null>(null)

  const update = useMutation((payload: Record<string, unknown>) =>
    api.patch<Project>(`/api/projects/${projectId}`, payload),
  )
  const archive = useMutation(() => api.post<Project>(`/api/projects/${projectId}/archive`))
  const addMember = useMutation(() =>
    api.post(`/api/projects/${projectId}/members`, { user_id: addUserId, role_on_project: addRole }),
  )
  const removeMember = useMutation((userId: string) => api.delete(`/api/projects/${projectId}/members/${userId}`))

  if (loading) return <Spinner label="Loading settings…" />
  if (error) return <ErrorState message={error} onRetry={reload} />
  if (!project) return null

  const isOwner = user?.role === 'admin' || project.owner_id === user?.id
  const effectiveStatus = status || project.status
  const effectiveMin = minRatings ?? project.min_ratings_per_item
  const effectiveMinor = minor ?? project.disagreement_minor_fraction
  const effectiveMajor = major ?? project.disagreement_major_fraction
  const effectiveConsensus = consensus || project.consensus_strategy

  async function save() {
    setNote(null)
    const res = await update.run({
      status: effectiveStatus,
      min_ratings_per_item: effectiveMin,
      disagreement_minor_fraction: effectiveMinor,
      disagreement_major_fraction: effectiveMajor,
      consensus_strategy: effectiveConsensus,
    })
    if (res) {
      setNote('Settings saved.')
      reload()
    }
  }

  const memberIds = new Set((members ?? []).map((m) => m.user_id))
  const candidates = (allUsers ?? []).filter((u) => !memberIds.has(u.id) && u.is_active)

  return (
    <>
      <PageHeader title="Project settings" subtitle="Lifecycle, thresholds, consensus strategy and team access." backTo={`/projects/${projectId}`} />

      <div className="grid gap-5 lg:grid-cols-2">
        <Card title="General">
          <div className="space-y-4">
            <Field label="Project name" htmlFor="s-name">
              <input id="s-name" className="input" value={project.name} disabled />
            </Field>
            <Field label="Status" htmlFor="s-status" hint="Archived projects are read-only and hidden from the default list.">
              <select
                id="s-status"
                className="input"
                value={effectiveStatus}
                disabled={!isOwner}
                onChange={(e) => setStatus(e.target.value)}
              >
                <option value="draft">Draft</option>
                <option value="active">Active</option>
                <option value="completed">Completed</option>
                <option value="archived">Archived</option>
              </select>
            </Field>
            <Field label="Ratings required per item" htmlFor="s-min">
              <input
                id="s-min"
                type="number"
                min={1}
                max={20}
                className="input"
                value={effectiveMin}
                disabled={!isOwner}
                onChange={(e) => setMinRatings(Number(e.target.value))}
              />
            </Field>
          </div>
        </Card>

        <Card title="Disagreement thresholds" subtitle="Scale-relative: a fraction of each category's own range.">
          <div className="space-y-4">
            <Field label="Minor threshold" htmlFor="s-minor" hint="e.g. 0.25 = a gap of 25% of the scale range.">
              <input
                id="s-minor"
                type="number"
                step={0.05}
                min={0.01}
                max={1}
                className="input"
                value={effectiveMinor}
                disabled={!isOwner}
                onChange={(e) => setMinor(Number(e.target.value))}
              />
            </Field>
            <Field label="Major threshold" htmlFor="s-major" hint="Must be greater than the minor threshold.">
              <input
                id="s-major"
                type="number"
                step={0.05}
                min={0.01}
                max={1}
                className="input"
                value={effectiveMajor}
                disabled={!isOwner}
                onChange={(e) => setMajor(Number(e.target.value))}
              />
            </Field>
            <Field
              label="Consensus strategy"
              htmlFor="s-consensus"
              hint="Advisory only — a human adjudication is always required for an authoritative label."
            >
              <select
                id="s-consensus"
                className="input"
                value={effectiveConsensus}
                disabled={!isOwner}
                onChange={(e) => setConsensus(e.target.value)}
              >
                <option value="majority">Majority vote</option>
                <option value="median">Median (ordinal / numeric)</option>
                <option value="expert">Expert gold label when available</option>
              </select>
            </Field>
            {effectiveMinor >= effectiveMajor && (
              <p className="text-xs text-rose-600" role="alert">
                The minor threshold must be smaller than the major threshold.
              </p>
            )}
          </div>
        </Card>
      </div>

      {isOwner && (
        <div className="mt-5 flex flex-wrap items-center gap-3">
          <button
            type="button"
            className="btn-primary"
            onClick={save}
            disabled={update.loading || effectiveMinor >= effectiveMajor}
          >
            {update.loading ? 'Saving…' : 'Save settings'}
          </button>
          {project.status !== 'archived' && (
            <button
              type="button"
              className="btn-danger"
              disabled={archive.loading}
              onClick={async () => {
                const res = await archive.run()
                if (res) {
                  reload()
                  setNote('Project archived.')
                }
              }}
            >
              Archive project
            </button>
          )}
          {(note || update.error || archive.error) && (
            <p className={`text-sm ${update.error || archive.error ? 'text-rose-600' : 'text-emerald-700'}`} role="status">
              {update.error ?? archive.error ?? note}
            </p>
          )}
        </div>
      )}

      <Card title="Team access" subtitle="Project-level access control. Non-members cannot see any project data." className="mt-5">
        <div className="mb-4 overflow-x-auto">
          <table className="table-base">
            <thead>
              <tr>
                <th className="th" scope="col">Member</th>
                <th className="th" scope="col">Global role</th>
                <th className="th" scope="col">Project role</th>
                <th className="th" scope="col"><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              {(members ?? []).map((m) => {
                const u = allUsers?.find((x) => x.id === m.user_id)
                return (
                  <tr key={m.id}>
                    <td className="td">
                      <p className="font-medium text-slate-800">{u?.full_name ?? m.user_id.slice(0, 8)}</p>
                      <p className="text-xs text-slate-500">{u?.email}</p>
                    </td>
                    <td className="td">
                      <Badge tone="slate">{u?.role ?? '—'}</Badge>
                    </td>
                    <td className="td">
                      <Badge tone={ROLE_TONE[m.role_on_project] ?? 'slate'}>{m.role_on_project}</Badge>
                    </td>
                    <td className="td">
                      {isOwner && m.user_id !== project.owner_id && (
                        <button
                          type="button"
                          className="btn-ghost px-2 py-1 text-xs text-rose-600"
                          disabled={removeMember.loading}
                          onClick={async () => {
                            await removeMember.run(m.user_id)
                            reloadMembers()
                          }}
                        >
                          Remove
                        </button>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>

        {isOwner && (
          <div className="flex flex-wrap items-end gap-3 rounded-lg border border-slate-200 bg-slate-50 p-3">
            <div className="min-w-[220px] flex-1">
              <Field label="Add a user" htmlFor="add-user">
                <select id="add-user" className="input" value={addUserId} onChange={(e) => setAddUserId(e.target.value)}>
                  <option value="">Select a user…</option>
                  {candidates.map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.full_name} ({u.email})
                    </option>
                  ))}
                </select>
              </Field>
            </div>
            <div className="w-44">
              <Field label="Project role" htmlFor="add-role">
                <select id="add-role" className="input" value={addRole} onChange={(e) => setAddRole(e.target.value)}>
                  <option value="reviewer">Reviewer</option>
                  <option value="lead">Lead</option>
                  <option value="adjudicator">Adjudicator</option>
                </select>
              </Field>
            </div>
            <button
              type="button"
              className="btn-primary"
              disabled={!addUserId || addMember.loading}
              onClick={async () => {
                const res = await addMember.run()
                if (res) {
                  setAddUserId('')
                  reloadMembers()
                }
              }}
            >
              Add member
            </button>
            {addMember.error && <p className="text-xs text-rose-600">{addMember.error}</p>}
          </div>
        )}

        {!isOwner && (
          <InfoNote tone="slate">Only the project owner and administrators can change team access.</InfoNote>
        )}
        {!can.manageRubric(user) && null}
      </Card>
    </>
  )
}
