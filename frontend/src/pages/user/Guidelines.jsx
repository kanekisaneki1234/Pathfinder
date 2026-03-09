import { Link } from 'react-router-dom'
import Layout from '../../components/Layout'
import {
  BookOpen, CheckCircle, XCircle, Layers, Briefcase, FolderOpen,
  Globe, Heart, FileText, ArrowLeft,
} from 'lucide-react'

function SectionCard({ icon: Icon, title, color, children }) {
  return (
    <div className="rounded-xl p-5" style={{ background: '#16213e', border: '1px solid #0f3460' }}>
      <div className="flex items-center gap-3 mb-4">
        <div className="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0"
             style={{ background: `${color}18`, border: `1px solid ${color}40` }}>
          <Icon size={17} color={color} />
        </div>
        <h2 className="font-semibold text-sm" style={{ color: '#e0e0e0' }}>{title}</h2>
      </div>
      {children}
    </div>
  )
}

function Tip({ text }) {
  return (
    <li className="flex items-start gap-2 text-sm" style={{ color: '#c0c8d8' }}>
      <CheckCircle size={14} color="#27ae60" className="flex-shrink-0 mt-0.5" />
      {text}
    </li>
  )
}

function Avoid({ text }) {
  return (
    <li className="flex items-start gap-2 text-sm" style={{ color: '#c0c8d8' }}>
      <XCircle size={14} color="#e74c3c" className="flex-shrink-0 mt-0.5" />
      {text}
    </li>
  )
}

function Example({ label, good, bad }) {
  return (
    <div className="mt-3 space-y-1.5">
      <p className="text-xs font-medium" style={{ color: '#8892a4' }}>{label}</p>
      <div className="flex gap-2">
        <div className="flex-1 px-3 py-2 rounded-lg text-xs"
             style={{ background: 'rgba(39,174,96,0.07)', border: '1px solid rgba(39,174,96,0.2)', color: '#27ae60' }}>
          ✓ {good}
        </div>
        <div className="flex-1 px-3 py-2 rounded-lg text-xs"
             style={{ background: 'rgba(231,76,60,0.07)', border: '1px solid rgba(231,76,60,0.2)', color: '#e74c3c' }}>
          ✗ {bad}
        </div>
      </div>
    </div>
  )
}

