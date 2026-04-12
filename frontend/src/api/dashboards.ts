import { get, post, put, del } from './client'
import type { Dashboard, DashboardDetail, SavedChart, ChartConfig } from '@/lib/types'

// Dashboards
export const listDashboards = () => get<Dashboard[]>('/api/dashboards')
export const getDashboard = (id: string) => get<DashboardDetail>(`/api/dashboards/${id}`)
export const createDashboard = (name: string, description?: string) =>
  post<Dashboard>('/api/dashboards', { name, description })
export const updateDashboard = (id: string, data: { name?: string; description?: string }) =>
  put<{ status: string }>(`/api/dashboards/${id}`, data)
export const deleteDashboard = (id: string) => del<{ status: string }>(`/api/dashboards/${id}`)

// Sections
export const createSection = (dashboardId: string, title: string, position: number = 0) =>
  post<{ id: string }>(`/api/dashboards/${dashboardId}/sections`, { title, position })
export const updateSection = (
  dashboardId: string,
  sectionId: string,
  data: { title?: string; position?: number },
) => put<{ status: string }>(`/api/dashboards/${dashboardId}/sections/${sectionId}`, data)
export const deleteSection = (dashboardId: string, sectionId: string) =>
  del<{ status: string }>(`/api/dashboards/${dashboardId}/sections/${sectionId}`)

// Dashboard charts
export const addChartToDashboard = (
  dashboardId: string,
  savedChartId: string,
  sectionId: string,
  position: number = 0,
) =>
  post<{ id: string }>(`/api/dashboards/${dashboardId}/charts`, {
    saved_chart_id: savedChartId,
    section_id: sectionId,
    position,
  })
export const removeChartFromDashboard = (dashboardId: string, chartId: string) =>
  del<{ status: string }>(`/api/dashboards/${dashboardId}/charts/${chartId}`)

// Saved charts
export const listCharts = () => get<SavedChart[]>('/api/charts')
export const createChart = (name: string, config: ChartConfig) =>
  post<SavedChart>('/api/charts', { name, config })
export const updateChart = (id: string, data: { name?: string; config?: ChartConfig }) =>
  put<{ status: string }>(`/api/charts/${id}`, data)
export const deleteChart = (id: string) => del<{ status: string }>(`/api/charts/${id}`)
