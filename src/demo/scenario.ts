import { initialAllocations, predictDuration, rebalanceSchedule } from '../adaptive.mjs'
import { DEMO_DATE, DEMO_ROUTE_KEY, demoRoutines, preparationHistory, travelHistory } from './fixtures.ts'

export type DemoRoutine = {
  id: string; name: string; base: number; minDuration: number; icon: string; allocatedDuration: number; skippable: boolean
  priority: 'required' | 'normal' | 'optional'; flexibility: number
  actualMinutes: number; guide: string
}
export type TravelRecordInput = Record<string, unknown>
export type DemoCalculations = {
  routines: DemoRoutine[]
  allocations: Record<string, number>
  learnedTravel: any
  initialPlan: any
  rebalance: any
  nextShowerMinutes: number
  nextTravel: any
  nextPlan: any
  nextTravelRecord: TravelRecordInput
}

export const DEMO_SCENES = [
  { id: 'opening', duration: 4, virtualTime: '06:20', caption: '수도권 장거리 이동자를 위한 AI 출발 코치' },
  { id: 'input', duration: 6, virtualTime: '06:20', caption: '목적지와 도착시간만 설정하면 됩니다.' },
  { id: 'departure', duration: 7, virtualTime: '06:20', caption: '교통 예상시간에 개인의 실제 이동 패턴까지 반영합니다.' },
  { id: 'preparation', duration: 7, virtualTime: '06:25', caption: '당신의 실제 준비 습관을 학습해 시간을 배분합니다.' },
  { id: 'coaching', duration: 23, virtualTime: '06:25–07:33', caption: '예상치 못한 지연에도 남은 시간을 다시 나눕니다.' },
  { id: 'departureActual', duration: 8, virtualTime: '07:33', caption: '출발시간뿐 아니라 실제 도착 결과까지 관리합니다.' },
  { id: 'arrival', duration: 9, virtualTime: '07:33–08:57', caption: '늦지도, 너무 이르지도 않게.' },
  { id: 'learning', duration: 10, virtualTime: '08:57', caption: '오늘의 경험을 내일의 계획에 반영했어요.' },
  { id: 'closing', duration: 4, virtualTime: '08:57', caption: '준비부터 도착까지, 당신의 시간을 최적화합니다.' },
] as const
export const DEMO_DURATION_SECONDS = DEMO_SCENES.reduce((sum, scene) => sum + scene.duration, 0)

const jsonPost = async <T,>(path: string, body: unknown): Promise<T> => {
  const controller = new AbortController()
  const timeout = globalThis.setTimeout(() => controller.abort(), 3500)
  try {
    const response = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal: controller.signal })
    if (!response.ok) throw new Error(`${path} 요청이 실패했어요 (${response.status}).`)
    return await response.json() as T
  } finally { globalThis.clearTimeout(timeout) }
}

export async function prepareDemoCalculations(): Promise<DemoCalculations> {
  const allocations = initialAllocations(demoRoutines, preparationHistory, 'commute')
  const preparationTotal = Object.values(allocations).reduce((sum, duration) => sum + duration, 0)
  const planRequest = {
    route_key: DEMO_ROUTE_KEY, base_travel_minutes: 70, prediction_source: 'api', strategy: 'balanced', history: travelHistory, demo_context: true,
    target_arrival_at: `${DEMO_DATE}T09:00:00+09:00`, routine_minutes: preparationTotal,
    transition_minutes: 0, reserve_minutes: 5, arrival_buffer_minutes: 4, extra_travel_buffer_minutes: 0,
  }
  const nextShowerMinutes = predictDuration(demoRoutines[0], [
    ...preparationHistory,
    { id: 'demo-shower-arrival', routineId: 'shower', actual: 22 * 60, completed: true, skipped: false, abnormal: false, executionMode: 'normal', context: 'commute' },
  ], 'commute').minutes
  // This remains a demo-marked fact in the explicit stateless preview context.
  // No completion endpoint or persistent learning store is called.
  const nextTravelRecord: TravelRecordInput = {
    id: 'demo-trip-arrival', run_id: 'demo-arrival-run', route_key: DEMO_ROUTE_KEY,
    target_arrival_at: `${DEMO_DATE}T09:00:00+09:00`, recommended_departure_at: null,
    actual_departure_at: `${DEMO_DATE}T07:33:00+09:00`, actual_arrival_at: `${DEMO_DATE}T08:57:00+09:00`,
    api_travel_minutes: 70, prediction_source: 'api', strategy: 'balanced', abnormal: false,
    is_demo: true, has_intermediate_stop: false,
  }
  const historyAfterArrival = [...travelHistory, nextTravelRecord]
  const nextRequest = { ...planRequest, history: historyAfterArrival, routine_minutes: preparationTotal + (nextShowerMinutes - allocations.shower) }
  const [initialPlan, nextPlan] = await Promise.all([
    jsonPost<any>('/api/travel/plan', planRequest),
    jsonPost<any>('/api/travel/plan', nextRequest),
  ])
  const learnedTravel = initialPlan.prediction
  const deadlineMs = new Date(initialPlan.recommended_departure_at).getTime()
  const virtualNowMs = new Date(`${DEMO_DATE}T06:47:00+09:00`).getTime()
  const rebalance = rebalanceSchedule({
    routines: demoRoutines, allocations, initial: allocations, activeId: 'shower', elapsedMinutes: 22,
    activeRemainingOverride: 0, deadlineMs, nowMs: virtualNowMs, reserve: 5,
  })
  const nextTravel = nextPlan.prediction
  return { routines: demoRoutines, allocations, learnedTravel, initialPlan, rebalance, nextShowerMinutes, nextTravel, nextPlan, nextTravelRecord }
}
