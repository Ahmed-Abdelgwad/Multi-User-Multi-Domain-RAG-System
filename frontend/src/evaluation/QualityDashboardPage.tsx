import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { downloadQualityDashboardCsv, getQualityDashboard } from '../api/evaluation'
import { ApiError } from '../api/client'
import { Badge } from '../components/Badge'
import { Button } from '../components/Button'
import { ErrorBanner } from '../components/ErrorBanner'
import { Spinner } from '../components/Spinner'

const DIMENSION_COLORS: Record<string, string> = {
  faithfulness: '#2563eb',
  relevance: '#059669',
  completeness: '#d97706',
  citation_accuracy: '#db2777',
}

export function QualityDashboardPage() {
  const { domainId } = useParams<{ domainId: string }>()
  const [windowDays, setWindowDays] = useState(30)
  const [trendPoints, setTrendPoints] = useState(6)
  const [exportError, setExportError] = useState<string | null>(null)

  const dashboardQuery = useQuery({
    queryKey: ['quality-dashboard', domainId, windowDays, trendPoints],
    queryFn: () => getQualityDashboard(domainId!, windowDays, trendPoints),
    enabled: Boolean(domainId),
  })

  async function handleExport() {
    setExportError(null)
    try {
      const blob = await downloadQualityDashboardCsv(domainId!, windowDays, trendPoints)
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `quality-dashboard-${domainId}.csv`
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
    } catch (err) {
      setExportError(err instanceof ApiError ? err.message : 'Could not export CSV')
    }
  }

  if (dashboardQuery.isLoading) return <Spinner />
  if (dashboardQuery.error) {
    return (
      <ErrorBanner
        message={dashboardQuery.error instanceof ApiError ? dashboardQuery.error.message : 'Could not load dashboard'}
      />
    )
  }
  const dashboard = dashboardQuery.data!
  const dimensions = Object.keys(dashboard.by_dimension)

  const chartData = dashboard.trend.map((point) => {
    const row: Record<string, number | string | null> = {
      period: new Date(point.period_end).toLocaleDateString(),
    }
    for (const dim of dimensions) {
      row[dim] = point.by_dimension[dim]?.mean ?? null
    }
    return row
  })

  const goldenDimensions = Object.entries(dashboard.golden_regression.by_dimension)

  return (
    <div>
      <div className="page-header">
        <h1>Quality dashboard</h1>
        <Button variant="ghost" onClick={handleExport}>
          Export CSV
        </Button>
      </div>
      {exportError && <ErrorBanner message={exportError} />}

      <div className="inline-form filters-row">
        <label>
          Window (days)
          <input type="number" min={1} max={365} value={windowDays} onChange={(e) => setWindowDays(Number(e.target.value))} />
        </label>
        <label>
          Trend points
          <input type="number" min={1} max={24} value={trendPoints} onChange={(e) => setTrendPoints(Number(e.target.value))} />
        </label>
      </div>

      <div className="dimension-cards">
        {dimensions.map((dim) => {
          const stat = dashboard.by_dimension[dim]
          const degrading = dashboard.degrading_dimensions.includes(dim)
          return (
            <div key={dim} className="dimension-card">
              <span className="muted">{dim.replace('_', ' ')}</span>
              <strong>{stat.mean !== null ? stat.mean.toFixed(2) : '--'}</strong>
              <span className="muted">{stat.sample_count} samples</span>
              {degrading && <Badge tone="danger">Degrading</Badge>}
            </div>
          )
        })}
      </div>

      {chartData.length > 0 && (
        <div className="chart-container">
          <ResponsiveContainer width="100%" height={280}>
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="period" fontSize={12} />
              <YAxis domain={[0, 1]} fontSize={12} />
              <Tooltip />
              <Legend />
              {dimensions.map((dim) => (
                <Line
                  key={dim}
                  type="monotone"
                  dataKey={dim}
                  stroke={DIMENSION_COLORS[dim] ?? '#666'}
                  dot={false}
                  connectNulls
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      <h2>Golden regression</h2>
      <p className="muted">Traffic from scheduled/manual golden-set regression runs -- kept separate from live-query stats above.</p>
      <div className="dimension-cards">
        <div className="dimension-card">
          <span className="muted">items</span>
          <strong>{dashboard.golden_regression.item_count}</strong>
        </div>
        <div className="dimension-card">
          <span className="muted">flagged</span>
          <strong>{dashboard.golden_regression.flagged_count}</strong>
        </div>
        <div className="dimension-card">
          <span className="muted">last run</span>
          <strong>
            {dashboard.golden_regression.last_run_at
              ? new Date(dashboard.golden_regression.last_run_at).toLocaleString()
              : '--'}
          </strong>
        </div>
      </div>
      {goldenDimensions.length > 0 && (
        <div className="dimension-cards">
          {goldenDimensions.map(([dim, stat]) => (
            <div key={dim} className="dimension-card">
              <span className="muted">{dim.replace('_', ' ')}</span>
              <strong>{stat.mean !== null ? stat.mean.toFixed(2) : '--'}</strong>
              <span className="muted">{stat.sample_count} samples</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
