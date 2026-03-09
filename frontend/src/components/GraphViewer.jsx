import { useState, useEffect } from 'react'

export default function GraphViewer({ generateFn, iframeSrc, height = '100%' }) {
  const [status, setStatus] = useState('generating') // generating | ready | error
  const [error, setError] = useState(null)

  useEffect(() => {
    setStatus('generating')
    setError(null)
    generateFn()
      .then(() => setStatus('ready'))
      .catch((err) => { setStatus('error'); setError(err.message) })
  }, [iframeSrc])

  if (status === 'generating') {
    return (
      <div className="w-full flex flex-col items-center justify-center gap-3"
           style={{ height, background: '#16213e', borderRadius: 8 }}>
        <div className="spinner" />
        <p className="text-sm" style={{ color: '#8892a4' }}>Generating graph…</p>
      </div>
    )
  }

  if (status === 'error') {
    return (
      <div className="w-full flex flex-col items-center justify-center gap-2"
           style={{ height, background: '#16213e', borderRadius: 8 }}>
        <p className="text-sm font-medium" style={{ color: '#e74c3c' }}>Failed to generate graph</p>
        <p className="text-xs" style={{ color: '#8892a4' }}>{error}</p>
      </div>
    )
  }

  return (
    <iframe
      src={iframeSrc}
      style={{ width: '100%', height, border: 'none', borderRadius: 8 }}
      title="Interactive graph"
    />
  )
}