export default function Guidelines() {
  return (
    <Layout>
      <div className="max-w-3xl mx-auto px-6 py-8">

        {/* Header */}
        <div className="flex items-center gap-3 mb-2">
          <Link
            to="/user/upload"
            className="flex items-center gap-1.5 text-sm"
            style={{ color: '#8892a4' }}
            onMouseEnter={e => e.currentTarget.style.color = '#e0e0e0'}
            onMouseLeave={e => e.currentTarget.style.color = '#8892a4'}>
            <ArrowLeft size={14} /> Upload
          </Link>
        </div>
        <div className="flex items-center gap-3 mb-2">
          <div className="w-10 h-10 rounded-xl flex items-center justify-center"
               style={{ background: 'rgba(233,69,96,0.12)', border: '1px solid rgba(233,69,96,0.25)' }}>
            <BookOpen size={18} color="#e94560" />
          </div>
          <div>
            <h1 className="text-2xl font-bold" style={{ color: '#e0e0e0' }}>Resume Guide</h1>
            <p className="text-sm" style={{ color: '#8892a4' }}>
              Format your resume to get the most accurate graph model
            </p>
          </div>
        </div>

        {/* How it works callout */}
        <div className="mt-6 mb-8 px-4 py-3 rounded-xl flex items-start gap-3"
             style={{ background: 'rgba(93,173,226,0.07)', border: '1px solid rgba(93,173,226,0.2)' }}>
          <FileText size={15} color="#5dade2" className="flex-shrink-0 mt-0.5" />
          <p className="text-sm" style={{ color: '#a0bcd8' }}>
            The system extracts <strong style={{ color: '#5dade2' }}>skills</strong>,{' '}
            <strong style={{ color: '#5dade2' }}>domains</strong>,{' '}
            <strong style={{ color: '#5dade2' }}>experiences</strong>,{' '}
            <strong style={{ color: '#5dade2' }}>projects</strong>, and{' '}
            <strong style={{ color: '#5dade2' }}>work style preferences</strong> from your resume using an LLM.
            The clearer these sections are in your resume, the richer the graph — and the better the job matches.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-5">

          {/* Format */}
          <SectionCard icon={FileText} title="File Format" color="#5dade2">
            <ul className="space-y-2">
              <Tip text="Use a PDF with a real text layer (not a scanned image)" />
              <Tip text="Keep it 1–2 pages for best extraction quality" />
              <Tip text="Use a clean, single-column layout where possible" />
              <Avoid text="Scanned / photographed resumes (text is not extractable)" />
              <Avoid text="Heavy graphics, skill bars, or icons replacing text" />
              <Avoid text="Tables with merged cells that break the reading order" />
            </ul>
          </SectionCard>

          {/* Skills */}
          <SectionCard icon={Layers} title="Skills Section" color="#e94560">
            <ul className="space-y-2">
              <Tip text="List skills individually, separated by commas or bullets" />
              <Tip text="Group by category: Languages, Frameworks, Tools, Cloud" />
              <Tip text="Use standard names: 'PyTorch' not 'deep learning library'" />
              <Avoid text="Embedding skills only inside job description sentences" />
              <Avoid text="Using skill-bar graphics instead of text" />
            </ul>
            <Example
              label="Skills line"
              good="Python, FastAPI, PostgreSQL, Docker, AWS"
              bad="Proficient in several backend technologies"
            />
          </SectionCard>

          {/* Experience */}
          <SectionCard icon={Briefcase} title="Work Experience" color="#e67e22">
            <ul className="space-y-2">
              <Tip text="Include company name, job title, and dates" />
              <Tip text="Use bullet points that mention specific technologies" />
              <Tip text="State what you built / owned, not just responsibilities" />
              <Avoid text="Omitting the company name (breaks experience hierarchy)" />
              <Avoid text="Paragraph blocks without mentioning any tech stack" />
            </ul>
            <Example
              label="Experience bullet"
              good="Built real-time pipeline using Kafka + Flink (Java) processing 1M events/day"
              bad="Worked on data infrastructure and improved system performance"
            />
          </SectionCard>

          {/* Projects */}
          <SectionCard icon={FolderOpen} title="Projects" color="#9b59b6">
            <ul className="space-y-2">
              <Tip text="Name the project clearly" />
              <Tip text="List the tech stack used (language, frameworks, services)" />
              <Tip text="One-line description of what it does" />
              <Avoid text="Vague entries like 'personal project — various technologies'" />
            </ul>
            <Example
              label="Project entry"
              good="JobGraph (React, FastAPI, Neo4j) — graph-based job matching engine"
              bad="Full-stack web application"
            />
          </SectionCard>

          {/* Domains */}
          <SectionCard icon={Globe} title="Domain Keywords" color="#27ae60">
            <ul className="space-y-2">
              <Tip text="Use domain-specific terms in section headers or summaries" />
              <Tip text="Examples: 'machine learning', 'data engineering', 'fintech', 'devops'" />
              <Tip text="Mention industry context (e.g. 'healthcare AI', 'e-commerce platform')" />
              <Avoid text="Generic buzzwords with no domain signal ('results-driven professional')" />
            </ul>
            <Example
              label="Summary line"
              good="Backend engineer specialising in distributed systems and data engineering"
              bad="Experienced engineer looking for challenging opportunities"
            />
          </SectionCard>

          {/* Work Style */}
          <SectionCard icon={Heart} title="Work Style Preferences" color="#e94560">
            <ul className="space-y-2">
              <Tip text="Mention your preferred work environment in a summary or profile section" />
              <Tip text="Use recognisable phrases: 'remote-first', 'startup culture', 'high-autonomy', 'collaborative'" />
              <Tip text="These feed the culture matching score against job requirements" />
              <Avoid text="Leaving this section out entirely — culture score will be zero" />
            </ul>
            <div className="mt-3 px-3 py-2 rounded-lg text-xs"
                 style={{ background: 'rgba(233,69,96,0.07)', border: '1px solid rgba(233,69,96,0.2)', color: '#c0c8d8' }}>
              Recognised terms include: <span style={{ color: '#e94560' }}>remote, hybrid, onsite, startup, fast-paced, high-autonomy, collaborative, data-driven, agile, async, design-focused</span>
            </div>
          </SectionCard>

        </div>

        {/* Bottom CTA */}
        <div className="mt-8 flex items-center justify-between px-5 py-4 rounded-xl"
             style={{ background: '#16213e', border: '1px solid #0f3460' }}>
          <p className="text-sm" style={{ color: '#8892a4' }}>
            Ready to upload your resume?
          </p>
          <Link
            to="/user/upload"
            className="px-4 py-2 rounded-lg text-sm font-semibold"
            style={{ background: '#e94560', color: '#fff' }}
            onMouseEnter={e => e.currentTarget.style.background = '#c73652'}
            onMouseLeave={e => e.currentTarget.style.background = '#e94560'}>
            Upload Resume →
          </Link>
        </div>

      </div>
    </Layout>
  )
}
