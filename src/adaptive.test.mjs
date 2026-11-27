import test from 'node:test'
import assert from 'node:assert/strict'
import { createEmergencyPlan, initialAllocations, migrateRoutine, predictDuration, rebalanceSchedule, riskReport } from './adaptive.mjs'

const now = 1_800_000_000_000
const routine = (id, extra = {}) => ({ id, name: id, base: 10, minDuration: 5, priority: 'normal', flexibility: 1, skippable: false, ...extra })

test('a five minute delay consumes reserve before shortening future routines', () => {
  const current = routine('active'), future = routine('future')
  const result = rebalanceSchedule({ routines: [current, future], allocations: { active: 10, future: 10 }, activeId: 'active', elapsedMinutes: 15, deadlineMs: now + 15 * 60_000, nowMs: now, reserve: 5 })
  assert.equal(result.reserveUsed, 5)
  assert.equal(result.reserve, 0)
  assert.equal(result.allocations.future, 10)
  assert.equal(result.activeEstimateTemporary, true)
})

test('after reserve is exhausted, flexible work is reduced only within its minimum', () => {
  const result = rebalanceSchedule({ routines: [routine('active'), routine('future')], allocations: { active: 10, future: 10 }, activeId: 'active', elapsedMinutes: 10, deadlineMs: now + 10 * 60_000, nowMs: now, reserve: 5 })
  assert.equal(result.reserve, 0)
  assert.equal(result.allocations.future, 8)
  assert.equal(result.shortfallMinutes, 0)
})

test('required routine minimum is preserved and remaining shortfall is explicit', () => {
  const must = routine('must', { priority: 'required', minDuration: 8 })
  const result = rebalanceSchedule({ routines: [must], allocations: { must: 10 }, deadlineMs: now + 5 * 60_000, nowMs: now })
  assert.equal(result.allocations.must, 8)
  assert.equal(result.needsEmergency, true)
  assert.equal(result.shortfallMinutes, 3)
})

test('skippable work is proposed but never removed before approval', () => {
  const active = routine('active', { minDuration: 10, flexibility: 0 })
  const optional = routine('optional', { priority: 'optional', minDuration: 5, flexibility: 0, skippable: true })
  const result = rebalanceSchedule({ routines: [active, optional], allocations: { active: 10, optional: 5 }, activeId: 'active', elapsedMinutes: 0, deadlineMs: now + 10 * 60_000, nowMs: now })
  assert.deepEqual(result.proposedSkips, ['optional'])
  assert.equal(result.allocations.optional, 5)
  const emergency = createEmergencyPlan({ routines: [active, optional], allocations: { active: 10, optional: 5 }, activeId: 'active', deadlineMs: now + 10 * 60_000, nowMs: now })
  assert.deepEqual(emergency.skippedIds, ['optional'])
  assert.equal(emergency.unavoidableMinutes, 0)
})

test('early completion restores earlier cuts and preserves further slack as reserve', () => {
  const result = rebalanceSchedule({ routines: [routine('future')], allocations: { future: 6 }, initial: { future: 10 }, deadlineMs: now + 20 * 60_000, nowMs: now, reserve: 0 })
  assert.equal(result.allocations.future, 10)
  assert.equal(result.reserve, 10)
})

test('probability is withheld below ten usable samples and simulation uses observed durations', () => {
  const task = routine('task')
  const logs = Array.from({ length: 9 }, (_, i) => ({ id: String(i), routineId: 'task', actual: 300, planned: 600, completed: true, skipped: false }))
  let report = riskReport({ routines: [task], allocations: { task: 10 }, logs, deadlineMs: now + 600_000, nowMs: now })
  assert.equal(report.probability, null)
  logs.push({ id: '10', routineId: 'task', actual: 300, planned: 600, completed: true, skipped: false })
  report = riskReport({ routines: [task], allocations: { task: 10 }, logs, deadlineMs: now + 600_000, nowMs: now, random: () => 0 })
  assert.equal(report.dataSufficient, true)
  assert.equal(report.probability, 1)
})

test('compressed and emergency records do not alter normal personal estimates', () => {
  const task = routine('task')
  const normal = { id: 'normal', routineId: 'task', actual: 600, completed: true, skipped: false, executionMode: 'normal' }
  const emergency = { id: 'emergency', routineId: 'task', actual: 120, completed: true, skipped: false, executionMode: 'emergency' }
  assert.equal(predictDuration(task, [normal, emergency]).count, 1)
  assert.deepEqual(initialAllocations([migrateRoutine({ id: 'old', name: 'legacy', base: 12 })]), { old: 12 })
})

test('context model falls back before five examples and blends after the threshold', () => {
  const task = routine('task')
  const records = (count, context, minutes) => Array.from({ length: count }, (_, i) => ({ id: `${context}-${i}`, routineId: 'task', actual: minutes * 60, planned: 600, completed: true, skipped: false, context }))
  const underHistory = [...records(6, 'general', 10), ...records(4, 'important', 30)]
  const under = predictDuration(task, underHistory, 'important')
  const global = predictDuration(task, underHistory)
  const enough = predictDuration(task, [...underHistory, ...records(1, 'important', 30)], 'important')
  assert.equal(under.contextCount, 4)
  assert.equal(under.minutes, global.minutes)
  assert.equal(enough.contextCount, 5)
  assert.ok(enough.minutes > global.minutes)
})

test('cold start blending and EWMA/Q80 prediction retain the requested thresholds', () => {
  const task = routine('task')
  assert.equal(predictDuration(task, []).minutes, 10)
  const one = [{ routineId: 'task', actual: 20 * 60, completed: true, skipped: false }]
  assert.equal(predictDuration(task, one).minutes, 12)
  const ten = Array.from({ length: 10 }, (_, i) => ({ id: String(i), routineId: 'task', actual: (i < 9 ? 30 : 10) * 60, completed: true, skipped: false }))
  const prediction = predictDuration(task, ten)
  assert.equal(prediction.count, 10)
  assert.equal(prediction.minutes, 22)
})

test('active overtime uses only historical runs that exceed the current elapsed time', () => {
  const active = routine('active'), history = [{ routineId: 'active', actual: 20 * 60, completed: true, skipped: false }]
  const result = rebalanceSchedule({ routines: [active], allocations: { active: 10 }, activeId: 'active', elapsedMinutes: 14, logs: history, deadlineMs: now + 20 * 60_000, nowMs: now })
  assert.equal(result.activeRemainingMinutes, 6)
  assert.equal(result.activeEstimateTemporary, false)
})

test('slack risk has safe, caution, and risk boundaries and withholds a probability without samples', () => {
  const task = routine('task'), run = slack => riskReport({ routines: [task], allocations: { task: 10 }, deadlineMs: now + (10 + slack) * 60_000, nowMs: now })
  assert.equal(run(5).level, 'safe')
  assert.equal(run(4).level, 'caution')
  assert.equal(run(-1).level, 'risk')
  assert.equal(run(5).probability, null)
})

test('data-rich risk level follows simulated arrival probability, not compressed targets', () => {
  const task = routine('task'), logs = Array.from({ length: 10 }, (_, i) => ({ id: String(i), routineId: 'task', actual: 5 * 60, planned: 10 * 60, completed: true, skipped: false }))
  const report = riskReport({ routines: [task], allocations: { task: 1 }, logs, deadlineMs: now + 2 * 60_000, nowMs: now, random: () => 0 })
  assert.equal(report.probability, 0)
  assert.equal(report.level, 'risk')
})
