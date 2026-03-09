"""
Adaptive Prototype 2.0 — Transparent Job Matching System

FastAPI application entry point.

Startup sequence:
  1. Load .env
  2. Init Neo4j driver + create constraints
  3. Register API routes

Access points after startup:
  - API:           http://localhost:8000/api/v1/
  - Swagger docs:  http://localhost:8000/docs
  - Neo4j Browser: http://localhost:7474
"""

import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Load .env before any imports that read env vars
load_dotenv()

from api.routes import router
from database.neo4j_client import init_client, get_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("━━ Starting Adaptive Job Matching System ━━")

    neo4j_uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    neo4j_user = os.environ.get("NEO4J_USERNAME", "neo4j")
    neo4j_pass = os.environ.get("NEO4J_PASSWORD", "")

    if not neo4j_pass:
        logger.warning("NEO4J_PASSWORD is not set — connection may fail")

    client = await init_client(neo4j_uri, neo4j_user, neo4j_pass)
    logger.info(f"Neo4j connected: {neo4j_uri}")

    output_dir = os.environ.get("OUTPUT_DIR", "./outputs")
    os.makedirs(output_dir, exist_ok=True)
    logger.info(f"Visualization output dir: {output_dir}")

    logger.info("━━ System ready — visit http://localhost:8000/docs ━━")

    yield

    logger.info("Shutting down...")
    await client.close()
    logger.info("Goodbye.")


app = FastAPI(
    title="Adaptive Job Matching System",
    description=(
        "A transparent, graph-based job matching system. "
        "Every match decision is traceable through explicit Neo4j graph paths. "
        "Powered by Groq (extraction) + Neo4j (graph matching)."
    ),
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")


@app.get("/", include_in_schema=False)
async def root():
    return {
        "name": "Adaptive Job Matching System",
        "version": "2.0.0",
        "docs": "/docs",
        "api": "/api/v1",
        "health": "/api/v1/health",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=os.environ.get("APP_HOST", "0.0.0.0"),
        port=int(os.environ.get("APP_PORT", "8000")),
        reload=True,
        log_level="info",
    )
