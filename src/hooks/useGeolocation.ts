import { useCallback, useEffect, useState } from 'react'

export type GeoStatus = 'idle' | 'loading' | 'success' | 'denied' | 'error'
export type CurrentLocation = { latitude: number; longitude: number; accuracy: number; timestamp: number }

export function useGeolocation(enabled: boolean) {
  const [status, setStatus] = useState<GeoStatus>('idle')
  const [location, setLocation] = useState<CurrentLocation | null>(null)
  const [message, setMessage] = useState('')

  const requestLocation = useCallback(() => new Promise<CurrentLocation | null>(resolve => {
    if (!('geolocation' in navigator)) {
      setStatus('error')
      setMessage('이 브라우저에서는 현재 위치를 사용할 수 없어요. 출발지를 직접 입력해 주세요.')
      resolve(null)
      return
    }
    setStatus('loading')
    setMessage('현재 위치를 확인하고 있어요…')
    navigator.geolocation.getCurrentPosition(position => {
      const current = {
        latitude: position.coords.latitude,
        longitude: position.coords.longitude,
        accuracy: position.coords.accuracy,
        timestamp: position.timestamp,
      }
      setLocation(current)
      setStatus('success')
      setMessage(`현재 위치를 확인했어요 · 정확도 약 ${Math.round(current.accuracy)}m`)
      resolve(current)
    }, error => {
      const denied = error.code === error.PERMISSION_DENIED
      setStatus(denied ? 'denied' : 'error')
      setMessage(denied
        ? '위치 권한이 없어 현재 위치를 사용할 수 없어요. 출발지를 직접 입력해 주세요.'
        : error.code === error.TIMEOUT
          ? '위치 확인 시간이 초과됐어요. 주소를 직접 입력하거나 다시 시도해 주세요.'
          : '현재 위치를 확인하지 못했어요. 주소를 직접 입력해 주세요.')
      resolve(null)
    }, { enableHighAccuracy: true, timeout: 8000, maximumAge: 60000 })
  }), [])

  useEffect(() => {
    if (!enabled || !navigator.permissions?.query) return
    let cancelled = false
    navigator.permissions.query({ name: 'geolocation' as PermissionName }).then(permission => {
      if (!cancelled && permission.state === 'granted') void requestLocation()
    }).catch(() => undefined)
    return () => { cancelled = true }
  }, [enabled, requestLocation])

  return { status, location, message, requestLocation }
}
