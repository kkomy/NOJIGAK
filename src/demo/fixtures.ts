import type { DemoRoutine, TravelRecordInput } from './scenario'

export const DEMO_DATE = '2026-11-27'
export const DEMO_ROUTE_KEY = 'demo:suwon-to-gangnam:commute'

export const demoRoutines: DemoRoutine[] = [
  { id: 'shower', name: '샤워', base: 12, minDuration: 8, priority: 'required', flexibility: 0.5, actualMinutes: 22, guide: '알림이 울리면 하던 일을 마무리하고 바로 샤워를 시작해요.', icon: '◌', allocatedDuration: 12, skippable: false },
  { id: 'meal', name: '식사', base: 16, minDuration: 12, priority: 'required', flexibility: 0, actualMinutes: 20, guide: '식사를 마무리하고 식기를 정리해요.', icon: '◒', allocatedDuration: 16, skippable: false },
  { id: 'outfit', name: '옷 입기', base: 8, minDuration: 6, priority: 'required', flexibility: 0, actualMinutes: 10, guide: '옷매무새를 확인하고 외출 준비를 해요.', icon: '⌁', allocatedDuration: 8, skippable: false },
  { id: 'groom', name: '그루밍', base: 8, minDuration: 8, priority: 'normal', flexibility: 1, actualMinutes: 11, guide: '최종 점검 후 도구를 정리해요.', icon: '✳', allocatedDuration: 8, skippable: false },
  { id: 'bag', name: '짐 챙기기', base: 4, minDuration: 3, priority: 'required', flexibility: 0, actualMinutes: 5, guide: '필수품을 확인하고 가방을 닫아요.', icon: '▱', allocatedDuration: 4, skippable: false },
]

export const preparationHistory = demoRoutines.flatMap((routine) =>
  Array.from({ length: 8 }, (_, index) => ({
    id: `demo-${routine.id}-${index + 1}`,
    routineId: routine.id,
    name: routine.name,
    actual: routine.base * 60 * 1.5,
    completed: true,
    skipped: false,
    abnormal: false,
    executionMode: 'normal' as const,
  })),
)

const historicalDurations = [82, 78, 85, 86, 79, 82, 78, 85]
export const travelHistory: TravelRecordInput[] = historicalDurations.map((minutes, index) => {
  const day = String(19 + index).padStart(2, '0')
  const actualArrival = new Date(`${DEMO_DATE.slice(0, 4)}-${DEMO_DATE.slice(5, 7)}-${day}T08:52:00+09:00`)
  const actualDeparture = new Date(actualArrival.getTime() - minutes * 60_000)
  return {
    id: `demo-travel-${index + 1}`,
    run_id: `demo-run-${index + 1}`,
    route_key: DEMO_ROUTE_KEY,
    target_arrival_at: `${DEMO_DATE.slice(0, 4)}-${DEMO_DATE.slice(5, 7)}-${day}T09:00:00+09:00`,
    recommended_departure_at: null,
    actual_departure_at: actualDeparture.toISOString(),
    actual_arrival_at: actualArrival.toISOString(),
    api_travel_minutes: 70,
    predicted_travel_minutes: null,
    effective_travel_minutes: null,
    prediction_source: 'api',
    strategy: 'balanced',
    abnormal: false,
    is_demo: true,
    has_intermediate_stop: false,
  }
})
