import type { ChartSurfaceHandle, ChartSurfaceLinkedTimeRange } from '../chart-adapter/useChartSurfaceRuntime'

export const linkLabels = { symbol: '交易对', interval: '周期', crosshair: '十字线', range: '可见范围', studies: '指标' }
export type LinkOptions = Record<keyof typeof linkLabels, boolean>
export const defaultLinks: LinkOptions = { symbol: false, interval: false, crosshair: false, range: false, studies: false }

export function readViewport(key: string): ChartSurfaceLinkedTimeRange | null {
  try {
    const range = JSON.parse(localStorage.getItem(key) ?? 'null') as Partial<ChartSurfaceLinkedTimeRange> | null
    if (!range || typeof range.from !== 'number' || typeof range.to !== 'number'
      || !Number.isFinite(range.from) || !Number.isFinite(range.to) || range.from >= range.to) return null
    return { from: range.from, to: range.to }
  } catch { return null }
}
export function saveViewport(key: string, range: ChartSurfaceLinkedTimeRange) {
  try { localStorage.setItem(key, JSON.stringify(range)) } catch { /* Storage unavailable. */ }
}

export class BrowserChartLinks {
  handles = new Map<number, ChartSurfaceHandle>()
  private viewKeys = new Map<number, string>()
  private pendingViews = new Map<number, ChartSurfaceLinkedTimeRange>()
  register(slot: number, handle: ChartSurfaceHandle | null, viewKey: string) {
    if (handle) {
      this.handles.set(slot, handle)
      this.viewKeys.set(slot, viewKey)
    } else {
      this.handles.delete(slot)
      this.viewKeys.delete(slot)
      this.pendingViews.delete(slot)
    }
  }
  applyPending(slot: number) {
    const range = this.pendingViews.get(slot)
    const key = this.viewKeys.get(slot)
    if (!range || !key || !this.handles.get(slot)?.setLinkedVisibleTimeRange(range)) return false
    saveViewport(key, range)
    this.pendingViews.delete(slot)
    return true
  }
  cancelPending() { this.pendingViews.clear() }
  private pointerSlot: number | null = null
  pointer(slot: number | null) { this.pointerSlot = slot }
  crosshair(slot: number, time: number | null) {
    if (slot !== this.pointerSlot) return
    for (const [other, handle] of this.handles) if (other !== slot) handle.setLinkedCrosshairTime(time)
  }
  range(slot: number, range: ChartSurfaceLinkedTimeRange) {
    for (const other of this.handles.keys()) {
      if (other === slot) continue
      this.pendingViews.set(other, range)
      this.applyPending(other)
    }
  }
}
