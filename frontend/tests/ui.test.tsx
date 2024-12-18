import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ConfusionMatrix } from '../src/components/charts'
import { MetricValue, ProgressBar, severityTone } from '../src/components/ui'

describe('MetricValue', () => {
  it('renders finite numbers with requested precision', () => {
    render(<MetricValue value={0.61234} digits={3} />)
    expect(screen.getByText('0.612')).toBeInTheDocument()
  })

  it('renders n/a for undefined metrics instead of a misleading zero', () => {
    render(<MetricValue value={null} />)
    expect(screen.getByText('n/a')).toBeInTheDocument()
  })

  it('renders n/a for NaN', () => {
    render(<MetricValue value={Number.NaN} />)
    expect(screen.getByText('n/a')).toBeInTheDocument()
  })
})

describe('ProgressBar', () => {
  it('clamps out-of-range values', () => {
    const { rerender } = render(<ProgressBar value={140} label="done" />)
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '100')
    rerender(<ProgressBar value={-5} label="done" />)
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '0')
  })

  it('exposes an accessible value', () => {
    render(<ProgressBar value={42} label="completion" />)
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '42')
  })
})

describe('severityTone', () => {
  it('maps severities to visual tones', () => {
    expect(severityTone('critical')).toBe('rose')
    expect(severityTone('major')).toBe('amber')
    expect(severityTone('high')).toBe('amber')
    expect(severityTone('minor')).toBe('slate')
  })
})

describe('ConfusionMatrix', () => {
  it('renders one row per gold label with its cell counts', () => {
    render(<ConfusionMatrix matrix={[[3, 1], [0, 7]]} labels={['gold-a', 'gold-b']} />)
    const table = screen.getByRole('table', { name: /Confusion matrix/i })
    const rows = within(table).getAllByRole('row')
    // header + one row per label
    expect(rows).toHaveLength(3)
    expect(within(rows[1]).getByText('gold-a')).toBeInTheDocument()
    expect(within(rows[1]).getByText('3')).toBeInTheDocument()
    expect(within(rows[1]).getByText('1')).toBeInTheDocument()
    expect(within(rows[2]).getByText('gold-b')).toBeInTheDocument()
    expect(within(rows[2]).getByText('7')).toBeInTheDocument()
    expect(within(rows[2]).getByText('0')).toBeInTheDocument()
  })

  it('shows an empty state when there is no data', () => {
    render(<ConfusionMatrix matrix={[]} labels={[]} />)
    expect(screen.getByText(/No reference-labelled ratings yet/i)).toBeInTheDocument()
  })
})

describe('interactive components', () => {
  it('invokes callbacks on user interaction', async () => {
    const onClick = vi.fn()
    render(
      <button type="button" onClick={onClick}>
        Submit rating
      </button>,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Submit rating' }))
    expect(onClick).toHaveBeenCalledTimes(1)
  })
})
