import axios from 'axios'

const API_BASE_URL = 'http://localhost:8000'

export const fetchMetricsSummary = async () => {
  const response = await axios.get(`${API_BASE_URL}/api/metrics/summary`)
  return response.data
}

export const fetchMetricData = async (metricType, startDate, endDate, interval = 'month') => {
  const params = new URLSearchParams()
  if (startDate) params.append('start_date', startDate)
  if (endDate) params.append('end_date', endDate)
  params.append('interval', interval)
  
  const response = await axios.get(
    `${API_BASE_URL}/api/metrics/${metricType}?${params.toString()}`
  )
  return response.data
}

export const syncStripeData = async () => {
  const response = await axios.post(`${API_BASE_URL}/api/sync/stripe`)
  return response.data
}

export const fetchCustomers = async (limit = 100, offset = 0) => {
  const response = await axios.get(
    `${API_BASE_URL}/api/customers?limit=${limit}&offset=${offset}`
  )
  return response.data
}
