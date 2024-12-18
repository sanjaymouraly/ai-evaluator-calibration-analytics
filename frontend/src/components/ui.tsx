import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'

/* eslint-disable react-refresh/only-export-components -- shared UI module exports style helpers next to components */

export function Card({
  title,
  subtitle,
  actions,
  children,
  className = '',
}: {
  title?: ReactNode
  subtitle?: ReactNode
  actions?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <header className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-200 px-5 py-4">
          <div>
            {title && <h2 className="text-base font-semibold text-slate-900">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-sm text-slate-500">{subtitle}</p>}
          </div>
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className="card-pad">{children}</div>
    </section>
  )
}

export function StatCard({
  label,
  value,
  hint,
  tone = 'neutral',
}: {
  label: string
  value: ReactNode
  hint?: ReactNode
  tone?: 'neutral' | 'good' | 'warn' | 'bad'
}) {
  const toneClass = {
    neutral: 'text-slate-900',
    good: 'text-emerald-700',
    warn: 'text-amber-700',
    bad: 'text-rose-700',
  }[tone]
  return (
    <div className="card card-pad">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</p>
      <p className={`mt-2 text-2xl font-semibold tabular-nums ${toneClass}`}>{value}</p>
      {hint && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
    </div>
  )
}

const BADGE_TONES: Record<string, string> = {
  slate: 'bg-slate-100 text-slate-700',
  green: 'bg-emerald-100 text-emerald-800',
  amber: 'bg-amber-100 text-amber-800',
  rose: 'bg-rose-100 text-rose-800',
  blue: 'bg-brand-100 text-brand-800',
  violet: 'bg-violet-100 text-violet-800',
}

export function Badge({
  children,
  tone = 'slate',
  title,
}: {
  children: ReactNode
  tone?: keyof typeof BADGE_TONES | string
  title?: string
}) {
  return (
    <span className={`badge ${BADGE_TONES[tone] ?? BADGE_TONES.slate}`} title={title}>
      {children}
    </span>
  )
}

export function severityTone(severity: string): string {
  if (severity === 'critical') return 'rose'
  if (severity === 'major' || severity === 'high') return 'amber'
  if (severity === 'medium') return 'blue'
  return 'slate'
}

export function Spinner({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-3 py-10 text-sm text-slate-500" role="status">
      <svg className="h-5 w-5 animate-spin text-brand-600" viewBox="0 0 24 24" aria-hidden="true">
        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
      </svg>
      <span>{label}</span>
    </div>
  )
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm" role="alert">
      <p className="font-medium text-rose-800">Something went wrong</p>
      <p className="mt-1 break-words text-rose-700">{message}</p>
      {onRetry && (
        <button type="button" className="btn-secondary mt-3" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  )
}

export function EmptyState({
  title,
  body,
  action,
}: {
  title: string
  body?: ReactNode
  action?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-slate-300 bg-slate-50/60 px-6 py-12 text-center">
      <svg className="mb-3 h-9 w-9 text-slate-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden="true">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3.75 9.75h16.5M3.75 14.25h16.5M6 5.25h12a2.25 2.25 0 012.25 2.25v9A2.25 2.25 0 0118 18.75H6A2.25 2.25 0 013.75 16.5v-9A2.25 2.25 0 016 5.25z" />
      </svg>
      <p className="text-sm font-semibold text-slate-800">{title}</p>
      {body && <div className="mt-1 max-w-md text-sm text-slate-500">{body}</div>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}

export function ProgressBar({ value, label }: { value: number; label?: string }) {
  const pct = Math.max(0, Math.min(100, value))
  return (
    <div>
      {label && (
        <div className="mb-1 flex items-center justify-between text-xs text-slate-500">
          <span>{label}</span>
          <span className="tabular-nums">{pct.toFixed(0)}%</span>
        </div>
      )}
      <div
        className="h-2 w-full overflow-hidden rounded-full bg-slate-200"
        role="progressbar"
        aria-valuenow={Math.round(pct)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={label ?? 'progress'}
      >
        <div className="h-full rounded-full bg-brand-600 transition-all" style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

export function MetricValue({
  value,
  digits = 3,
  suffix,
}: {
  value: number | null | undefined
  digits?: number
  suffix?: string
}) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return (
      <span className="text-slate-400" title="Metric undefined for this data (see warnings)">
        n/a
      </span>
    )
  }
  return (
    <span className="tabular-nums">
      {value.toFixed(digits)}
      {suffix}
    </span>
  )
}

export function WarningList({ warnings }: { warnings?: string[] }) {
  if (!warnings || warnings.length === 0) return null
  return (
    <ul className="mt-2 space-y-1 text-xs text-amber-800">
      {warnings.map((w) => (
        <li key={w} className="flex gap-1.5">
          <span aria-hidden="true">⚠</span>
          <span>{w}</span>
        </li>
      ))}
    </ul>
  )
}

export function InfoNote({ children, tone = 'blue' }: { children: ReactNode; tone?: 'blue' | 'amber' | 'slate' }) {
  const tones = {
    blue: 'border-brand-200 bg-brand-50 text-brand-900',
    amber: 'border-amber-200 bg-amber-50 text-amber-900',
    slate: 'border-slate-200 bg-slate-50 text-slate-700',
  }
  return <div className={`rounded-lg border px-3 py-2 text-xs leading-relaxed ${tones[tone]}`}>{children}</div>
}

export function Modal({
  open,
  title,
  onClose,
  children,
  footer,
  wide = false,
}: {
  open: boolean
  title: string
  onClose: () => void
  children: ReactNode
  footer?: ReactNode
  wide?: boolean
}) {
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-900/50 p-4 sm:p-8">
      <div
        className={`w-full ${wide ? 'max-w-4xl' : 'max-w-lg'} rounded-xl bg-white shadow-xl`}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <header className="flex items-center justify-between border-b border-slate-200 px-5 py-3.5">
          <h2 className="text-base font-semibold text-slate-900">{title}</h2>
          <button type="button" className="btn-ghost px-2 py-1" onClick={onClose} aria-label="Close dialog">
            ✕
          </button>
        </header>
        <div className="px-5 py-4">{children}</div>
        {footer && <footer className="flex justify-end gap-2 border-t border-slate-200 px-5 py-3.5">{footer}</footer>}
      </div>
    </div>
  )
}

export function PageHeader({
  title,
  subtitle,
  actions,
  backTo,
}: {
  title: string
  subtitle?: ReactNode
  actions?: ReactNode
  backTo?: string
}) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
      <div>
        {backTo && (
          <Link to={backTo} className="mb-1 inline-block text-xs font-medium text-brand-600 hover:underline">
            ← Back
          </Link>
        )}
        <h1 className="text-xl font-semibold text-slate-900 sm:text-2xl">{title}</h1>
        {subtitle && <p className="mt-1 max-w-3xl text-sm text-slate-500">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

export function Field({
  label,
  hint,
  error,
  children,
  htmlFor,
}: {
  label: string
  hint?: string
  error?: string
  children: ReactNode
  htmlFor?: string
}) {
  return (
    <div>
      <label className="label" htmlFor={htmlFor}>
        {label}
      </label>
      {children}
      {hint && !error && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
      {error && (
        <p className="mt-1 text-xs text-rose-600" role="alert">
          {error}
        </p>
      )}
    </div>
  )
}
