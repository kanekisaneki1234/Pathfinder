"""
FastAPI route definitions.

All endpoints are prefixed with /api/v1 (applied in main.py).

Endpoints:
  POST /users/ingest                      — extract + write user to Neo4j
  POST /jobs/ingest                       — extract + write job to Neo4j
  GET  /users/{user_id}/matches           — rank ALL jobs for a user (batch)
  GET  /users/{user_id}/matches/{job_id}  — single user-job score detail
  GET  /users/{user_id}/matches/{job_id}/paths — explicit graph paths (scrutability)
  POST /users/{user_id}/visualize         — generate interactive HTML graph
  GET  /users/{user_id}/visualize         — serve the HTML graph in browser
  GET  /users                             — list all users
  GET  /jobs                              — list all jobs
  GET  /health                            — Neo4j connectivity check
"""

import io
import logging
import os

import pypdf
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from database.neo4j_client import Neo4jClient, get_client
from models.schemas import (
    BatchCandidateResponse,
    BatchMatchResponse,
    IngestJobRequest,
    IngestUserRequest,
    MatchResult,
)
from services.ingestion import IngestionService
from services.matching_engine import MatchingEngine
from services.visualization import VisualizationService

logger = logging.getLogger(__name__)
router = APIRouter()


def get_neo4j() -> Neo4jClient:
    return get_client()


# ── Ingestion ──────────────────────────────────────────────────────────────────

@router.post("/users/ingest", tags=["ingestion"], summary="Ingest user profile")
async def ingest_user(
    request: IngestUserRequest,
    db: Neo4jClient = Depends(get_neo4j),
):
    """
    Extract structured entities from raw profile text and write to Neo4j.

    Pipeline:
    1. Groq (llama-3.3-70b) extracts skills, domains, projects, experiences,
       preferences, and problem-solving patterns as structured JSON.
    2. The 4-level hierarchy is written to Neo4j (User → Category → Family → Leaf).
    """
    try:
        service = IngestionService(db)
        result = await service.ingest_user(request.user_id, request.profile_text)
        return {"status": "success", **result}
    except Exception as e:
        logger.exception(f"User ingestion failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/jobs/ingest", tags=["ingestion"], summary="Ingest job posting")
