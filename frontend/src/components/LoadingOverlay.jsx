export default function LoadingOverlay({ message = 'Loading...' }) {
  return (
    <div className="fixed inset-0 z-50 flex flex-col items-center justify-center"
         style={{ background: 'rgba(26,26,46,0.88)', backdropFilter: 'blur(6px)' }}>
      <div className="spinner mb-5" />
      <p className="text-lg font-medium" style={{ color: '#e0e0e0' }}>{message}</p>
    </div>
  )
}
