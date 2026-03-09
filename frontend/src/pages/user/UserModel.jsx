import { useNavigate } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'
import { api } from '../../lib/api'
import Layout from '../../components/Layout'
import GraphViewer from '../../components/GraphViewer'
import { ArrowLeft, RefreshCw } from 'lucide-react'
import { useState } from 'react'

export default function UserModel() {
  const { session } = useAuth()
  const navigate    = useNavigate()
  const [key, setKey] = useState(0)  // increment to force GraphViewer re-mount

  const iframeSrc = api.userVizUrl(session.userId)

  return (
    <Layout>
      <div className="flex flex-col h-full">
        {/* Topbar */}
        <div className="flex items-center justify-between px-6 py-4 border-b flex-shrink-0"
             style={{ background: '#16213e', borderColor: '#0f3460' }}>
          <button
            onClick={() => navigate('/user/dashboard')}
            className="flex items-center gap-2 text-sm transition-colors"
            style={{ color: '#8892a4' }}
            onMouseEnter={e => e.currentTarget.style.color = '#e0e0e0'}
            onMouseLeave={e => e.currentTarget.style.color = '#8892a4'}>
            <ArrowLeft size={16} /> Back to Dashboard
          </button>

          <h1 className="text-base font-semibold" style={{ color: '#e0e0e0' }}>
            Knowledge Graph — {session.userId}
          </h1>

          <button
            onClick={() => setKey(k => k + 1)}
            className="flex items-center gap-1 text-xs px-3 py-1.5 rounded-lg transition-colors"
            style={{ background: '#0f3460', color: '#8892a4', border: '1px solid #0f3460' }}
            onMouseEnter={e => e.currentTarget.style.color = '#e0e0e0'}
            onMouseLeave={e => e.currentTarget.style.color = '#8892a4'}>
            <RefreshCw size={12} /> Refresh
          </button>
        </div>

        {/* Graph area */}
        <div className="flex-1 p-4">
          <GraphViewer
            key={key}
            generateFn={() => api.generateUserViz(session.userId)}
            iframeSrc={iframeSrc}
            height="100%"
          />
        </div>
      </div>
    </Layout>
  )
}
