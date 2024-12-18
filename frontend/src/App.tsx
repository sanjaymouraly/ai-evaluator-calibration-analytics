import { Navigate, Route, Routes, useParams } from 'react-router-dom'
import { useAuth } from './auth'
import Layout from './components/Layout'
import { Spinner } from './components/ui'
import AdjudicationPage from './pages/Adjudication'
import AdminPage from './pages/Admin'
import CalibrationPage from './pages/Calibration'
import DisagreementsPage from './pages/Disagreements'
import EvaluatePage from './pages/Evaluate'
import InsightsPage from './pages/Insights'
import LoginPage from './pages/Login'
import ProjectDashboard from './pages/ProjectDashboard'
import ProjectsPage from './pages/Projects'
import ReportsPage from './pages/Reports'
import RubricPage from './pages/Rubric'
import SettingsPage from './pages/Settings'
import TasksPage from './pages/Tasks'

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth()
  // Read the route param here so the sidebar can render project-scoped
  // navigation for every nested page.
  const { projectId } = useParams()
  if (loading) return <Spinner label="Restoring session…" />
  if (!user) return <Navigate to="/login" replace />
  return <Layout projectId={projectId}>{children}</Layout>
}

export default function App() {
  const { user, loading } = useAuth()

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Spinner label="Loading…" />
      </div>
    )
  }

  return (
    <Routes>
      <Route
        path="/login"
        element={user ? <Navigate to="/projects" replace /> : <LoginPage />}
      />
      <Route
        path="/projects"
        element={
          <RequireAuth>
            <ProjectsPage />
          </RequireAuth>
        }
      />
      <Route
        path="/admin"
        element={
          <RequireAuth>
            <AdminPage />
          </RequireAuth>
        }
      />
      <Route
        path="/projects/:projectId"
        element={
          <RequireAuth>
            <ProjectDashboard />
          </RequireAuth>
        }
      />
      <Route
        path="/projects/:projectId/evaluate"
        element={
          <RequireAuth>
            <EvaluatePage />
          </RequireAuth>
        }
      />
      <Route
        path="/projects/:projectId/tasks"
        element={
          <RequireAuth>
            <TasksPage />
          </RequireAuth>
        }
      />
      <Route
        path="/projects/:projectId/rubric"
        element={
          <RequireAuth>
            <RubricPage />
          </RequireAuth>
        }
      />
      <Route
        path="/projects/:projectId/disagreements"
        element={
          <RequireAuth>
            <DisagreementsPage />
          </RequireAuth>
        }
      />
      <Route
        path="/projects/:projectId/adjudication"
        element={
          <RequireAuth>
            <AdjudicationPage />
          </RequireAuth>
        }
      />
      <Route
        path="/projects/:projectId/calibration"
        element={
          <RequireAuth>
            <CalibrationPage />
          </RequireAuth>
        }
      />
      <Route
        path="/projects/:projectId/insights"
        element={
          <RequireAuth>
            <InsightsPage />
          </RequireAuth>
        }
      />
      <Route
        path="/projects/:projectId/reports"
        element={
          <RequireAuth>
            <ReportsPage />
          </RequireAuth>
        }
      />
      <Route
        path="/projects/:projectId/settings"
        element={
          <RequireAuth>
            <SettingsPage />
          </RequireAuth>
        }
      />
      <Route path="*" element={<Navigate to={user ? '/projects' : '/login'} replace />} />
    </Routes>
  )
}
