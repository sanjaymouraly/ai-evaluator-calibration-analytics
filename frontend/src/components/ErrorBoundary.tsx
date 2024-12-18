import { Component } from 'react'
import type { ErrorInfo, ReactNode } from 'react'

interface Props {
  children: ReactNode
}

interface State {
  error: Error | null
}

/**
 * Top-level error boundary. A crash in one view shows a recoverable message
 * instead of blanking the whole application.
 */
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Unhandled UI error:', error, info.componentStack)
  }

  render() {
    if (this.state.error) {
      return (
        <div className="flex min-h-screen items-center justify-center bg-slate-50 p-6">
          <div className="card max-w-lg p-6">
            <h1 className="text-lg font-semibold text-slate-900">This view crashed</h1>
            <p className="mt-2 text-sm text-slate-600">
              The rest of the application is still available. The error below was logged to the browser console.
            </p>
            <pre className="mt-3 max-h-40 overflow-auto rounded-lg bg-slate-100 p-3 font-mono text-xs text-slate-700">
              {this.state.error.message}
            </pre>
            <div className="mt-4 flex gap-2">
              <button type="button" className="btn-primary" onClick={() => this.setState({ error: null })}>
                Try again
              </button>
              <button type="button" className="btn-secondary" onClick={() => window.location.assign('/projects')}>
                Back to projects
              </button>
            </div>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}
