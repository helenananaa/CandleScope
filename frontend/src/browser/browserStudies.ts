import type { IndicatorValuePoint } from '../features/indicators/indicatorTypes'

export const names = ['ma', 'ema', 'rsi'] as const
export type Study = typeof names[number]
export const sources = ['close', 'open', 'high', 'low', 'hl2', 'hlc3'] as const
export type Studies = Record<Study, { enabled: boolean; period: number; source: typeof sources[number] }>
export type StudyLines = Partial<Record<Study, IndicatorValuePoint[]>>

export function readStudies(saved?: Partial<Studies>, ma = true): Studies {
  function read(name: Study): Studies[Study] {
    const item = saved?.[name]
    return {
      enabled: typeof item?.enabled === 'boolean' ? item.enabled : name === 'ma' && ma,
      period: item && Number.isInteger(item.period) && item.period >= 2 && item.period <= 500
        ? item.period : name === 'rsi' ? 14 : 20,
      source: item && sources.includes(item.source) ? item.source : 'close',
    }
  }
  return { ma: read('ma'), ema: read('ema'), rsi: read('rsi') }
}
