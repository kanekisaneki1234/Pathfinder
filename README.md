# Adaptive Job Matching System

A transparent, graph-based job matching platform where every match decision is fully explainable. Unlike black-box vector similarity or opaque ML models, every match score traces back to explicit paths in a Neo4j knowledge graph — no magic numbers.

---

## How It Works

**For Job Seekers**
1. Upload a resume (PDF or paste text)
2. Groq (LLaMA 3.3 70B) extracts skills, domains, projects, experiences, and work preferences as structured JSON
3. The extracted entities are written into a personal knowledge graph in Neo4j (4-level hierarchy: User → Category → Family → Leaf)
4. Browse all job listings ranked by match score, with full breakdowns of what matched and what didn't
5. Click any job to see the combined match graph visualized interactively

**For Recruiters**
1. Post a job (PDF or paste text) — LLM extracts skill requirements, domain requirements, work styles, and company culture
2. Browse "Find Candidates" to see all job seekers ranked against your specific job
3. Explore the combined graph view for any candidate to see exactly why they matched

**Matching Engine**
- **Skills (65%)** — weighted intersection via `MATCHES` edges in the graph; importance-weighted (`must_have=1.0`, `nice_to_have=0.5`); seniority factor applied when years of experience is specified
- **Domain (35%)** — set intersection of domain expertise vs. job domain requirements
- **Culture bonus** — ratio of job work styles that match user preferences (displayed separately, not in total score)
- **Preference bonus** — remote policy + company size preference satisfaction (displayed separately)
- Every score is traceable through explicit graph paths — "User → HAS\_SKILL → Python → MATCHES → JobSkillRequirement"

---

## Tech Stack

| Layer | Technology |
|---|---|
| **LLM** | Groq API — LLaMA 3.3 70B Versatile |
| **Graph DB** | Neo4j 5.15 Community (Docker) + APOC plugin |
| **Backend** | FastAPI + Uvicorn (Python 3.13) |
| **Graph viz** | pyvis + NetworkX (self-contained inline HTML) |
| **Frontend** | React 18 + Vite 5 + TailwindCSS + React Router v6 |
| **Icons** | lucide-react |
| **PDF parsing** | pypdf |
| **Data modeling** | Pydantic v2 |

---

## Project Structure

```
Adaptive_Protoype_2.0/
├── main.py                        # FastAPI app entry point + lifespan
├── docker-compose.yml             # Neo4j 5.15 + APOC
├── requirements.txt
│
├── api/
│   └── routes.py                  # All API endpoints (/api/v1/*)
│
├── database/
│   └── neo4j_client.py            # Async Neo4j driver singleton + helpers
│
├── models/
│   ├── schemas.py                 # Pydantic request/response + LLM extraction models
│   └── taxonomies.py              # Skill/domain taxonomies, match weights, work-style synonyms
│
├── services/
│   ├── llm_extraction.py          # Groq structured JSON extraction
│   ├── llm_ingestion.py           # Writes LLM hierarchy → Neo4j
│   ├── ingestion.py               # Orchestrates extraction + ingestion pipeline
│   ├── matching_engine.py         # Pure Cypher-based scoring + path tracing
│   └── visualization.py           # pyvis graph generators (user / job / match)
│
├── outputs/                       # Generated pyvis HTML graphs (gitignored)
│
└── frontend/
    ├── src/
    │   ├── pages/
    │   │   ├── Login.jsx
    │   │   ├── user/              # Job Seeker views
    │   │   │   ├── Upload.jsx     # Resume upload (PDF + text)
    │   │   │   ├── Guidelines.jsx # Resume formatting tips
    │   │   │   ├── UserModel.jsx  # Personal knowledge graph viewer
    │   │   │   ├── Dashboard.jsx  # Job listings + match scores
    │   │   │   └── MatchExplorer.jsx # Combined match graph + score breakdown
    │   │   ├── recruiter/         # Recruiter views
    │   │   │   ├── PostJob.jsx    # Job posting (PDF + text)
    │   │   │   ├── JobModel.jsx   # Job knowledge graph viewer
    │   │   │   ├── CandidatesBrowser.jsx # Job picker → candidates
    │   │   │   └── Candidates.jsx # Ranked candidates for a job
    │   │   └── admin/
    │   │       └── AdminDashboard.jsx
    │   ├── components/
    │   │   ├── Layout.jsx         # Sidebar nav + session header
    │   │   ├── GraphViewer.jsx    # iframe wrapper for pyvis HTML
    │   │   ├── ScoreBar.jsx
    │   │   ├── SkillBadge.jsx
    │   │   └── ProtectedRoute.jsx
    │   ├── context/AuthContext.jsx # Session stored in localStorage
    │   └── lib/api.js             # Typed API client (fetch wrapper)
    └── package.json
```

---

## Getting Started

### Prerequisites

