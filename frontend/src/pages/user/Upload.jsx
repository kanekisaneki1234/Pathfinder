import { useState, useRef } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'
import { api } from '../../lib/api'
import Layout from '../../components/Layout'
import { Upload as UploadIcon, FileText, CheckCircle, AlertCircle, BookOpen } from 'lucide-react'

function StatCard({ label, value }) {
  return (
    <div className="rounded-xl p-5 text-center" style={{ background: '#0f3460' }}>
      <p className="text-3xl font-bold mb-1" style={{ color: '#e94560' }}>{value}</p>
      <p className="text-xs" style={{ color: '#8892a4' }}>{label}</p>
    </div>
  )
}

export default function Upload() {
  const { session } = useAuth()
  const navigate    = useNavigate()
  const fileRef     = useRef(null)

  const [tab, setTab]         = useState('pdf')   // 'pdf' | 'text'
  const [file, setFile]       = useState(null)
  const [text, setText]       = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult]   = useState(null)
  const [error, setError]     = useState(null)
  const [dragging, setDragging] = useState(false)

  async function handleAnalyse() {
    setError(null)
    setResult(null)
    setLoading(true)
    try {
      let data
      if (tab === 'pdf') {
        if (!file) throw new Error('Please select a PDF file.')
        data = await api.uploadUserPdf(session.userId, file)
      } else {
        if (!text.trim()) throw new Error('Please paste your profile text.')
        data = await api.ingestUser(session.userId, text.trim())
      }
      setResult(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  function onDrop(e) {
    e.preventDefault()
    setDragging(false)
    const f = e.dataTransfer.files[0]
    if (f?.type === 'application/pdf') setFile(f)
    else setError('Only PDF files are accepted.')
  }

  const tabStyle = (t) => ({
    padding: '8px 20px',
    borderRadius: 8,
    fontSize: 13,
    fontWeight: 500,
    cursor: 'pointer',
    background: tab === t ? '#e94560' : 'transparent',
    color: tab === t ? '#fff' : '#8892a4',
    border: 'none',
  })

  return (
    <Layout>
      <div className="max-w-xl mx-auto px-6 py-10">
        <div className="flex items-start justify-between mb-1">
          <h1 className="text-2xl font-bold" style={{ color: '#e0e0e0' }}>Upload Your Resume</h1>
          <Link
            to="/user/guidelines"
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg flex-shrink-0"
            style={{ color: '#8892a4', border: '1px solid #0f3460', background: '#16213e' }}
            onMouseEnter={e => { e.currentTarget.style.color = '#e94560'; e.currentTarget.style.borderColor = '#e94560' }}
            onMouseLeave={e => { e.currentTarget.style.color = '#8892a4'; e.currentTarget.style.borderColor = '#0f3460' }}>
            <BookOpen size={12} /> Resume tips
          </Link>
        </div>
        <p className="text-sm mb-8" style={{ color: '#8892a4' }}>
          We'll extract your skills, domains, and experience to build your knowledge graph.
        </p>

        {/* Tab toggle */}
        <div className="flex gap-1 p-1 rounded-xl mb-6 inline-flex"
             style={{ background: '#16213e', border: '1px solid #0f3460' }}>
          <button style={tabStyle('pdf')}   onClick={() => setTab('pdf')}>Upload PDF</button>
          <button style={tabStyle('text')}  onClick={() => setTab('text')}>Paste Text</button>
        </div>

        {/* PDF drop zone */}
        {tab === 'pdf' && (
          <div
            onClick={() => fileRef.current?.click()}
            onDragOver={e => { e.preventDefault(); setDragging(true) }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            className="rounded-xl p-10 text-center cursor-pointer transition-colors"
            style={{
              border: `2px dashed ${dragging ? '#e94560' : file ? '#27ae60' : '#0f3460'}`,
              background: dragging ? 'rgba(233,69,96,0.05)' : '#16213e',
            }}>
            <input ref={fileRef} type="file" accept=".pdf" className="hidden"
                   onChange={e => setFile(e.target.files[0] || null)} />
            {file ? (
              <>
                <FileText size={40} className="mx-auto mb-3" color="#27ae60" />
                <p className="font-medium text-sm" style={{ color: '#27ae60' }}>{file.name}</p>
                <p className="text-xs mt-1" style={{ color: '#8892a4' }}>
                  {(file.size / 1024).toFixed(0)} KB · Click to change
                </p>
              </>
            ) : (
              <>
                <UploadIcon size={40} className="mx-auto mb-3" color="#0f3460" />
                <p className="font-medium text-sm" style={{ color: '#e0e0e0' }}>
                  Drop your PDF here or click to browse
                </p>
                <p className="text-xs mt-1" style={{ color: '#8892a4' }}>Supports PDF resume files</p>
              </>
            )}
          </div>
        )}

        {/* Text paste */}
        {tab === 'text' && (
          <textarea
            value={text}
            onChange={e => setText(e.target.value)}
            placeholder="Paste your resume or profile text here..."
            rows={12}
            className="w-full px-4 py-3 rounded-xl text-sm outline-none resize-none"
            style={{
              background: '#16213e',
              border: '1px solid #0f3460',
              color: '#e0e0e0',
            }}
            onFocus={e => e.target.style.borderColor = '#e94560'}
            onBlur={e => e.target.style.borderColor = '#0f3460'}
          />
        )}

        {/* Error */}
        {error && (
          <div className="mt-4 flex items-center gap-2 px-4 py-3 rounded-lg"
               style={{ background: 'rgba(231,76,60,0.1)', border: '1px solid rgba(231,76,60,0.3)' }}>
            <AlertCircle size={16} color="#e74c3c" />
            <p className="text-sm" style={{ color: '#e74c3c' }}>{error}</p>
          </div>
        )}

        {/* Analyse button */}
        <button
          onClick={handleAnalyse}
          disabled={loading}
          className="w-full mt-5 py-3 rounded-xl font-semibold text-sm transition-colors disabled:opacity-50"
          style={{ background: '#e94560', color: '#fff' }}
          onMouseEnter={e => !loading && (e.currentTarget.style.background = '#c73652')}
          onMouseLeave={e => e.currentTarget.style.background = '#e94560'}>
          {loading ? 'Analysing…' : 'Analyse Profile'}
        </button>

        {/* Result stats */}
        {result && (
          <div className="mt-8 fade-in">
            <div className="flex items-center gap-2 mb-5">
              <CheckCircle size={18} color="#27ae60" />
              <p className="font-semibold text-sm" style={{ color: '#27ae60' }}>
                Profile successfully processed
              </p>
            </div>
            <div className="grid grid-cols-2 gap-3 mb-6">
              <StatCard label="Skills"      value={result.skills_extracted  || 0} />
              <StatCard label="Domains"     value={result.domains_extracted || 0} />
              <StatCard label="Projects"    value={result.projects_extracted || 0} />
              <StatCard label="Experiences" value={result.experiences_extracted || 0} />
            </div>
            <div className="flex gap-3">
              <button
                onClick={() => navigate('/user/model')}
                className="flex-1 py-3 rounded-xl text-sm font-semibold transition-colors"
                style={{ background: '#0f3460', color: '#e0e0e0', border: '1px solid #0f3460' }}
                onMouseEnter={e => e.currentTarget.style.background = '#1a3a7a'}
                onMouseLeave={e => e.currentTarget.style.background = '#0f3460'}>
                View My Knowledge Graph
              </button>
              <button
                onClick={() => navigate('/user/dashboard')}
                className="flex-1 py-3 rounded-xl text-sm font-semibold transition-colors"
                style={{ background: '#e94560', color: '#fff' }}
                onMouseEnter={e => e.currentTarget.style.background = '#c73652'}
                onMouseLeave={e => e.currentTarget.style.background = '#e94560'}>
                Browse Jobs →
              </button>
            </div>
          </div>
        )}
      </div>
    </Layout>
  )
}
