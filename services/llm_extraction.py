"""
Groq-based structured extraction service.

Uses the Groq Python SDK (AsyncGroq) with JSON mode to enforce structured output.
Groq does not accept a Pydantic response_schema directly, so the full Pydantic
JSON schema is embedded in the system prompt and response_format={"type":
"json_object"} is used to guarantee the response is valid JSON.

Model choice: llama-3.3-70b-versatile
  - Best instruction following on Groq for complex structured extraction
  - 128k context window handles long resumes
  - Near-instant inference on Groq hardware despite being 70B
"""

import asyncio
import json
import logging
import os

from groq import AsyncGroq

from models.schemas import UserProfileExtraction, JobPostingExtraction
from models.taxonomies import SKILL_TAXONOMY, DOMAIN_TAXONOMY

logger = logging.getLogger(__name__)

# Pre-compute JSON schemas once at module load — included in every system prompt
# so the model knows exactly what structure to return.
_USER_SCHEMA = json.dumps(UserProfileExtraction.model_json_schema(), indent=2)
_JOB_SCHEMA = json.dumps(JobPostingExtraction.model_json_schema(), indent=2)


def _build_skill_taxonomy_hint() -> str:
    return "\n".join(
        f"  - {family}: {', '.join(skills[:6])}..."
        for family, skills in SKILL_TAXONOMY.items()
    )


def _build_domain_taxonomy_hint() -> str:
    return "\n".join(
        f"  - {family}: {', '.join(domains[:4])}..."
        for family, domains in DOMAIN_TAXONOMY.items()
    )


