import { useState, useEffect, useRef } from 'react'

export default function usePolling(url, interval = 5000) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const mountedRef = useRef(true)

  useEffect(() => {
    mountedRef.current = true

    const fetch_ = async () => {
      try {
        const res = await fetch(url)
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const json = await res.json()
        if (mountedRef.current) { setData(json); setError(null) }
      } catch (e) {
        if (mountedRef.current) setError(e.message)
      }
    }

    fetch_()
    const timer = setInterval(fetch_, interval)
    return () => { mountedRef.current = false; clearInterval(timer) }
  }, [url, interval])

  return { data, error }
}
