import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { api, getToken } from '../api/client'
import {
  Badge,
  Card,
  EmptyState,
  ErrorState,
  Field,
  InfoNote,
  PageHeader,
  Spinner,
} from '../components/ui'
import { useAsync, useMutation, useTitle } from '../hooks'
import type { Job, Report } from '../types'

const FORMAT_LABEL: Record<string, string> = {
  csv: 'CSV (spreadsheet / BI tools)',
  json: 'JSON (programmatic reuse)',
  pdf: 'PDF (shareable summary)',
}

export default function ReportsPage() {
  const { projectId = '' } = useParams()
  useTitle('Reports')
  const [title, setTitle] = useState('Evaluation quality report')
  const [format, setFormat] = useState<'csv' | 'json' | 'pdf'>('pdf')
  const [pendingJob, setPendingJob] = useState<string | null>(null)
  const [jobStatus, setJobStatus] = useState<string | null>(null)

  const { data: reports, loading, error, reload } = useAsync<Report[]>(
    () => api.get<Report[]>(`/api/projects/${projectId}/reports`),
    [projectId],
  )
  const generate = useMutation(() =>
    api.post<Job>(`/api/projects/${projectId}/reports`, { title, report_format: format }),
  )

  // Poll the job until it finishes, then refresh the report list.
  useEffect(() => {
    if (!pendingJob) return
    let cancelled = false
    const poll = async () => {
      const jobs = await api.get<Job[]>('/api/admin/jobs').catch(() => [] as Job[])
      const job = jobs.find((j) => j.id === pendingJob)
      if (cancelled) return
      if (job) {
        setJobStatus(job.status)
        if (job.status === 'succeeded' || job.status === 'failed') {
          setPendingJob(null)
          reload()
        }
      }
    }
    void poll()
    const interval = window.setInterval(() => void poll(), 1200)
    return () => {
      cancelled = true
      window.clearInterval(interval)
    }
  }, [pendingJob, reload])

  async function download(report: Report) {
    // Authenticated download: fetch with the bearer token, then save the blob.
    const response = await fetch(`/api/projects/${projectId}/reports/${report.id}/download`, {
      headers: { Authorization: `Bearer ${getToken() ?? ''}` },
    })
    if (!response.ok) throw new Error(`Download failed (${response.status})`)
    const blob = await response.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${report.title.replace(/\s+/g, '_')}.${report.report_format}`
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  }

  return (
    <>
      <PageHeader
        title="Reports & exports"
        subtitle="Generate CSV, JSON and PDF reports. Every export records its generation time, applied filters and the exact definition of each metric."
        backTo={`/projects/${projectId}`}
      />

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_360px]">
        <Card title="Generated reports" subtitle="Newest first.">
          {loading && <Spinner label="Loading reports…" />}
          {error && <ErrorState message={error} onRetry={reload} />}
          {reports && reports.length === 0 && (
            <EmptyState title="No reports yet" body="Generate one using the panel on the right." />
          )}
          {reports && reports.length > 0 && (
            <div className="overflow-x-auto">
              <table className="table-base">
                <thead>
                  <tr>
                    <th className="th" scope="col">Title</th>
                    <th className="th" scope="col">Format</th>
                    <th className="th" scope="col">Generated</th>
                    <th className="th" scope="col"><span className="sr-only">Download</span></th>
                  </tr>
                </thead>
                <tbody>
                  {reports.map((r) => (
                    <tr key={r.id}>
                      <td className="td font-medium text-slate-800">{r.title}</td>
                      <td className="td">
                        <Badge tone={r.report_format === 'pdf' ? 'rose' : r.report_format === 'csv' ? 'green' : 'blue'}>
                          {r.report_format.toUpperCase()}
                        </Badge>
                      </td>
                      <td className="td text-xs text-slate-500">{new Date(r.created_at).toLocaleString()}</td>
                      <td className="td">
                        <button
                          type="button"
                          className="btn-secondary px-2.5 py-1 text-xs"
                          onClick={() => void download(r)}
                        >
                          Download
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        <div className="space-y-5">
          <Card title="Generate a report">
            <div className="space-y-4">
              <Field label="Report title" htmlFor="rep-title">
                <input id="rep-title" className="input" value={title} onChange={(e) => setTitle(e.target.value)} />
              </Field>
              <Field label="Format" htmlFor="rep-format">
                <select
                  id="rep-format"
                  className="input"
                  value={format}
                  onChange={(e) => setFormat(e.target.value as 'csv' | 'json' | 'pdf')}
                >
                  {Object.entries(FORMAT_LABEL).map(([k, label]) => (
                    <option key={k} value={k}>
                      {label}
                    </option>
                  ))}
                </select>
              </Field>
              <button
                type="button"
                className="btn-primary w-full"
                disabled={generate.loading || pendingJob !== null || !title.trim()}
                onClick={async () => {
                  const job = await generate.run()
                  if (job) {
                    setPendingJob(job.id)
                    setJobStatus('queued')
                  }
                }}
              >
                {pendingJob ? `Generating… (${jobStatus})` : generate.loading ? 'Submitting…' : 'Generate report'}
              </button>
              {generate.error && <p className="text-sm text-rose-600">{generate.error}</p>}
              <InfoNote tone="slate">
                Report generation runs as a background job, so large projects will not block the UI.
              </InfoNote>
            </div>
          </Card>

          <Card title="Direct exports">
            <div className="space-y-2">
              <a
                className="btn-secondary w-full"
                href={`/api/projects/${projectId}/export/ratings`}
                onClick={async (e) => {
                  e.preventDefault()
                  const response = await fetch(`/api/projects/${projectId}/export/ratings`, {
                    headers: { Authorization: `Bearer ${getToken() ?? ''}` },
                  })
                  const blob = await response.blob()
                  const url = URL.createObjectURL(blob)
                  const a = document.createElement('a')
                  a.href = url
                  a.download = 'ratings_export.csv'
                  document.body.appendChild(a)
                  a.click()
                  a.remove()
                  URL.revokeObjectURL(url)
                }}
              >
                Download all ratings (CSV)
              </a>
              <p className="text-xs text-slate-500">
                Includes every rating version, so corrections remain auditable.
              </p>
            </div>
          </Card>
        </div>
      </div>

      {reports && reports[0]?.metric_definitions && (
        <Card title="Metric definitions" subtitle="Bundled into every generated report so numbers are never ambiguous." className="mt-5">
          <dl className="grid gap-3 md:grid-cols-2">
            {Object.entries(reports[0].metric_definitions).map(([name, definition]) => (
              <div key={name} className="rounded-lg border border-slate-200 p-3">
                <dt className="font-mono text-xs font-semibold text-slate-800">{name}</dt>
                <dd className="mt-1 text-xs leading-relaxed text-slate-600">{definition}</dd>
              </div>
            ))}
          </dl>
        </Card>
      )}
    </>
  )
}