class LLMExtractionService:
    """
    Wraps Groq API for structured JSON extraction.

    Uses AsyncGroq with response_format={"type": "json_object"} and a
    system prompt that includes the full Pydantic JSON schema. The response
    is parsed with model_validate_json() for strict Pydantic validation.

    The schema is passed in the system message so the model treats it as a
    hard constraint rather than a soft suggestion.
    """

    def __init__(self):
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY environment variable not set")

        self._model_name = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
        self._client = AsyncGroq(api_key=api_key)
        self._skill_hint = _build_skill_taxonomy_hint()
        self._domain_hint = _build_domain_taxonomy_hint()
        logger.info(f"LLM extraction service initialized with model: {self._model_name}")

    async def _call_with_retry(self, **kwargs) -> str:
        """Call Groq API with exponential backoff (3 attempts: immediate, 1s, 2s)."""
        for attempt in range(3):
            try:
                resp = await self._client.chat.completions.create(**kwargs)
                return resp.choices[0].message.content
            except Exception as e:
                if attempt == 2:
                    raise
                wait = 2 ** attempt
                logger.warning(f"Groq API error (attempt {attempt + 1}/3): {e}. Retrying in {wait}s")
                await asyncio.sleep(wait)

    async def extract_user_profile(self, profile_text: str) -> UserProfileExtraction:
        """
        Extract structured user profile from raw resume/profile text.

        Returns a validated UserProfileExtraction with skills, projects,
        domains, experiences, preferences, and problem-solving patterns.
        """
        system_msg = (
            "You are an expert HR data extractor. Extract structured professional "
            "information and return ONLY valid JSON matching this exact schema:\n\n"
            f"{_USER_SCHEMA}\n\n"
            "Constraints:\n"
            "- skill.family must be one of: Programming Languages, Web Frameworks, "
            "Databases, Cloud & DevOps, ML & AI, Data Engineering, Mobile Development, "
            "Testing & QA, Analytics & Visualization, Other\n"
            "- domain.family must be one of: FinTech, Healthcare, E-commerce, SaaS, "
            "Enterprise, Gaming, Education, Other\n"
            "- Return an empty list [] for any section with no data — never omit keys."
        )

        user_msg = (
            "Extract all professional information from the following profile.\n\n"
            "Skill family reference:\n"
            f"{self._skill_hint}\n\n"
            "Domain family reference:\n"
            f"{self._domain_hint}\n\n"
            f"PROFILE TEXT:\n{profile_text}"
        )

        raw_json = await self._call_with_retry(
            model=self._model_name,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
        )
        extracted = UserProfileExtraction.model_validate_json(raw_json)
        logger.info(
            f"Extracted: {len(extracted.skills)} skills, "
            f"{len(extracted.projects)} projects, "
            f"{len(extracted.domains)} domains"
        )
        return extracted

    async def generate_match_explanation(
        self,
        user_id: str,
        job_title: str,
        company: str | None,
        total_score: float,
        skill_score: float,
        domain_score: float,
        culture_bonus: float,
        preference_bonus: float,
        matched_skills: list[str],
        missing_skills: list[str],
        matched_domains: list[str],
        missing_domains: list[str],
        paths: list[str],
    ) -> str:
        """
        Generate a natural-language explanation of a user-job match.

        Passes all structured match data (scores, matched/missing lists, graph paths)
        to the LLM and returns a concise 2–3 sentence plain-English summary written
        for a recruiter. Uses free-text mode (no JSON) at temperature 0.4.
        """
        company_str = company or "Unknown Company"
        matched_skills_str = ", ".join(matched_skills) if matched_skills else "None"
        missing_skills_str = ", ".join(missing_skills) if missing_skills else "None"
        matched_domains_str = ", ".join(matched_domains) if matched_domains else "None"
        missing_domains_str = ", ".join(missing_domains) if missing_domains else "None"
        paths_str = "\n".join(f"- {p}" for p in paths[:10]) if paths else "(no direct graph paths found)"

        system_msg = (
            "You are a career advisor writing match summaries for a knowledge-graph-based job matching platform. "
            "Write concise, plain-English summaries. Be specific — always name actual skills and domains "
            "from the data provided. Never invent data not given to you. Do not use bullet points."
        )

        user_msg = (
            f"Candidate: {user_id}\n"
            f"Job: {job_title} at {company_str}\n"
            f"Overall Match Score: {round(total_score * 100)}% "
            f"(Skills 65% weight: {round(skill_score * 100)}%, Domain 35% weight: {round(domain_score * 100)}%)\n"
            f"Culture Fit Bonus: {round(culture_bonus * 100)}%\n"
            f"Preference Fit Bonus: {round(preference_bonus * 100)}%\n\n"
            f"Matched skills: {matched_skills_str}\n"
            f"Skill gaps: {missing_skills_str}\n"
            f"Matched domains: {matched_domains_str}\n"
            f"Domain gaps: {missing_domains_str}\n\n"
            f"Knowledge graph paths showing how this candidate connects to the job:\n{paths_str}\n\n"
            "Write 2–3 sentences explaining why this candidate is or is not a strong match for this role. "
            "Mention specific skills and domains by name. If there are gaps, note what they would need. "
            "Write for a recruiter."
        )

        text = await self._call_with_retry(
            model=self._model_name,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.4,
        )
        return text.strip()

    async def extract_job_posting(self, job_text: str) -> JobPostingExtraction:
        """
        Extract structured job requirements from raw job posting text.

        Returns a validated JobPostingExtraction with skill requirements,
        domain requirements, work styles, and company metadata.
        """
        system_msg = (
            "You are an expert HR data extractor. Extract structured job requirements "
            "and return ONLY valid JSON matching this exact schema:\n\n"
            f"{_JOB_SCHEMA}\n\n"
            "Constraints:\n"
            "- skill.family must be one of: Programming Languages, Web Frameworks, "
            "Databases, Cloud & DevOps, ML & AI, Data Engineering, Mobile Development, "
            "Testing & QA, Analytics & Visualization, Other\n"
            "- domain.family must be one of: FinTech, Healthcare, E-commerce, SaaS, "
            "Enterprise, Gaming, Education, Other\n"
            "- remote_policy must be one of: 'remote', 'hybrid', 'onsite'\n"
            "- company_size must be one of: 'startup', 'mid-size', 'enterprise'\n"
            "- importance must be one of: 'must_have', 'nice_to_have'\n"
            "- Return an empty list [] for any section with no data — never omit keys."
        )

        user_msg = (
            "Extract all job requirements from the following job posting.\n\n"
            "Skill family reference:\n"
            f"{self._skill_hint}\n\n"
            "Domain family reference:\n"
            f"{self._domain_hint}\n\n"
            f"JOB POSTING:\n{job_text}"
        )

        raw_json = await self._call_with_retry(
            model=self._model_name,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
        )
        extracted = JobPostingExtraction.model_validate_json(raw_json)
        logger.info(
            f"Extracted job: {extracted.title} at {extracted.company} — "
            f"{len(extracted.skill_requirements)} skill requirements"
        )
        return extracted
