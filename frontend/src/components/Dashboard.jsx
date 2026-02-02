import React, { useState, useEffect } from 'react'
import MetricChart from './MetricChart'
import { fetchMetricData } from '../services/api'
import './Dashboard.css'

const Dashboard = () => {
  const [selectedMetric, setSelectedMetric] = useState('mrr')
  const [timeRange, setTimeRange] = useState('1y')
  const [interval, setInterval] = useState('month')
  const [chartData, setChartData] = useState([])
  const [loading, setLoading] = useState(false)

  const metrics = [
    { id: 'mrr', label: 'MRR', icon: '💰' },
    { id: 'arr', label: 'ARR', icon: '📈' },
    { id: 'ltv', label: 'LTV', icon: '⭐' },
    { id: 'retention', label: 'Retention', icon: '🔒' },
    { id: 'renewal_rate', label: 'Renewal Rate', icon: '🔄' },
    { id: 'churn_rate', label: 'Churn Rate', icon: '📉' },
    { id: 'customer_count', label: 'Customers', icon: '👥' }
  ]

  const timeRanges = [
    { id: '3m', label: '3 Months', days: 90 },
    { id: '6m', label: '6 Months', days: 180 },
    { id: '1y', label: '1 Year', days: 365 },
    { id: '2y', label: '2 Years', days: 730 }
  ]

  useEffect(() => {
    loadMetricData()
  }, [selectedMetric, timeRange, interval])

  const loadMetricData = async () => {
    try {
      setLoading(true)
      
      const range = timeRanges.find(r => r.id === timeRange)
      const endDate = new Date()
      const startDate = new Date()
      startDate.setDate(startDate.getDate() - range.days)

      const data = await fetchMetricData(
        selectedMetric,
        startDate.toISOString().split('T')[0],
        endDate.toISOString().split('T')[0],
        interval
      )
      
      setChartData(data)
    } catch (err) {
      console.error('Error loading metric data:', err)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="dashboard">
      <div className="dashboard-controls">
        <div className="metric-selector">
          <label>Select Metric:</label>
          <div className="metric-buttons">
            {metrics.map(metric => (
              <button
                key={metric.id}
                className={`metric-button ${selectedMetric === metric.id ? 'active' : ''}`}
                onClick={() => setSelectedMetric(metric.id)}
              >
                <span className="metric-button-icon">{metric.icon}</span>
                <span className="metric-button-label">{metric.label}</span>
              </button>
            ))}
          </div>
        </div>

        <div className="time-controls">
          <div className="control-group">
            <label>Time Range:</label>
            <select 
              value={timeRange} 
              onChange={(e) => setTimeRange(e.target.value)}
            >
              {timeRanges.map(range => (
                <option key={range.id} value={range.id}>
                  {range.label}
                </option>
              ))}
            </select>
          </div>

          <div className="control-group">
            <label>Interval:</label>
            <select 
              value={interval} 
              onChange={(e) => setInterval(e.target.value)}
            >
              <option value="day">Daily</option>
              <option value="week">Weekly</option>
              <option value="month">Monthly</option>
              <option value="year">Yearly</option>
            </select>
          </div>
        </div>
      </div>

      <div className="chart-container">
        {loading ? (
          <div className="chart-loading">Loading chart data...</div>
        ) : (
          <MetricChart 
            data={chartData}
            metricType={selectedMetric}
            metricLabel={metrics.find(m => m.id === selectedMetric)?.label}
          />
        )}
      </div>
    </div>
  )
}

export default Dashboard
