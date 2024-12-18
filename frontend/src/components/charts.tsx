import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { EmptyState } from './ui'

/* eslint-disable react-refresh/only-export-components -- shared chart module exports palette/colour helpers next to components */

// Colour-blind-friendly qualitative palette (Okabe-Ito inspired).
export const PALETTE = ['#2643e5', '#009e73', '#e69f00', '#cc79a7', '#56b4e9', '#d55e00', '#6b7280']

const SEVERITY_COLORS: Record<string, string> = {
  critical: '#d55e00',
  major: '#e69f00',
  minor: '#56b4e9',
  high: '#d55e00',
  medium: '#e69f00',
  low: '#56b4e9',
  open: '#e69f00',
  in_review: '#56b4e9',
  resolved: '#009e73',
  dismissed: '#6b7280',
}

export function colorFor(key: string): string {
  return SEVERITY_COLORS[key] ?? PALETTE[Math.abs(hash(key)) % PALETTE.length]
}

function hash(s: string): number {
  let h = 0
  for (let i = 0; i < s.length; i += 1) h = (h << 5) - h + s.charCodeAt(i)
  return h
}

interface BarDatum {
  name: string
  value: number
}

/** Row shape accepted by the line/grouped-bar charts. */
export type ChartDatum = Record<string, string | number | null>

export function SimpleBarChart({
  data,
  height = 240,
  color,
  valueLabel = 'value',
  domain,
  formatValue,
}: {
  data: BarDatum[]
  height?: number
  color?: string
  valueLabel?: string
  domain?: [number, number]
  formatValue?: (v: number) => string
}) {
  if (!data.length) return <EmptyState title="No data to chart yet" />
  return (
    <figure role="img" aria-label={`Bar chart of ${valueLabel}`}>
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={[...data]} margin={{ top: 8, right: 12, left: -18, bottom: 4 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
        <XAxis dataKey="name" tick={{ fontSize: 11, fill: '#64748b' }} interval={0} angle={data.length > 6 ? -20 : 0} height={data.length > 6 ? 56 : 28} />
        <YAxis tick={{ fontSize: 11, fill: '#64748b' }} domain={domain ?? ['auto', 'auto']} />
        <Tooltip
          formatter={(v) => [formatValue ? formatValue(Number(v)) : String(v), valueLabel]}
          contentStyle={{ fontSize: 12, borderRadius: 8, borderColor: '#e2e8f0' }}
        />
        <Bar dataKey="value" name={valueLabel} radius={[4, 4, 0, 0]}>
          {data.map((d) => (
            <Cell key={d.name} fill={color ?? colorFor(d.name)} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
    </figure>
  )
}

export function CategoryPieChart({
  data,
  height = 240,
  name = 'count',
}: {
  data: BarDatum[]
  height?: number
  name?: string
}) {
  const filtered = data.filter((d) => d.value > 0)
  if (!filtered.length) return <EmptyState title="Nothing to summarise yet" />
  return (
    <figure role="img" aria-label={`Pie chart of ${name}`}>
    <ResponsiveContainer width="100%" height={height}>
      <PieChart>
        <Pie data={filtered} dataKey="value" nameKey="name" innerRadius={48} outerRadius={82} paddingAngle={2}>
          {filtered.map((d) => (
            <Cell key={d.name} fill={colorFor(d.name)} />
          ))}
        </Pie>
        <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8, borderColor: '#e2e8f0' }} />
        <Legend wrapperStyle={{ fontSize: 11 }} />
      </PieChart>
    </ResponsiveContainer>
    </figure>
  )
}

export function TrendLineChart({
  data,
  xKey,
  yKey,
  height = 240,
  color = '#2643e5',
  label = 'value',
}: {
  data: readonly ChartDatum[]
  xKey: string
  yKey: string
  height?: number
  color?: string
  label?: string
}) {
  if (!data.length) return <EmptyState title="No trend data yet" body="Ratings will appear here as reviewers submit them." />
  return (
    <figure role="img" aria-label={`Trend of ${label}`}>
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={[...data]} margin={{ top: 8, right: 12, left: -18, bottom: 4 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
        <XAxis dataKey={xKey} tick={{ fontSize: 11, fill: '#64748b' }} />
        <YAxis tick={{ fontSize: 11, fill: '#64748b' }} />
        <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8, borderColor: '#e2e8f0' }} />
        <Line type="monotone" dataKey={yKey} stroke={color} strokeWidth={2} dot={{ r: 2.5 }} name={label} />
      </LineChart>
    </ResponsiveContainer>
    </figure>
  )
}

export function GroupedBarChart({
  data,
  keys,
  height = 260,
  xKey = 'name',
}: {
  data: readonly ChartDatum[]
  keys: string[]
  height?: number
  xKey?: string
}) {
  if (!data.length) return <EmptyState title="No data to chart yet" />
  return (
    <figure role="img" aria-label="Grouped bar chart">
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={[...data]} margin={{ top: 8, right: 12, left: -18, bottom: 4 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
        <XAxis dataKey={xKey} tick={{ fontSize: 11, fill: '#64748b' }} />
        <YAxis tick={{ fontSize: 11, fill: '#64748b' }} />
        <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8, borderColor: '#e2e8f0' }} />
        <Legend wrapperStyle={{ fontSize: 11 }} />
        {keys.map((k, i) => (
          <Bar key={k} dataKey={k} fill={PALETTE[i % PALETTE.length]} radius={[3, 3, 0, 0]} />
        ))}
      </BarChart>
    </ResponsiveContainer>
    </figure>
  )
}

/** Accessible confusion-matrix heat table (no canvas, works everywhere). */
export function ConfusionMatrix({
  matrix,
  labels,
}: {
  matrix: number[][]
  labels: string[]
}) {
  if (!matrix.length) return <EmptyState title="No reference-labelled ratings yet" />
  const max = Math.max(1, ...matrix.flat())
  return (
    <div className="overflow-x-auto">
      <table className="table-base" aria-label="Confusion matrix of ratings versus gold labels">
        <caption className="sr-only">Rows are gold labels, columns are reviewer ratings</caption>
        <thead>
          <tr>
            <th className="th" scope="col">
              gold ↓ / rating →
            </th>
            {labels.map((l) => (
              <th className="th text-center" scope="col" key={l}>
                {l}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {matrix.map((row, i) => (
            <tr key={labels[i] ?? i}>
              <th className="td font-medium text-slate-600" scope="row">
                {labels[i]}
              </th>
              {row.map((cell, j) => {
                const intensity = cell / max
                const bg = `rgba(38, 67, 229, ${0.08 + intensity * 0.72})`
                return (
                  <td
                    key={j}
                    className="td text-center tabular-nums"
                    style={{ backgroundColor: bg, color: intensity > 0.55 ? 'white' : undefined }}
                  >
                    {cell}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
