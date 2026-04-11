import { useState, useEffect, useRef, useCallback } from 'react'

export default function useWebSocket(url) {
  const [connected, setConnected] = useState(false)
  const [lastMessage, setLastMessage] = useState(null)
  const wsRef = useRef(null)
  const retryRef = useRef(null)
  const mountedRef = useRef(true)

  const connect = useCallback(() => {
    if (!mountedRef.current) return
    try {
      const ws = new WebSocket(url)
      wsRef.current = ws

      ws.onopen = () => {
        if (!mountedRef.current) return
        setConnected(true)
      }

      ws.onmessage = (evt) => {
        if (!mountedRef.current) return
        try {
          const data = JSON.parse(evt.data)
          if (data.type !== 'ping') setLastMessage(data)
        } catch {}
      }

      ws.onclose = () => {
        if (!mountedRef.current) return
        setConnected(false)
        retryRef.current = setTimeout(connect, 3000)
      }

      ws.onerror = () => { ws.close() }
    } catch {
      retryRef.current = setTimeout(connect, 5000)
    }
  }, [url])

  useEffect(() => {
    mountedRef.current = true
    connect()
    return () => {
      mountedRef.current = false
      clearTimeout(retryRef.current)
      wsRef.current?.close()
    }
  }, [connect])

  return { connected, lastMessage }
}
