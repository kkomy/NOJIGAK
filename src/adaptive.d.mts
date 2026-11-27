export type RoutineConfig = { id:string; name:string; base:number; guide:string; icon:string; predictedDuration?:number; initialAllocatedDuration?:number; allocatedDuration:number; minDuration:number; priority:'required'|'normal'|'optional'; flexibility:number; skippable:boolean; [key:string]:any }
export type AdaptiveLog = { id?:string; routineId:string; actual:number; planned?:number; initialPlanned?:number; completed:boolean; skipped:boolean; abnormal?:boolean; executionMode?:'normal'|'compressed'|'emergency'; context?:string; start?:string }
export type RescheduleChange = { routineId:string; name:string; from:number; to:number; delta:number; reason:string }
export type RebalanceResult = { allocations:Record<string,number>; reserve:number; changes:RescheduleChange[]; reserveUsed:number; activeRemainingMinutes:number; activeEstimateTemporary:boolean; slackMinutes:number; shortfallMinutes:number; proposedSkips:string[]; needsEmergency:boolean; deficitBeforeCuts:number }
export type RiskBottleneck = { routineId:string; name:string; excessMinutes:number; meanOverrun:number; onTimeRate:number|null; contribution:number; share:number }
export type RiskReport = { probability:number|null; dataSufficient:boolean; expectedMinutes:number; slackMinutes:number; level:'safe'|'caution'|'risk'; estimatedReadyAt:Date; bottlenecks:RiskBottleneck[]; simulations:number }
export type EmergencyPlan = RebalanceResult & { skippedIds:string[]; skippedMinutes:number; unavoidableMinutes:number; normal:RebalanceResult }
export function migrateRoutine(raw:any): RoutineConfig
export function predictDuration(routine:RoutineConfig, logs?:AdaptiveLog[], context?:string): { minutes:number; count:number; contextCount:number; learned:boolean }
export function predictTransitionDuration(logs?:Array<AdaptiveLog & { transitionDuration?:number }>, minimumSamples?:number): { minutes:number; count:number; learned:boolean }
export function initialAllocations(routines:RoutineConfig[], logs?:AdaptiveLog[], context?:string): Record<string,number>
export function rebalanceSchedule(args:any): RebalanceResult
export function createEmergencyPlan(args:any): EmergencyPlan
export function riskReport(args:any): RiskReport
export function emergencyLogTags(mode?:'compressed'|'emergency'): { executionMode:string; excludeFromLearning:boolean }
