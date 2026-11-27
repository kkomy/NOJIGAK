export const PRIORITIES = ['required', 'normal', 'optional']
export const RISK_THRESHOLDS = { safeSlackMinutes: 5, cautionProbability: 0.8, riskProbability: 0.5, simulationCount: 1000, minimumSamples: 10 }

export function migrateRoutine(raw) {
  const base = Math.max(1, Number(raw.base) || 10)
  return {
    ...raw,
    guide: raw.guide ?? '차근차근 마무리해요',
    icon: raw.icon ?? '✦',
    base,
    predictedDuration: Math.max(1, Number(raw.predictedDuration) || base),
    initialAllocatedDuration: Math.max(1, Number(raw.initialAllocatedDuration) || base),
    allocatedDuration: Math.max(1, Number(raw.allocatedDuration) || base),
    minDuration: Math.max(1, Math.min(base, Number(raw.minDuration) || Math.ceil(base * 0.75))),
    priority: PRIORITIES.includes(raw.priority) ? raw.priority : 'normal',
    flexibility: Number.isFinite(Number(raw.flexibility)) ? Math.min(1, Math.max(0, Number(raw.flexibility))) : 0.5,
    skippable: Boolean(raw.skippable),
  }
}

const validForLearning = log => log.completed && !log.skipped && !log.abnormal && (log.executionMode ?? 'normal') === 'normal' && log.actual > 0
const quantile80 = values => {
  const sorted = [...values].sort((a, b) => a - b)
  if (sorted.length === 1) return sorted[0]
  const at = (sorted.length - 1) * 0.8
  const low = Math.floor(at), high = Math.ceil(at)
  return sorted[low] + (sorted[high] - sorted[low]) * (at - low)
}
const ceilMinutes = value => Math.max(1, Math.ceil(value - 1e-9))
const recordsFor = (routine, logs) => logs.filter(log => log.routineId === routine.id && validForLearning(log))

function ewma(records) {
  let value = records[0].actual / 60
  for (const record of records.slice(1)) value = 0.25 * (record.actual / 60) + 0.75 * value
  return records.length >= 10 ? Math.max(value, quantile80(records.slice(-20).map(x => x.actual / 60))) : value
}

export function predictDuration(routine, logs = [], context = '') {
  const all = recordsFor(routine, logs)
  const fullValue = all.length ? ewma(all) : routine.base
  const fullWeight = all.length / (all.length + 8)
  const full = all.length ? (1 - fullWeight) * routine.base + fullWeight * fullValue : routine.base
  const matching = context ? all.filter(log => (log.context ?? '') === context) : []
  if (context && matching.length >= 5) {
    const contextValue = ewma(matching)
    const contextWeight = matching.length / (matching.length + 8)
    const contextual = (1 - contextWeight) * full + contextWeight * contextValue
    return { minutes: ceilMinutes(contextual), count: all.length, contextCount: matching.length, learned: true }
  }
  return { minutes: ceilMinutes(full), count: all.length, contextCount: matching.length, learned: all.length > 0 }
}

export function initialAllocations(routines, logs = [], context = '') {
  return Object.fromEntries(routines.map(r => [r.id, predictDuration(r, logs, context).minutes]))
}

function activeRemaining(routine, elapsedMinutes, allocation, logs, override) {
  if (Number.isFinite(override) && override >= 0) return { minutes: override, temporary: false }
  if (elapsedMinutes < allocation) return { minutes: allocation - elapsedMinutes, temporary: false }
  const longer = recordsFor(routine, logs).map(x => x.actual / 60).filter(x => x > elapsedMinutes).map(x => x - elapsedMinutes).sort((a, b) => a - b)
  if (longer.length) return { minutes: longer[Math.floor((longer.length - 1) / 2)], temporary: false }
  const over = elapsedMinutes - allocation
  return { minutes: Math.max(2, Math.ceil(over * 0.5) + 2), temporary: true }
}

const rank = priority => priority === 'optional' ? 0 : priority === 'normal' ? 1 : 2
const rmin = r => Math.max(1, Number(r.minDuration) || 1, Number(r.flexibility) === 0 ? Number(r.predictedDuration) || 1 : 1)
const availableCut = (routine, allocation) => Math.max(0, Math.floor((allocation - rmin(routine)) * routine.flexibility + 1e-9))

