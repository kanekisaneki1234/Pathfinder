"""
LLM ingestion orchestrator.

Two-phase pipeline for both users and jobs:
  Phase 1: Groq extraction → structured JSON (skills, domains, projects, etc.)
  Phase 2: Write hierarchy → Neo4j (source='llm')
"""

import logging
from database.neo4j_client import Neo4jClient
from services.llm_extraction import LLMExtractionService
from services.llm_ingestion import LLMIngestionService

logger = logging.getLogger(__name__)


class IngestionService:
    def __init__(self, neo4j_client: Neo4jClient):
        self._client = neo4j_client
        self._llm_extractor = LLMExtractionService()
        self._llm_ingester = LLMIngestionService(neo4j_client)

    async def ingest_user(self, user_id: str, profile_text: str) -> dict:
        """
        Ingest a user profile via LLM extraction + Neo4j write.
        Returns ingestion stats for the API response.
        """
        logger.info(f"Ingesting user: {user_id}")

        extraction = await self._llm_extractor.extract_user_profile(profile_text)
        await self._llm_ingester.ingest_user_profile(user_id, extraction)
        skill_links = await self._llm_ingester.link_skill_matches(user_id)
        domain_links = await self._llm_ingester.link_domain_matches(user_id)

        result = {
            "user_id": user_id,
            "entity_type": "user",
            "skills_extracted": len(extraction.skills),
            "domains_extracted": len(extraction.domains),
            "projects_extracted": len(extraction.projects),
            "experiences_extracted": len(extraction.experiences),
            "skill_matches_linked": skill_links,
            "domain_matches_linked": domain_links,
        }
        logger.info(f"User ingestion complete: {result}")
        return result

    async def ingest_job(self, job_id: str, job_text: str, recruiter_id: str | None = None) -> dict:
        """
        Ingest a job posting via LLM extraction + Neo4j write.
        Returns ingestion stats for the API response.
        """
        logger.info(f"Ingesting job: {job_id}")

        extraction = await self._llm_extractor.extract_job_posting(job_text)
        await self._llm_ingester.ingest_job_posting(job_id, extraction, recruiter_id)
        skill_links = await self._llm_ingester.link_job_skill_matches(job_id)
        domain_links = await self._llm_ingester.link_job_domain_matches(job_id)

        result = {
            "job_id": job_id,
            "entity_type": "job",
            "title": extraction.title,
            "company": extraction.company,
            "skill_requirements_extracted": len(extraction.skill_requirements),
            "domain_requirements_extracted": len(extraction.domain_requirements),
            "work_styles_extracted": len(extraction.work_styles),
            "skill_matches_linked": skill_links,
            "domain_matches_linked": domain_links,
        }
        logger.info(f"Job ingestion complete: {result}")
        return result