async def ingest_job(
    request: IngestJobRequest,
    db: Neo4jClient = Depends(get_neo4j),
):
    """
    Extract structured requirements from a job posting and write to Neo4j.

    Pipeline:
    1. Groq extracts skill requirements, domain requirements, work styles,
       remote policy, company size, and experience requirements.
    2. The job hierarchy is written to Neo4j.
    """
    try:
        service = IngestionService(db)
        result = await service.ingest_job(request.job_id, request.job_text, request.recruiter_id)
        return {"status": "success", **result}
    except Exception as e:
        logger.exception(f"Job ingestion failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def _extract_pdf_text(file: UploadFile) -> str:
    """Extract plain text from an uploaded PDF file using pypdf."""
    content = await file.read()
    reader = pypdf.PdfReader(io.BytesIO(content))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


@router.post("/users/upload", tags=["ingestion"], summary="Upload PDF resume")
async def upload_user_pdf(
    user_id: str = Form(...),
    file: UploadFile = File(...),
    db: Neo4jClient = Depends(get_neo4j),
):
    """
    Accept a PDF resume, extract text server-side via pypdf, then run the
    standard LLM ingestion pipeline.
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")
    try:
        profile_text = await _extract_pdf_text(file)
        if not profile_text.strip():
            raise HTTPException(status_code=422, detail="Could not extract text from PDF")
        service = IngestionService(db)
        result = await service.ingest_user(user_id, profile_text)
        return {"status": "success", **result}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"PDF user ingestion failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/jobs/upload", tags=["ingestion"], summary="Upload PDF job posting")
async def upload_job_pdf(
    job_id: str = Form(...),
    file: UploadFile = File(...),
    recruiter_id: str = Form(None),
    db: Neo4jClient = Depends(get_neo4j),
):
    """
    Accept a PDF job posting, extract text server-side via pypdf, then run the
    standard LLM ingestion pipeline.
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")
    try:
        job_text = await _extract_pdf_text(file)
        if not job_text.strip():
            raise HTTPException(status_code=422, detail="Could not extract text from PDF")
        service = IngestionService(db)
        result = await service.ingest_job(job_id, job_text, recruiter_id)
        return {"status": "success", **result}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"PDF job ingestion failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Matching ───────────────────────────────────────────────────────────────────

@router.get(
    "/users/{user_id}/matches",
    response_model=BatchMatchResponse,
    tags=["matching"],
    summary="Rank all jobs for a user",
)
async def get_all_matches_for_user(
    user_id: str,
    db: Neo4jClient = Depends(get_neo4j),
):
    """
    Compute match scores for ALL jobs in the database for the given user.

    Returns results ranked by total_score (descending).

    Score breakdown:
      - skill_score      (50%): weighted intersection of user skills ∩ job requirements
      - domain_score     (25%): set intersection of domains
      - culture_score    (15%): work-style preference alignment
      - preference_score (10%): remote policy match

    Every score component is traceable via graph paths at /matches/{job_id}/paths.
    """
    engine = MatchingEngine(db)
    return await engine.rank_all_jobs_for_user(user_id)


@router.get(
    "/users/{user_id}/matches/{job_id}",
    response_model=MatchResult,
    tags=["matching"],
    summary="Get detailed score for one user-job pair",
)
async def get_single_match(
    user_id: str,
    job_id: str,
    db: Neo4jClient = Depends(get_neo4j),
):
    """
    Compute detailed match score between a specific user and job.
    Includes matched/missing skill lists and human-readable explanation.
    """
    engine = MatchingEngine(db)
    result = await engine._score_user_job_pair(user_id, job_id)
    if result is None:
        raise HTTPException(
            status_code=404, detail=f"User '{user_id}' or job '{job_id}' not found"
        )
    return result


@router.get(
    "/jobs/{job_id}/matches",
    response_model=BatchCandidateResponse,
    tags=["matching"],
    summary="Rank all candidates for a job",
)
async def get_all_candidates_for_job(
    job_id: str,
    db: Neo4jClient = Depends(get_neo4j),
):
    """
    Compute match scores for ALL users in the database for the given job.
    Returns results ranked by total_score (descending) — reverse-match for recruiters.
    """
    engine = MatchingEngine(db)
    return await engine.rank_all_users_for_job(job_id)


@router.get(
    "/users/{user_id}/matches/{job_id}/paths",
    tags=["matching"],
    summary="Trace explicit graph paths (scrutability)",
)
async def trace_match_paths(
    user_id: str,
    job_id: str,
    limit: int = 10,
    db: Neo4jClient = Depends(get_neo4j),
):
    """
    Find all explicit graph paths connecting a user to a job.

    Returns path chains like:
      "user1 → HAS_SKILL_CATEGORY → Skills → HAS_SKILL_FAMILY → Python → ..."

    Every match reason is a traceable graph edge, not a black-box score.
    """
    engine = MatchingEngine(db)
    paths = await engine.trace_match_paths(user_id, job_id, limit=limit)
    return {"user_id": user_id, "job_id": job_id, "paths": paths}


# ── Visualization ──────────────────────────────────────────────────────────────

@router.post(
    "/users/{user_id}/recommendations",
    tags=["visualization"],
    summary="Generate job recommendations dashboard",
)
async def generate_recommendations(
    user_id: str,
    limit: int = 10,
    db: Neo4jClient = Depends(get_neo4j),
):
    """
    Generate a styled HTML recommendations page for a user.

    Shows the top-N ranked jobs as cards with score breakdown bars,
    matched skill badges (green), missing skill badges (orange), and
    a "View Match Graph" link per job.
    """
    output_dir = os.getenv("OUTPUT_DIR", "./outputs")
    viz = VisualizationService(db, output_dir)
    try:
        filepath = await viz.generate_recommendations_page(user_id, limit=limit)
        return {
            "user_id": user_id,
            "file": filepath,
            "instructions": (
                "Open the HTML file in a browser, or fetch via "
                f"GET /api/v1/users/{user_id}/recommendations"
            ),
        }
    except Exception as e:
        logger.exception(f"Recommendations generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/users/{user_id}/recommendations",
    tags=["visualization"],
    summary="Serve the recommendations dashboard HTML",
)
async def serve_recommendations(
    user_id: str,
    db: Neo4jClient = Depends(get_neo4j),
):
    """Serve the recommendations HTML page. Generate it first via POST."""
    output_dir = os.getenv("OUTPUT_DIR", "./outputs")
    filepath = os.path.join(output_dir, f"recommendations_{user_id}.html")
    if not os.path.exists(filepath):
        raise HTTPException(
            status_code=404,
            detail=f"Not found. POST /api/v1/users/{user_id}/recommendations first.",
        )
    return FileResponse(filepath, media_type="text/html")


@router.post(
    "/users/{user_id}/matches/{job_id}/visualize",
    tags=["visualization"],
    summary="Generate combined user+job match comparison graph",
)
async def generate_match_visualization(
    user_id: str,
    job_id: str,
    db: Neo4jClient = Depends(get_neo4j),
):
    """
    Generate a combined pyvis graph showing both user and job subgraphs.

    Colour coding:
      Green  — matched skills/domains (user has it, job requires it)
      Orange — gaps (job requires it, user lacks it)
      Green edges — MATCHES connections between matched nodes
    """
    output_dir = os.getenv("OUTPUT_DIR", "./outputs")
    viz = VisualizationService(db, output_dir)
    try:
        filepath = await viz.generate_match_graph(user_id, job_id)
        return {
            "user_id": user_id,
            "job_id": job_id,
            "file": filepath,
            "instructions": (
                "Open the HTML file in a browser, or fetch via "
                f"GET /api/v1/users/{user_id}/matches/{job_id}/visualize"
            ),
        }
    except Exception as e:
        logger.exception(f"Match visualization generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/users/{user_id}/matches/{job_id}/visualize",
    tags=["visualization"],
    summary="Serve the match comparison graph HTML",
)
async def serve_match_visualization(
    user_id: str,
    job_id: str,
    db: Neo4jClient = Depends(get_neo4j),
):
    """Serve the match comparison graph HTML. Generate it first via POST."""
    output_dir = os.getenv("OUTPUT_DIR", "./outputs")
    filepath = os.path.join(
        output_dir, f"graph_match_{user_id}_{job_id}.html"
    )
    if not os.path.exists(filepath):
        raise HTTPException(
            status_code=404,
            detail=(
                f"Not found. POST /api/v1/users/{user_id}/matches/{job_id}/visualize first."
            ),
        )
    return FileResponse(filepath, media_type="text/html")


@router.post(
    "/users/{user_id}/visualize",
    tags=["visualization"],
    summary="Generate interactive graph visualization",
)
async def generate_user_visualization(
    user_id: str,
    db: Neo4jClient = Depends(get_neo4j),
):
    """
    Generate an interactive pyvis HTML graph of the user's knowledge graph.

    The graph shows the full 4-level hierarchy (User → Category → Family → Leaf)
    with nodes colored by type. Open the HTML file in any browser.

    File is saved to OUTPUT_DIR and served via GET /visualize.
    """
    output_dir = os.getenv("OUTPUT_DIR", "./outputs")
    viz = VisualizationService(db, output_dir)
    try:
        filepath = await viz.generate_user_graph(user_id)
        return {
            "user_id": user_id,
            "file": filepath,
            "instructions": (
                "Open the HTML file in a browser, or fetch via "
                f"GET /api/v1/users/{user_id}/visualize"
            ),
        }
    except Exception as e:
        logger.exception(f"Visualization generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/users/{user_id}/visualize",
    tags=["visualization"],
    summary="Serve the graph visualization HTML",
)
async def serve_visualization(
    user_id: str,
    db: Neo4jClient = Depends(get_neo4j),
):
    """
    Serve the interactive pyvis HTML graph directly in the browser.

    If the file doesn't exist yet, call POST /visualize first to generate it.
    """
    output_dir = os.getenv("OUTPUT_DIR", "./outputs")
    filepath = os.path.join(output_dir, f"graph_{user_id}.html")
    if not os.path.exists(filepath):
        raise HTTPException(
            status_code=404,
            detail=f"Graph not found. POST /api/v1/users/{user_id}/visualize first.",
        )
    return FileResponse(filepath, media_type="text/html")


@router.post(
    "/jobs/{job_id}/visualize",
    tags=["visualization"],
    summary="Generate interactive graph visualization for a job",
)
async def generate_job_visualization(
    job_id: str,
    db: Neo4jClient = Depends(get_neo4j),
):
    """
    Generate an interactive pyvis HTML graph of a job's requirement hierarchy.

    Shows the full hierarchy: Job → JobSkillRequirements → JobSkillFamily →
    JobSkillRequirement, JobDomainRequirements, JobCultureRequirements, etc.
    """
    output_dir = os.getenv("OUTPUT_DIR", "./outputs")
    viz = VisualizationService(db, output_dir)
    try:
        filepath = await viz.generate_job_graph(job_id)
        return {
            "job_id": job_id,
            "file": filepath,
            "instructions": (
                "Open the HTML file in a browser, or fetch via "
                f"GET /api/v1/jobs/{job_id}/visualize"
            ),
        }
    except Exception as e:
        logger.exception(f"Job visualization generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/jobs/{job_id}/visualize",
    tags=["visualization"],
    summary="Serve the job graph visualization HTML",
)
async def serve_job_visualization(
    job_id: str,
    db: Neo4jClient = Depends(get_neo4j),
):
    """
    Serve the interactive pyvis HTML graph for a job directly in the browser.

    If the file doesn't exist yet, call POST /jobs/{job_id}/visualize first.
    """
    output_dir = os.getenv("OUTPUT_DIR", "./outputs")
    filepath = os.path.join(output_dir, f"graph_job_{job_id}.html")
    if not os.path.exists(filepath):
        raise HTTPException(
            status_code=404,
            detail=f"Graph not found. POST /api/v1/jobs/{job_id}/visualize first.",
        )
    return FileResponse(filepath, media_type="text/html")


# ── Utility ────────────────────────────────────────────────────────────────────

@router.get("/users", tags=["utility"], summary="List all users")
async def list_users(db: Neo4jClient = Depends(get_neo4j)):
    """Return all user IDs in the database."""
    return await db.run_query(
        "MATCH (u:User) RETURN u.id AS id ORDER BY u.id"
    )


@router.get("/jobs", tags=["utility"], summary="List all jobs")
async def list_jobs(recruiter_id: str | None = None, db: Neo4jClient = Depends(get_neo4j)):
    """Return job IDs, titles, and companies. Pass recruiter_id to filter to that recruiter's jobs only."""
    if recruiter_id:
        return await db.run_query(
            """
            MATCH (j:Job)
            WHERE j.recruiter_id = $recruiter_id
            RETURN j.id AS id, j.title AS title, j.company AS company,
                   j.remote_policy AS remote_policy
            ORDER BY j.title
            """,
            {"recruiter_id": recruiter_id},
        )
    return await db.run_query(
        """
        MATCH (j:Job)
        RETURN j.id AS id, j.title AS title, j.company AS company,
               j.remote_policy AS remote_policy
        ORDER BY j.title
        """
    )


@router.get("/users/{user_id}/graph-stats", tags=["utility"])
async def get_user_graph_stats(
    user_id: str, db: Neo4jClient = Depends(get_neo4j)
):
    """Return node counts at each hierarchy level for a user's graph."""
    stats = await db.count_nodes_for_user(user_id)
    if stats["categories"] == 0:
        raise HTTPException(status_code=404, detail=f"User '{user_id}' not found")
    return {"user_id": user_id, **stats}


# ── Admin ──────────────────────────────────────────────────────────────────────

@router.delete("/users/{user_id}", tags=["admin"], summary="Delete a user and all their data")
async def delete_user(user_id: str, db: Neo4jClient = Depends(get_neo4j)):
    """Cascade-delete the User node and every node owned by this user (skills,
    domains, projects, experiences, preferences, patterns) plus all MATCHES edges.
    Also removes any cached visualization HTML files."""
    await db.run_write(
        """
        MATCH (n)
        WHERE (n:User AND n.id = $user_id) OR n.user_id = $user_id
        DETACH DELETE n
        """,
        {"user_id": user_id},
    )
    import glob
    for f in (
        glob.glob(f"./outputs/graph_{user_id}.html")
        + glob.glob(f"./outputs/graph_match_{user_id}_*.html")
        + glob.glob(f"./outputs/recommendations_{user_id}.html")
    ):
        try:
            os.remove(f)
        except OSError:
            pass
    return {"status": "deleted", "user_id": user_id}


@router.delete("/jobs/{job_id}", tags=["admin"], summary="Delete a job and all its data")
async def delete_job(job_id: str, db: Neo4jClient = Depends(get_neo4j)):
    """Cascade-delete the Job node and every node owned by this job (skill/domain
    requirements, work styles) plus all MATCHES edges pointing to those nodes.
    Also removes any cached visualization HTML files."""
    await db.run_write(
        """
        MATCH (n)
        WHERE (n:Job AND n.id = $job_id) OR n.job_id = $job_id
        DETACH DELETE n
        """,
        {"job_id": job_id},
    )
    import glob
    for f in (
        glob.glob(f"./outputs/graph_job_{job_id}.html")
        + glob.glob(f"./outputs/graph_match_*_{job_id}.html")
    ):
        try:
            os.remove(f)
        except OSError:
            pass
    return {"status": "deleted", "job_id": job_id}


@router.get("/health", tags=["utility"], summary="Health check")
async def health_check(db: Neo4jClient = Depends(get_neo4j)):
    """Verify Neo4j connectivity. Returns 503 if database is unreachable."""
    try:
        await db.verify_connectivity()
        return {"status": "healthy", "neo4j": "connected"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Neo4j unreachable: {e}")
