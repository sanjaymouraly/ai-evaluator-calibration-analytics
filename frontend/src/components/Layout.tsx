import { useState } from 'react'
import type { ReactNode } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth'
import { Badge } from './ui'

const ROLE_LABEL: Record<string, string> = {
  admin: 'Administrator',
  adjudicator: 'Adjudicator',
  senior_reviewer: 'Senior reviewer',
  reviewer: 'Reviewer',
}

function NavSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="mb-5">
      <p className="mb-1.5 px-3 text-[11px] font-semibold uppercase tracking-wider text-slate-500">{title}</p>
      <nav className="space-y-0.5">{children}</nav>
    </div>
  )
}

export default function Layout({ children, projectId }: { children: ReactNode; projectId?: string }) {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)

  const link = (path: string) => (projectId ? `/projects/${projectId}${path}` : path)

  const sidebar = (
    <div className="flex h-full flex-col overflow-y-auto bg-slate-900 px-3 py-5">
      <div className="mb-6 flex items-center gap-2.5 px-2">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-brand-600 text-sm font-bold text-white">
          EC
        </div>
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-white">Evaluator Calibration</p>
          <p className="truncate text-[11px] text-slate-400">Disagreement Analytics</p>
        </div>
      </div>

      <NavSection title="Workspace">
        <NavLink to="/projects" className={({ isActive }) => `nav-link ${isActive && !projectId ? 'nav-link-active' : ''}`} end>
          <span aria-hidden="true">▦</span> Projects
        </NavLink>
        {user?.role === 'admin' && (
          <NavLink to="/admin" className={({ isActive }) => `nav-link ${isActive ? 'nav-link-active' : ''}`}>
            <span aria-hidden="true">⚙</span> Administration
          </NavLink>
        )}
      </NavSection>

      {projectId && (
        <NavSection title="This project">
          <NavLink to={link('')} className={({ isActive }) => `nav-link ${isActive ? 'nav-link-active' : ''}`} end>
            <span aria-hidden="true">◔</span> Dashboard
          </NavLink>
          <NavLink to={link('/evaluate')} className={({ isActive }) => `nav-link ${isActive ? 'nav-link-active' : ''}`}>
            <span aria-hidden="true">✎</span> Evaluate
          </NavLink>
          <NavLink to={link('/tasks')} className={({ isActive }) => `nav-link ${isActive ? 'nav-link-active' : ''}`}>
            <span aria-hidden="true">☰</span> Tasks &amp; data
          </NavLink>
          <NavLink to={link('/rubric')} className={({ isActive }) => `nav-link ${isActive ? 'nav-link-active' : ''}`}>
            <span aria-hidden="true">⚖</span> Rubric
          </NavLink>
          <NavLink
            to={link('/disagreements')}
            className={({ isActive }) => `nav-link ${isActive ? 'nav-link-active' : ''}`}
          >
            <span aria-hidden="true">⚡</span> Disagreements
          </NavLink>
          <NavLink to={link('/adjudication')} className={({ isActive }) => `nav-link ${isActive ? 'nav-link-active' : ''}`}>
            <span aria-hidden="true">§</span> Adjudication
          </NavLink>
          <NavLink to={link('/calibration')} className={({ isActive }) => `nav-link ${isActive ? 'nav-link-active' : ''}`}>
            <span aria-hidden="true">◎</span> Calibration
          </NavLink>
          <NavLink to={link('/insights')} className={({ isActive }) => `nav-link ${isActive ? 'nav-link-active' : ''}`}>
            <span aria-hidden="true">✧</span> Rubric insights
          </NavLink>
          <NavLink to={link('/reports')} className={({ isActive }) => `nav-link ${isActive ? 'nav-link-active' : ''}`}>
            <span aria-hidden="true">⇩</span> Reports
          </NavLink>
          <NavLink to={link('/settings')} className={({ isActive }) => `nav-link ${isActive ? 'nav-link-active' : ''}`}>
            <span aria-hidden="true">⋯</span> Settings
          </NavLink>
        </NavSection>
      )}

      <div className="mt-auto border-t border-white/10 pt-4">
        {user && (
          <div className="px-2">
            <p className="truncate text-sm font-medium text-white">{user.full_name}</p>
            <p className="truncate text-[11px] text-slate-400">{user.email}</p>
            <div className="mt-2 flex items-center gap-2">
              <Badge tone="blue">{ROLE_LABEL[user.role] ?? user.role}</Badge>
              <button
                type="button"
                className="text-[11px] font-medium text-slate-400 hover:text-white"
                onClick={() => {
                  logout()
                  navigate('/login')
                }}
              >
                Sign out
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )

  return (
    <div className="min-h-screen lg:flex">
      {/* Desktop sidebar */}
      <aside className="hidden w-64 shrink-0 lg:block">
        <div className="fixed inset-y-0 left-0 w-64">{sidebar}</div>
      </aside>

      {/* Mobile top bar */}
      <div className="sticky top-0 z-40 flex items-center justify-between border-b border-slate-200 bg-white px-4 py-3 lg:hidden">
        <p className="text-sm font-semibold text-slate-900">Evaluator Calibration</p>
        <button
          type="button"
          className="btn-secondary"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          aria-controls="mobile-nav"
        >
          {open ? 'Close menu' : 'Menu'}
        </button>
      </div>
      {open && (
        <div id="mobile-nav" className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-slate-900/40" onClick={() => setOpen(false)} aria-hidden="true" />
          <div className="absolute inset-y-0 left-0 w-72">{sidebar}</div>
        </div>
      )}

      <main className="min-w-0 flex-1 px-4 py-6 sm:px-6 lg:px-8">{children}</main>
    </div>
  )
}