- Python 3.11+
- Node.js 18+
- Docker + Docker Compose
- A [Groq API key](https://console.groq.com)

### 1. Clone and configure

```bash
git clone <repo-url>
cd Adaptive_Protoype_2.0

cp .env.example .env
# Edit .env and fill in:
#   GROQ_API_KEY=your_key_here
#   NEO4J_PASSWORD=your_password
```

### 2. Start Neo4j

```bash
docker compose down && docker compose up -d
# Wait ~15s for Neo4j to initialise
```

### 3. Start the backend

```bash
python -m venv adaptive_job_rec
source adaptive_job_rec/bin/activate   # Windows: adaptive_job_rec\Scripts\activate
pip install -r requirements.txt

python main.py
# API available at http://localhost:8000
# Swagger docs at http://localhost:8000/docs
```

### 4. Start the frontend

```bash
cd frontend
npm install
npm run dev
# App available at http://localhost:5173
```

---

## Environment Variables

Create a `.env` file in the project root:

```env
# Neo4j
NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your_password_here

# Groq
GROQ_API_KEY=your_groq_api_key_here

# Optional
OUTPUT_DIR=./outputs
APP_HOST=0.0.0.0
APP_PORT=8000
```

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/users/ingest` | Ingest user profile from text |
| `POST` | `/api/v1/users/upload` | Ingest user profile from PDF |
| `POST` | `/api/v1/jobs/ingest` | Ingest job posting from text |
| `POST` | `/api/v1/jobs/upload` | Ingest job posting from PDF |
| `GET` | `/api/v1/users/{id}/matches` | Rank all jobs for a user |
| `GET` | `/api/v1/users/{id}/matches/{job_id}` | Detailed score for one pair |
| `GET` | `/api/v1/users/{id}/matches/{job_id}/paths` | Explicit graph paths (scrutability) |
| `GET` | `/api/v1/jobs/{job_id}/matches` | Rank all candidates for a job |
| `POST` | `/api/v1/users/{id}/visualize` | Generate user knowledge graph |
| `POST` | `/api/v1/jobs/{job_id}/visualize` | Generate job requirement graph |
| `POST` | `/api/v1/users/{id}/matches/{job_id}/visualize` | Generate combined match graph |
| `GET` | `/api/v1/jobs` | List all jobs (filter by `?recruiter_id=`) |
| `GET` | `/api/v1/users` | List all users |
| `DELETE` | `/api/v1/users/{id}` | Delete user and all their data |
| `DELETE` | `/api/v1/jobs/{job_id}` | Delete job and all its data |
| `GET` | `/api/v1/health` | Neo4j connectivity check |

Full interactive docs available at `http://localhost:8000/docs`.

---

## Graph Schema

```
User
 └─HAS_SKILL_CATEGORY─► SkillCategory
      └─HAS_SKILL_FAMILY─► SkillFamily
           └─HAS_SKILL─► Skill ──MATCHES──► JobSkillRequirement

User
 └─HAS_DOMAIN_CATEGORY─► DomainCategory
      └─HAS_DOMAIN_FAMILY─► DomainFamily
           └─HAS_DOMAIN─► Domain ──MATCHES──► JobDomainRequirement

User └─HAS_PREFERENCE_CATEGORY─► PreferenceCategory └─HAS_PREFERENCE─► Preference
User └─HAS_PROJECT_CATEGORY─► ProjectCategory └─HAS_PROJECT─► Project
User └─HAS_EXPERIENCE_CATEGORY─► ExperienceCategory └─HAS_EXPERIENCE─► Experience

Job
 └─HAS_SKILL_REQUIREMENTS─► JobSkillRequirements
      └─HAS_SKILL_FAMILY_REQ─► JobSkillFamily
           └─REQUIRES_SKILL─► JobSkillRequirement

Job └─HAS_DOMAIN_REQUIREMENTS─► JobDomainRequirements └─... ─► JobDomainRequirement
Job └─HAS_CULTURE_REQUIREMENTS─► JobCultureRequirements └─HAS_WORK_STYLE─► WorkStyle
```

---

## Key Design Decisions

**No vectors, no black boxes.** Matching is 100% graph traversal. `MATCHES` edges connect user skill/domain nodes directly to job requirement nodes. Every score component is a Cypher query result, not an embedding similarity.

**Recruiter scoping.** Each job is tagged with the `recruiter_id` of who posted it. Recruiters only see their own job listings in the candidate browser.

**Self-contained visualizations.** pyvis graphs use `cdn_resources="in_line"` — the entire vis.js bundle is embedded in each HTML file, making them fully portable with no external dependencies.

**LLM as structured extractor only.** Groq LLaMA 3.3 70B is used exclusively for extracting structured entities (skills, domains, work styles) from free-text resumes and job postings. All matching logic is deterministic Cypher, not LLM-driven.

---

## Roles

| Role | Access |
|------|--------|
| **Job Seeker** | Upload resume, view knowledge graph, browse & explore job matches |
| **Recruiter** | Post jobs, browse & rank candidates, explore match graphs |
| **Admin** | Manage users and jobs (delete, inspect) |

> Authentication is session-based (localStorage) for demo purposes. No passwords — enter any ID and select a role.