export function rebalanceSchedule({ routines, allocations, initial = allocations, done = [], activeId = null, elapsedMinutes = 0, logs = [], deadlineMs, nowMs = Date.now(), reserve = 0, activeRemainingOverride }) {
  const next = { ...allocations }, completed = new Set(done)
  const pending = routines.filter(r => !completed.has(r.id))
  const current = pending.find(r => r.id === activeId)
  const active = current ? activeRemaining(current, elapsedMinutes, next[current.id] ?? rmin(current), logs, activeRemainingOverride) : { minutes: 0, temporary: false }
  const future = pending.filter(r => r.id !== activeId)
  const secondsAvailable = Math.max(0, (deadlineMs - nowMs) / 60000)
  const needed = active.minutes + future.reduce((sum, r) => sum + (next[r.id] ?? rmin(r)), 0) + reserve
  let deficit = Math.max(0, needed - secondsAvailable)
  const reserveUsed = Math.min(reserve, deficit)
  let nextReserve = Math.max(0, reserve - reserveUsed)
  deficit -= reserveUsed
  const originalDeficit = deficit
  const changes = []
  if (deficit > 0) {
    const candidates = [...future].sort((a, b) => rank(a.priority) - rank(b.priority) || b.flexibility - a.flexibility)
    for (const routine of candidates) {
      if (deficit <= 1e-8) break
      const before = next[routine.id] ?? rmin(routine)
      const possible = availableCut(routine, before)
      const exactCut = Math.min(deficit, possible)
      const cut = Math.min(possible, Math.ceil(exactCut - 1e-9))
      if (cut <= 0) continue
      next[routine.id] = before - cut
      nextReserve += Math.max(0, cut - exactCut)
      deficit = Math.max(0, deficit - cut)
      changes.push({ routineId: routine.id, name: routine.name, from: before, to: next[routine.id], delta: -cut, reason: 'time_pressure' })
    }
  } else {
    let slack = Math.max(0, secondsAvailable - needed)
    const candidates = [...future].sort((a, b) => rank(b.priority) - rank(a.priority))
    for (const routine of candidates) {
      if (slack <= 1e-8) break
      const before = next[routine.id] ?? rmin(routine)
      const target = initial[routine.id] ?? before
      const restore = Math.min(Math.floor(slack + 1e-9), Math.max(0, target - before))
      if (restore <= 0) continue
      next[routine.id] = before + restore
      slack -= restore
      changes.push({ routineId: routine.id, name: routine.name, from: before, to: next[routine.id], delta: restore, reason: 'restore' })
    }
    if (slack > 1e-8) nextReserve += slack
  }
  const proposedSkips = deficit > 1e-8 ? future.filter(r => r.priority === 'optional' && r.skippable).map(r => r.id) : []
  const shortfallMinutes = Math.max(0, deficit)
  return {
    allocations: next, reserve: nextReserve, changes, reserveUsed,
    activeRemainingMinutes: active.minutes, activeEstimateTemporary: active.temporary,
    slackMinutes: secondsAvailable - active.minutes - future.reduce((sum, r) => sum + (next[r.id] ?? rmin(r)), 0),
    shortfallMinutes, proposedSkips, needsEmergency: shortfallMinutes > 1e-8,
    deficitBeforeCuts: originalDeficit,
  }
}

export function createEmergencyPlan({ routines, allocations, initial = allocations, done = [], activeId = null, elapsedMinutes = 0, logs = [], deadlineMs, nowMs = Date.now(), reserve = 0, activeRemainingOverride }) {
  const normal = rebalanceSchedule({ routines, allocations, initial, done, activeId, elapsedMinutes, logs, deadlineMs, nowMs, reserve, activeRemainingOverride })
  const next = { ...normal.allocations }, skip = []
  const pending = routines.filter(r => !done.includes(r.id) && r.id !== activeId)
  let left = normal.shortfallMinutes
  const candidates = pending.filter(r => r.priority === 'optional' && r.skippable).sort((a, b) => rank(a.priority) - rank(b.priority))
  for (const r of candidates) {
    if (left <= 1e-8) break
    skip.push(r.id); left -= next[r.id] ?? rmin(r)
  }
  const emergency = rebalanceSchedule({
    routines: routines.filter(r => !skip.includes(r.id)), allocations: next, initial,
    done, activeId, elapsedMinutes, logs, deadlineMs, nowMs, reserve: normal.reserve,
    activeRemainingOverride,
  })
  return { ...emergency, skippedIds: skip, skippedMinutes: normal.shortfallMinutes - left, unavoidableMinutes: Math.max(0, emergency.shortfallMinutes), normal }
}

