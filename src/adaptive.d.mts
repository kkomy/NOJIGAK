export type RoutineConfig = { id:string; name:string; base:number; guide:string; icon:string; predictedDuration?:number; initialAllocatedDuration?:number; allocatedDuration:number; minDuration:number; priority:'required'|'normal'|'optional'; flexibility:number; skippable:boolean; [key:string]:any }
export type AdaptiveLog = { id?:string; routineId:string; actual:number; planned?:number; initialPlanned?:number; completed:boolean; skipped:boolean; abnormal?:boolean; executionMode?:'normal'|'compressed'|'emergency'; context?:string; start?:string }
export function migrateRoutine(raw:any): RoutineConfig
export function predictDuration(routine:RoutineConfig, logs?:AdaptiveLog[], context?:string): { minutes:number; count:number; contextCount:number; learned:boolean }
export function initialAllocations(routines:RoutineConfig[], logs?:AdaptiveLog[], context?:string): Record<string,number>
export function rebalanceSchedule(args:any): any
export function createEmergencyPlan(args:any): any
export function riskReport(args:any): any
export function emergencyLogTags(mode?:'compressed'|'emergency'): { executionMode:string; excludeFromLearning:boolean }
