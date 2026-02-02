import React from 'react'
import {
  LineChart,
  Line,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer
} from 'recharts'

const MetricChart = ({ data, metricType, metricLabel }) => {
  const formatValue = (value) => {
    // Format currency for money metrics
    if (['mrr', 'arr', 'ltv'].includes(metricType)) {
      return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD',
        minimumFractionDigits: 0,
        maximumFractionDigits: 0,
      }).format(value)
    }
    
    // Format percentage for rate metrics
    if (['retention', 'renewal_rate', 'churn_rate'].includes(metricType)) {
      return `${value.toFixed(1)}%`
    }
    
    // Format as number for count metrics
    return Math.round(value).toLocaleString()
  }

  const getColor = () => {
    const colors = {
      mrr: '#4CAF50',
      arr: '#2196F3',
      ltv: '#FF9800',
      retention: '#9C27B0',
      renewal_rate: '#00BCD4',
      churn_rate: '#F44336',
      customer_count: '#607D8B'
    }
    return colors[metricType] || '#667eea'
  }

  const color = getColor()

  // Use area chart for growth metrics, line chart for rates
  const useAreaChart = ['mrr', 'arr', 'ltv', 'customer_count'].includes(metricType)

  return (
    <ResponsiveContainer width="100%" height={400}>
      {useAreaChart ? (
        <AreaChart data={data}>
          <defs>
            <linearGradient id={`gradient-${metricType}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={color} stopOpacity={0.3}/>
              <stop offset="95%" stopColor={color} stopOpacity={0}/>
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
          <XAxis 
            dataKey="date" 
            stroke="#666"
            style={{ fontSize: '0.85rem' }}
          />
          <YAxis 
            stroke="#666"
            style={{ fontSize: '0.85rem' }}
            tickFormatter={formatValue}
          />
          <Tooltip 
            formatter={formatValue}
            contentStyle={{
              backgroundColor: 'white',
              border: '1px solid #ddd',
              borderRadius: '8px',
              padding: '10px'
            }}
          />
          <Legend />
          <Area
            type="monotone"
            dataKey="value"
            name={metricLabel}
            stroke={color}
            strokeWidth={2}
            fill={`url(#gradient-${metricType})`}
          />
        </AreaChart>
      ) : (
        <LineChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
          <XAxis 
            dataKey="date" 
            stroke="#666"
            style={{ fontSize: '0.85rem' }}
          />
          <YAxis 
            stroke="#666"
            style={{ fontSize: '0.85rem' }}
            tickFormatter={formatValue}
          />
          <Tooltip 
            formatter={formatValue}
            contentStyle={{
              backgroundColor: 'white',
              border: '1px solid #ddd',
              borderRadius: '8px',
              padding: '10px'
            }}
          />
          <Legend />
          <Line
            type="monotone"
            dataKey="value"
            name={metricLabel}
            stroke={color}
            strokeWidth={2}
            dot={{ fill: color, r: 4 }}
            activeDot={{ r: 6 }}
          />
        </LineChart>
      )}
    </ResponsiveContainer>
  )
}

export default MetricChart
