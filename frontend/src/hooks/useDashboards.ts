import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import * as api from '@/api/dashboards'
import type { ChartConfig } from '@/lib/types'

export function useDashboards() {
  return useQuery({ queryKey: ['dashboards'], queryFn: api.listDashboards })
}

export function useDashboard(id: string) {
  return useQuery({ queryKey: ['dashboards', id], queryFn: () => api.getDashboard(id) })
}

export function useCreateDashboard() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: { name: string; description?: string }) =>
      api.createDashboard(data.name, data.description),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['dashboards'] }),
  })
}

export function useDeleteDashboard() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: api.deleteDashboard,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['dashboards'] }),
  })
}

export function useCreateSection(dashboardId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: { title: string; position?: number }) =>
      api.createSection(dashboardId, data.title, data.position),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['dashboards', dashboardId] }),
  })
}

export function useDeleteSection(dashboardId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (sectionId: string) => api.deleteSection(dashboardId, sectionId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['dashboards', dashboardId] }),
  })
}

export function useSavedCharts() {
  return useQuery({ queryKey: ['charts'], queryFn: api.listCharts })
}

export function useSaveChart() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: { name: string; config: ChartConfig }) =>
      api.createChart(data.name, data.config),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['charts'] }),
  })
}

export function useAddChartToDashboard(dashboardId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: { savedChartId: string; sectionId: string; position?: number }) =>
      api.addChartToDashboard(dashboardId, data.savedChartId, data.sectionId, data.position),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['dashboards', dashboardId] }),
  })
}

export function useRemoveChartFromDashboard(dashboardId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (chartId: string) => api.removeChartFromDashboard(dashboardId, chartId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['dashboards', dashboardId] }),
  })
}
