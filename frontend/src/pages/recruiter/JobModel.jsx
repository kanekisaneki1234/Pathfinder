import { useParams, useNavigate } from 'react-router-dom'
import { api } from '../../lib/api'
import Layout from '../../components/Layout'
import GraphViewer from '../../components/GraphViewer'
import { ArrowLeft, RefreshCw, Users } from 'lucide-react'
import { useState } from 'react'

export default function JobModel() {
  const { jobId } = useParams()
  const navigate  = useNavigate()
  const [key, setKey] = useState(0)

  const iframeSrc = api.jobVizUrl(jobId)

  return (
    <Layout>
      <div className="flex flex-col h-full">
        {/* Topbar */}
        <div className="flex items-center justify-between px-6 py-4 border-b flex-shrink-0"
             style={{ background: '#16213e', borderColor: '#0f3460' }}>
          <button
            onClick={() => navigate('/recruiter/post')}
            className="flex items-center gap-2 text-sm"
            style={{ color: '#8892a4' }}
            onMouseEnter={e => e.currentTarget.style.color = '#e0e0e0'}
            onMouseLeave={e => e.currentTarget.style.color = '#8892a4'}>
            <ArrowLeft size={16} /> Back
          </button>

          <h1 className="text-base font-semibold" style={{ color: '#e0e0e0' }}>
            Job Model — {jobId}
          </h1>

          <div className="flex gap-2">
            <button
              onClick={() => navigate(`/recruiter/candidates/${jobId}`)}
              className="flex items-center gap-1 text-xs px-3 py-1.5 rounded-lg"
              style={{ background: '#e94560', color: '#fff' }}
              onMouseEnter={e => e.currentTarget.style.background = '#c73652'}
              onMouseLeave={e => e.currentTarget.style.background = '#e94560'}>
              <Users size={12} /> Find Candidates
            </button>
            <button
              onClick={() => setKey(k => k + 1)}
              className="flex items-center gap-1 text-xs px-3 py-1.5 rounded-lg"
              style={{ background: '#0f3460', color: '#8892a4', border: '1px solid #0f3460' }}
              onMouseEnter={e => e.currentTarget.style.color = '#e0e0e0'}
              onMouseLeave={e => e.currentTarget.style.color = '#8892a4'}>
              <RefreshCw size={12} /> Refresh
            </button>
          </div>
        </div>

        {/* Graph area */}
        <div className="flex-1 p-4">
          <GraphViewer
            key={key}
            generateFn={() => api.generateJobViz(jobId)}
            iframeSrc={iframeSrc}
            height="100%"
          />
        </div>
      </div>
    </Layout>
  )
}