export function riskReport({ routines, allocations, done = [], activeId = null, elapsedMinutes = 0, logs = [], context = '', deadlineMs, nowMs = Date.now(), reserve = 0, simulations = RISK_THRESHOLDS.simulationCount, random = Math.random, activeRemainingOverride }) {
  const completed = new Set(done), pending = routines.filter(r => !completed.has(r.id))
  const samples = new Map(), means = []
  for (const routine of pending) {
    const history = recordsFor(routine, logs).slice(-20).map(x => x.actual / 60)
    if (routine.id === activeId) {
      const remaining = history.filter(x => x > elapsedMinutes).map(x => x - elapsedMinutes)
      samples.set(routine.id, remaining)
      means.push(activeRemaining(routine, elapsedMinutes, allocations[routine.id] ?? rmin(routine), logs, activeRemainingOverride).minutes)
    } else {
      samples.set(routine.id, history)
      means.push(predictDuration(routine, logs, context).minutes)
    }
  }
  const expectedMinutes = means.reduce((a, b) => a + b, 0)
  const slackMinutes = (deadlineMs - nowMs) / 60000 - expectedMinutes
  const dataSufficient = pending.length > 0 && pending.every(r => (samples.get(r.id)?.length ?? 0) >= RISK_THRESHOLDS.minimumSamples)
  let probability = null
  if (dataSufficient) {
    let onTime = 0
    const remainingDeadline = Math.max(0, (deadlineMs - nowMs) / 60000)
    for (let i = 0; i < simulations; i++) {
      let total = 0
      for (const r of pending) {
        const list = samples.get(r.id)
        total += list[Math.min(list.length - 1, Math.floor(random() * list.length))]
      }
      if (total <= remainingDeadline) onTime++
    }
    probability = onTime / simulations
  }
  const slackLevel = slackMinutes >= RISK_THRESHOLDS.safeSlackMinutes ? 'safe' : slackMinutes >= 0 ? 'caution' : 'risk'
  const level = probability === null ? slackLevel : probability >= RISK_THRESHOLDS.cautionProbability ? 'safe' : probability >= RISK_THRESHOLDS.riskProbability ? 'caution' : 'risk'
  const bottlenecks = routines.map(r => {
    const valid = recordsFor(r, logs)
    const excess = valid.reduce((sum, log) => sum + Math.max(0, log.actual / 60 - (log.initialPlanned ?? log.planned) / 60), 0)
    return { routineId: r.id, name: r.name, excessMinutes: excess, meanOverrun: valid.length ? valid.reduce((sum, log) => sum + Math.max(0, log.actual / 60 - (log.initialPlanned ?? log.planned) / 60), 0) / valid.length : 0, onTimeRate: valid.length ? valid.filter(log => log.actual <= (log.initialPlanned ?? log.planned)).length / valid.length : null, contribution: excess }
  }).filter(x => x.excessMinutes > 0).sort((a, b) => b.contribution - a.contribution)
  const totalExcess = bottlenecks.reduce((sum, x) => sum + x.excessMinutes, 0)
  for (const item of bottlenecks) item.share = totalExcess ? item.excessMinutes / totalExcess : 0
  return { probability, dataSufficient, expectedMinutes, slackMinutes, level, estimatedReadyAt: new Date(nowMs + expectedMinutes * 60000), bottlenecks, simulations: probability === null ? 0 : simulations }
}

export function emergencyLogTags(mode = 'emergency') { return { executionMode: mode, excludeFromLearning: true } }
