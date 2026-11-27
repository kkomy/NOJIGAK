import { useEffect, useMemo, useRef, useState } from 'react'
import { Pause, Play, RotateCcw, X } from 'lucide-react'
import { DEMO_DURATION_SECONDS, DEMO_SCENES, prepareDemoCalculations, type DemoCalculations } from './scenario.ts'
import './demo.css'

type Status = 'idle' | 'preparing' | 'playing' | 'paused' | 'completed'
const formatTime = (value?: string | null) => value ? new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(new Date(value)) : '—'
const mmss = (seconds: number) => `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`
const speak = (text: string) => {
  if (!('speechSynthesis' in window) || !('SpeechSynthesisUtterance' in window)) return
  window.speechSynthesis.cancel()
  const utterance = new SpeechSynthesisUtterance(text)
  utterance.lang = 'ko-KR'; utterance.rate = 1
  window.speechSynthesis.speak(utterance)
}

export function DemoPlayer({ onClose, autoStart = false }: { onClose: () => void; autoStart?: boolean }) {
  const [status, setStatus] = useState<Status>('idle')
  const [data, setData] = useState<DemoCalculations | null>(null)
  const [error, setError] = useState('')
  const [elapsed, setElapsed] = useState(0)
  const [showControls, setShowControls] = useState(false)
  const [recordingMode, setRecordingMode] = useState(false)
  const startedAt = useRef(0)
  const pausedAt = useRef(0)
  const autoStarted = useRef(false)

  const offsets = useMemo(() => DEMO_SCENES.map((scene, index) => DEMO_SCENES.slice(0, index).reduce((sum, item) => sum + item.duration, 0)), [])
  const sceneIndex = status === 'completed' ? DEMO_SCENES.length - 1 : Math.max(0, offsets.findIndex((offset, index) => elapsed < (offsets[index + 1] ?? DEMO_DURATION_SECONDS)))
  const scene = DEMO_SCENES[sceneIndex]
  const sceneElapsed = Math.max(0, elapsed - offsets[sceneIndex])
  const sceneProgress = Math.min(1, sceneElapsed / scene.duration)

  const start = async () => {
    setStatus('preparing'); setError(''); setElapsed(0)
    try {
      const prepared = await prepareDemoCalculations()
      setData(prepared)
      startedAt.current = performance.now()
      setStatus('playing')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '시연 계산을 준비하지 못했어요.')
      setStatus('idle')
    }
  }
  const reset = () => { window.speechSynthesis?.cancel(); setStatus('idle'); setElapsed(0); setData(null); setError('') }
  const pause = () => { if (status !== 'playing') return; pausedAt.current = performance.now(); setStatus('paused'); window.speechSynthesis?.pause() }
  const resume = () => { if (status !== 'paused') return; startedAt.current += performance.now() - pausedAt.current; setStatus('playing'); window.speechSynthesis?.resume() }

  useEffect(() => {
    if (autoStart && !autoStarted.current) { autoStarted.current = true; void start() }
  }, [])

  useEffect(() => {
    if (status !== 'playing') return
    const timer = window.setInterval(() => {
      const next = Math.min(DEMO_DURATION_SECONDS, Math.floor((performance.now() - startedAt.current) / 1000))
      setElapsed(next)
      if (next >= DEMO_DURATION_SECONDS) { setStatus('completed'); window.speechSynthesis?.cancel() }
    }, 100)
    return () => window.clearInterval(timer)
  }, [status])

  useEffect(() => {
    if (status !== 'playing') return
    if (scene.id === 'coaching') {
      if (sceneElapsed === 0) speak('샤워할 시간이에요. 15분 동안 샤워에만 집중해 볼까요?')
      if (sceneElapsed === 5) speak('5분 남았어요. 이제 헹구고 샤워를 마무리할 시간이에요.')
      if (sceneElapsed === 9) speak('목표 시간에 도달했어요. 지금 마무리하고 다음 행동으로 넘어가 볼까요?')
      if (sceneElapsed === 12) speak('목표보다 7분 더 걸리고 있어요. 필요한 시간을 확보할게요.')
      if (sceneElapsed === 14) speak('샤워 완료. 이제 식사를 시작해요.')
      if (sceneElapsed === 16) speak('식사 완료. 이제 옷을 입어요.')
      if (sceneElapsed === 18) speak('옷 입기 완료. 이제 그루밍을 해요.')
      if (sceneElapsed === 20) speak('그루밍 완료. 가방을 챙겨요.')
    }
  }, [scene.id, sceneElapsed, status])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { window.speechSynthesis?.cancel(); onClose() }
      if (event.code === 'Space' && status === 'playing') { event.preventDefault(); pause() }
      if (event.key.toLowerCase() === 'r') setRecordingMode(value => !value)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose, status])

  useEffect(() => () => { window.speechSynthesis?.cancel() }, [])

  const activityIndex = sceneElapsed < 14 ? 0 : Math.min(4, 1 + Math.floor((sceneElapsed - 14) / 2.2))
  const completedRoutines = sceneElapsed < 14 ? 0 : sceneElapsed >= 22 ? 5 : Math.min(4, 1 + Math.floor((sceneElapsed - 14) / 2.2))
  const showerPhase = sceneElapsed < 14
  const routineItems = data?.routines ?? []
  const displaySource = data?.learnedTravel
  const behaviorLabels = ['샤워', '식사', '옷 입기', '그루밍', '짐 챙기기']

  return <div className={`demo-stage ${recordingMode ? 'recording-mode' : ''}`} role="dialog" aria-modal="true" aria-label="노지각 자동 가상 시나리오">
    <div className="demo-frame">
      <header className="demo-topline"><div className="demo-brand"><span className="demo-brand-mark">N</span><span>노지각<small>늦지도, 너무 이르지도 않게</small></span></div><div className="demo-clock"><span>가상 시각</span><b>{scene.virtualTime}</b></div></header>
      <main className={`demo-content demo-scene-${scene.id}`} key={scene.id}>
        {status === 'idle' || status === 'preparing' ? <section className="demo-start-card">
          <span className="demo-eyebrow">AI DEPARTURE COACH · 시연 모드</span>
          <h1>너무 일찍 출발하면 시간 낭비,<br/>조금 늦게 출발하면 지각.</h1>
          <p>수도권 장거리 이동자를 위한 AI 출발 코치</p>
          {error && <div className="demo-error">이동시간 개인화 API에 연결할 수 없어요. 백엔드가 켜져 있는지 확인한 뒤 다시 시작해 주세요.<small>{error}</small></div>}
          <button className="demo-primary" onClick={() => { speak('노지각. 너무 일찍 출발하면 시간 낭비, 조금 늦게 출발하면 지각.'); void start() }} disabled={status === 'preparing'}><Play size={17} fill="currentColor"/>{status === 'preparing' ? '가상 계산 준비 중…' : '가상 시나리오 시작 — 78초 체험'}</button>
          <small className="demo-provenance">가상 데이터 기반 시연 · GPS 및 실제 교통 조회 없음</small>
        </section> : <>
          <div className="demo-scene-header"><span className="demo-eyebrow">{String(sceneIndex + 1).padStart(2, '0')} / 09 · {scene.id === 'coaching' ? 'BEHAVIOR COACHING' : 'NO LATE'}</span><span className="demo-scene-label">{scene.caption}</span></div>

          {scene.id === 'opening' && <section className="demo-opening"><span className="demo-monogram">N</span><h1>노지각</h1><b>너무 일찍 출발하면 시간 낭비,<br/>조금 늦게 출발하면 지각.</b><p>수도권 장거리 이동자를 위한 AI 출발 코치</p></section>}

          {scene.id === 'input' && <section className="demo-input-scene card schedule-wizard"><span className="eyebrow">STEP 1</span><h1>어디에 가나요?</h1><label className="field-label">목적지</label><input readOnly value="강남역"/><label className="field-label">출발지</label><div className="demo-origin">경기도 수원 <small>가상 위치 · GPS를 요청하지 않아요</small></div><label className="field-label">목표 도착시간</label><input readOnly value="오전 09:00"/><p>과거 준비 및 이동 기록을 반영했어요.</p><small className="demo-provenance">가상 데이터 기반 시연</small></section>}

          {scene.id === 'departure' && data && <section className="demo-departure-scene"><div><small>늦지 않으려면</small><strong>{formatTime(data.initialPlan.recommended_departure_at)}</strong><b>까지 출발하세요</b><span>과거 이동기록과 여유시간을 반영한 추천 출발시간</span></div><div className="demo-components"><p><span>교통 API 예상 <small>시연용 입력값</small></span><b>{displaySource?.api_travel_minutes ?? 70}분</b></p><p><span>개인화 보정</span><b>+{Number(displaySource?.personal_correction_minutes ?? 0).toFixed(1)}분</b></p><p><span>균형 전략 여유</span><b>+{Number(displaySource?.strategy_margin_minutes ?? 0).toFixed(1)}분</b></p><p><span>도착 여유</span><b>+4분</b></p></div><small className="demo-caveat">추천 시각은 과거 기록 기반 추정이며 정시 도착을 보장하지 않아요.</small></section>}

          {scene.id === 'preparation' && data && <section className="demo-preparation-scene"><div className="demo-prep-lead"><small>준비 시작 추천</small><strong>{formatTime(data.initialPlan.recommended_preparation_start_at)}</strong><b>부터 준비하세요</b><p>예비시간 5분은 별도로 유지해요.</p></div><div className="demo-routine-grid">{routineItems.map(item => <div key={item.id}><span>{item.name}</span><small>{item.base} → {data.allocations[item.id]}분</small></div>)}</div><div className="demo-total"><span>기본 준비시간</span><b>48분</b><i>→</i><span>개인화 준비시간</span><b>{Object.values(data.allocations).reduce((a,b)=>a+b,0)}분</b></div></section>}

          {scene.id === 'coaching' && data && <section className="demo-coaching-scene"><div className="demo-coach-copy"><span className="demo-ring">{showerPhase ? sceneElapsed < 5 ? '15' : sceneElapsed < 7 ? '10' : sceneElapsed < 9 ? '05' : sceneElapsed < 12 ? '00' : '+07' : '→'}</span><div><small>{showerPhase ? '샤워 · 행동 시작 알림' : `${behaviorLabels[activityIndex]} 시작`}</small><h1>{showerPhase ? sceneElapsed < 5 ? '알림이 울리면 하던 일을 마무리하고 바로 시작해요.' : sceneElapsed < 7 ? '10분 남았어요. 지금 하는 단계에 집중해요.' : sceneElapsed < 9 ? '5분 남았어요. 헹구고 마무리할 시간이에요.' : sceneElapsed < 12 ? '목표 시간이에요. 마무리하고 다음으로 넘어가 볼까요?' : '7분 더 걸리고 있어요. 필요한 시간을 확보할게요.' : `${behaviorLabels[activityIndex]}를 시작해요.`}</h1><p>목표 {showerPhase ? sceneElapsed < 12 ? data.allocations.shower : data.rebalance.allocations.shower : data.allocations[data.routines[activityIndex].id]}분 · 현재 {showerPhase ? sceneElapsed < 5 ? 0 : sceneElapsed < 7 ? 5 : sceneElapsed < 9 ? 10 : sceneElapsed < 12 ? 15 : 22 : data.routines[activityIndex].actualMinutes}분</p></div></div><div className="demo-progress-row"><b>{completedRoutines}/5 완료</b><div>{data.routines.map((routine, index) => <i className={`${index < completedRoutines ? 'done' : ''} ${index === activityIndex && completedRoutines < 5 ? 'current' : ''}`} key={routine.id}/>)}</div></div>{sceneElapsed >= 12 && sceneElapsed < 14 && <aside className="demo-rebalance"><b>남은 시간을 다시 계산했어요</b><span>예비시간 −{Math.ceil(data.rebalance.reserveUsed)}분</span><span>그루밍 {data.rebalance.changes.find((change: any) => change.routineId === 'groom')?.from} → {data.rebalance.allocations.groom}분</span></aside>}{sceneElapsed >= 14 && <div className="demo-complete-action">✓ 완료하고 다음 시작 <small>가상 완료 이벤트 · {behaviorLabels[activityIndex]}</small></div>}<small className="demo-psychology">적시 개입: 구체적인 마무리 안내 · 완료 진행률로 다음 행동 유도</small></section>}

          {scene.id === 'departureActual' && <section className="demo-actual-departure"><span className="demo-big-check">✓</span><small>준비 완료 · 5 / 5</small><h1>준비 완료!</h1><div className="demo-prep-duration">실제 준비 68분 · 06:25 → 07:33</div><div className="demo-time-pair"><span><small>추천 출발</small><b>{data && formatTime(data.initialPlan.recommended_departure_at)}</b></span><i>→</i><span><small>실제 출발</small><b>07:33</b></span></div><p>추천 출발시간보다 3분 늦었어요.<br/>아직 지각 여부를 확정하지 않았어요.</p><strong>출발하기</strong><small>가상 출발 이벤트 · 준비 타이머와 음성 코칭 종료</small></section>}

          {scene.id === 'arrival' && data && <section className="demo-arrival-scene"><div className="demo-route-label">수원 → 강남역 <span>가상 대중교통 이동</span></div><div className="demo-arrival-time"><small>도착했어요</small><strong>08:57</strong><b>3분 일찍 도착했어요!</b></div><div className="demo-trip-stats"><span><small>실제 출발</small><b>07:33</b></span><span><small>실제 이동</small><b>84분</b></span><span><small>목표 도착</small><b>09:00</b></span></div><small className="demo-caveat">실제 GPS가 아닌 명시적으로 시뮬레이션한 도착 기록이에요.</small></section>}

          {scene.id === 'learning' && data && <section className="demo-learning-scene"><div className="demo-learn-head"><span>AI LEARNING FEEDBACK</span><h1>오늘의 경험을 내일의 계획에 반영했어요.</h1></div><div className="demo-learn-columns"><article><small>준비시간 재학습</small><p>샤워 예측 <b>15분 → {data.nextShowerMinutes}분</b></p><span>정상 완료 가상 기록 +22분</span></article><article><small>이동시간 재학습</small><p>개인화 이동 <b>{Number(data.learnedTravel.point_estimate_minutes).toFixed(1)} → {Number(data.nextTravel.point_estimate_minutes).toFixed(1)}분</b></p><span>신규 residual +14분 · 표본 {data.nextTravel.sample_count}개</span></article></div><div className="demo-next-plan"><small>다음 일정 재계산</small><span>출발 추천 <b>{formatTime(data.initialPlan.recommended_departure_at)} → {formatTime(data.nextPlan.recommended_departure_at)}</b></span><span>다음 준비 시작 <b>{formatTime(data.nextPlan.recommended_preparation_start_at)}</b></span></div><small className="demo-caveat">한 번의 가상 사례이며 지각 방지 효과가 검증됐다는 뜻은 아니에요.</small></section>}

          {scene.id === 'closing' && <section className="demo-closing"><span className="demo-monogram">N</span><h1>노지각</h1><b>늦지도, 너무 이르지도 않게.</b><p>준비부터 도착까지, 당신의 시간을 최적화합니다.</p><div><span>개인화 학습</span><span>행동 코칭</span><span>동적 재분배</span><span>도착 결과 기반 재학습</span></div></section>}
        </>}
      </main>
      {status !== 'idle' && status !== 'preparing' && <footer className="demo-footer"><div className="demo-timeline"><i style={{ width: `${status === 'completed' ? 100 : elapsed / DEMO_DURATION_SECONDS * 100}%` }}/></div><div><span>{status === 'completed' ? '시연 완료' : `장면 ${sceneIndex + 1} · ${mmss(elapsed)} / 01:18`}</span><small>가상 데이터 기반 시연</small></div></footer>}
      {status === 'completed' && <div className="demo-end-mark">시연이 끝났어요</div>}
      {status === 'idle' && <div className="demo-footer idle"><span>가상 데이터 기반 시연</span><small>개인정보·학습 기록에 저장되지 않습니다.</small></div>}
      {!recordingMode && <div className={`demo-controls ${showControls ? 'expanded' : ''}`}>
        {showControls && <><button onClick={status === 'playing' ? pause : resume} disabled={status !== 'playing' && status !== 'paused'} aria-label={status === 'playing' ? '일시정지' : '재개'}>{status === 'playing' ? <Pause size={16}/> : <Play size={16}/>}</button><button onClick={reset} aria-label="다시 시작"><RotateCcw size={16}/></button><button onClick={onClose} aria-label="닫기"><X size={16}/></button><label><input type="checkbox" checked={recordingMode} onChange={(event) => setRecordingMode(event.target.checked)}/> 녹화 모드</label></>}
        <button className="demo-control-toggle" onClick={() => setShowControls(!showControls)} aria-label={showControls ? '조작 숨기기' : '시연 조작 열기'}>{showControls ? '숨기기' : '⋯'}</button>
      </div>}
    </div>
  </div>
}
