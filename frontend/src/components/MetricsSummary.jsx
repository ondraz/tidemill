import React from 'react'
import './MetricsSummary.css'

const MetricsSummary = ({ summary }) => {
  const formatCurrency = (value) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(value)
  }

  const formatPercent = (value) => {
    return `${value.toFixed(1)}%`
  }

  const metrics = [
    {
      label: 'Monthly Recurring Revenue',
      value: formatCurrency(summary.mrr),
      icon: '💰',
      color: '#4CAF50'
    },
    {
      label: 'Annual Recurring Revenue',
      value: formatCurrency(summary.arr),
      icon: '📈',
      color: '#2196F3'
    },
    {
      label: 'Customer Lifetime Value',
      value: formatCurrency(summary.ltv),
      icon: '⭐',
      color: '#FF9800'
    },
    {
      label: 'Customer Retention',
      value: formatPercent(summary.retention),
      icon: '🔒',
      color: '#9C27B0'
    },
    {
      label: 'Churn Rate',
      value: formatPercent(summary.churn_rate),
      icon: '📉',
      color: '#F44336'
    },
    {
      label: 'Total Customers',
      value: Math.round(summary.customer_count),
      icon: '👥',
      color: '#607D8B'
    }
  ]

  return (
    <div className="metrics-summary">
      {metrics.map((metric, index) => (
        <div 
          key={index} 
          className="metric-card"
          style={{ borderTopColor: metric.color }}
        >
          <div className="metric-icon">{metric.icon}</div>
          <div className="metric-content">
            <div className="metric-label">{metric.label}</div>
            <div className="metric-value" style={{ color: metric.color }}>
              {metric.value}
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}

export default MetricsSummary
