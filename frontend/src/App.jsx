import React, { useState, useEffect } from 'react'
import Dashboard from './components/Dashboard'
import MetricsSummary from './components/MetricsSummary'
import { fetchMetricsSummary } from './services/api'
import './App.css'

function App() {
  const [summary, setSummary] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    loadSummary()
  }, [])

  const loadSummary = async () => {
    try {
      setLoading(true)
      const data = await fetchMetricsSummary()
      setSummary(data)
      setError(null)
    } catch (err) {
      setError('Failed to load metrics summary')
      console.error('Error loading summary:', err)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="app">
      <header className="app-header">
        <h1>📊 SaaS Analytics Dashboard</h1>
        <p>Subscription business metrics powered by Stripe & Clickhouse</p>
      </header>

      <main className="app-main">
        {loading && <div className="loading">Loading metrics...</div>}
        
        {error && (
          <div className="error">
            {error}
            <button onClick={loadSummary}>Retry</button>
          </div>
        )}

        {!loading && !error && summary && (
          <>
            <MetricsSummary summary={summary} />
            <Dashboard />
          </>
        )}
      </main>

      <footer className="app-footer">
        <p>Data synced from Stripe • Last updated: {summary?.updated_at || 'Loading...'}</p>
      </footer>
    </div>
  )
}

export default App
