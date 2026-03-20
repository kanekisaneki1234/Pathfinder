"""
Pydantic schemas for two purposes:
1. Gemini structured output (response_schema) — controls LLM extraction format
2. FastAPI request/response bodies — controls API interface

Keep these separate to allow them to evolve independently.
"""

from typing import List, Literal, Optional
from pydantic import BaseModel, Field, field_validator


# ──────────────────────────────────────────────────────────────────────────────
# GEMINI EXTRACTION SCHEMAS
# Passed as response_schema to GenerationConfig. Gemini enforces the JSON shape.
# ──────────────────────────────────────────────────────────────────────────────

class ExtractedSkill(BaseModel):
    name: str = Field(description="Canonical skill name, e.g. 'Python', 'React'")
    family: str = Field(
        description=(
            "Skill family grouping. Must be one of: "
            "Programming Languages, Web Frameworks, Databases, Cloud & DevOps, "
            "ML & AI, Data Engineering, Mobile Development, Testing & QA, "
            "Analytics & Visualization, Other"
        )
    )
    years: Optional[float] = Field(default=None, description="Years of experience, null if unknown")
    level: Optional[Literal["beginner", "intermediate", "advanced", "expert"]] = Field(
        default=None, description="Proficiency level inferred from context — be conservative, not generous"
    )
    evidence_strength: Optional[Literal["claimed_only", "mentioned_once", "project_backed", "multiple_productions"]] = Field(
        default=None,
        description=(
            "How well evidenced is this skill? "
            "'claimed_only' = listed as skill but no project evidence; "
            "'mentioned_once' = appears in one project/role but superficially; "
            "'project_backed' = has at least one concrete project with this skill; "
            "'multiple_productions' = demonstrated across multiple real projects/roles"
        )
    )


class SkillUsage(BaseModel):
    """
    Rich 5W+H capture of a skill used in a specific project context.
    This enables graph-to-graph matching beyond simple name matching.
    """
    name: str = Field(description="Canonical skill name used in this project, e.g. 'Python', 'React'")
    what: Optional[str] = Field(
        default=None,
        description="WHAT was built or accomplished using this skill in this project. Be specific."
    )
    how: Optional[str] = Field(
        default=None,
        description=(
            "HOW this skill was applied — specific patterns, techniques, frameworks, or approaches used. "
            "E.g. 'Used async/await patterns with connection pooling to handle concurrent DB queries'"
        )
    )
    why: Optional[str] = Field(
        default=None,
        description="WHY this skill was chosen or what problem it solved in this context."
    )
    scale: Optional[str] = Field(
        default=None,
        description="Scale or scope: users, data volume, requests/sec, team size, revenue — whatever is relevant."
    )
    outcome: Optional[str] = Field(
        default=None,
        description="Measurable outcome or impact from using this skill. Null if not mentioned."
    )
    # Computed summary for backwards-compat and quick display
    context: Optional[str] = Field(
        default=None,
        description=(
            "Single-sentence summary combining the most important 5W+H signals. "
            "Auto-generate from the other fields if not provided. "
            "E.g. 'Built async payment API (FastAPI) handling 10k req/s, reducing latency by 40%'"
        )
    )


class ExtractedProject(BaseModel):
    name: str = Field(description="Project name")
    description: str = Field(
        description=(
            "Rich description covering: (1) what the project does, (2) your specific contribution "
            "vs team contribution, (3) scale or impact (users, data volume, team size, revenue), "
            "(4) key technical challenges solved. Be specific and quantify where possible. "
            "Do NOT embellish — capture only what is stated."
        )
    )
    skills_demonstrated: List[SkillUsage] = Field(
        description="Skills directly used in this project, each with context on HOW it was applied"
    )
    domain: Optional[str] = Field(
        default=None,
        description="Domain this project belongs to, e.g. 'FinTech', 'Healthcare'"
    )
    contribution_type: Optional[Literal["sole_engineer", "tech_lead", "senior_contributor", "team_member", "unclear"]] = Field(
        default=None,
        description="What was the person's actual role/ownership level on this project?"
    )
    has_measurable_impact: bool = Field(
        default=False,
        description="True only if the description contains at least one concrete metric or measurable outcome"
    )


class ExtractedDomain(BaseModel):
    name: str = Field(description="Specific domain area, e.g. 'Payment Systems', 'NLP'")
    family: str = Field(
        description=(
            "Domain family. Must be one of: "
            "FinTech, Healthcare, E-commerce, SaaS, Enterprise, Gaming, Education, Other"
        )
    )
    years_experience: Optional[float] = Field(
        default=None, description="Years of domain experience, null if unknown"
    )
    depth: Optional[Literal["shallow", "moderate", "deep"]] = Field(
        default=None, description="Depth of domain knowledge"
    )


class ExtractedExperience(BaseModel):
    title: str = Field(description="Job title")
    company: Optional[str] = Field(default=None, description="Company name, null if not mentioned")
    duration_years: Optional[float] = Field(
        default=None, description="Duration in years, null if unknown"
    )
    description: Optional[str] = Field(default=None, description="Role description")
    accomplishments: List[str] = Field(
        default_factory=list,
        description=(
            "Concrete, specific accomplishments from this role. Each must name what was done, "
            "how it was done, and ideally a measurable outcome or scale. "
            "E.g. 'Reduced API latency by 40% by migrating from REST polling to WebSocket streaming for 50k daily users'. "
            "If the profile is vague, capture exactly what is stated without embellishing."
        )
    )
    contribution_type: Optional[Literal["sole_engineer", "tech_lead", "senior_contributor", "team_member", "unclear"]] = Field(
        default=None,
        description=(
            "What was their actual role in this experience? "
            "'sole_engineer' = built it alone; 'tech_lead' = led a team; "
            "'senior_contributor' = senior IC on a team; 'team_member' = one of many contributors; "
            "'unclear' = cannot determine from profile"
        )
    )


class ExtractedPreference(BaseModel):
    type: str = Field(
        description=(
            "Preference type. Use one of: "
            "remote_work, company_size, work_style, role_type, location, salary_range"
        )
    )
    value: str = Field(description="Preference value, e.g. 'remote', 'startup', 'async-first'")


class ExtractedPattern(BaseModel):
    pattern: str = Field(
        description=(
            "Problem-solving pattern demonstrated, e.g. "
            "'systems thinker', 'data-driven', 'user-focused', 'performance-oriented'"
        )
    )
    evidence: Optional[str] = Field(
        default=None, description="Brief evidence from the profile"
    )


class CriticalAssessment(BaseModel):
    """
    Brutally honest assessment of the candidate from a recruiter/engineering manager lens.
    This is NOT flattery — it is a calibrated, evidence-based evaluation.
    """
    overall_signal: Literal["strong", "moderate", "weak", "misleading"] = Field(
        description=(
            "Overall signal quality of this profile. "
            "'strong' = concrete evidence, real impact, clearly owned work; "
            "'moderate' = some evidence but gaps or vagueness; "
            "'weak' = mostly vague, no quantified impact, buzzword-heavy; "
            "'misleading' = claims inconsistent with or unsupported by evidence"
        )
    )
    seniority_assessment: Literal["junior", "mid", "senior", "staff_plus", "unclear"] = Field(
        description=(
            "Honest seniority level based on evidence, NOT claimed title. "
            "Assess ownership, scope of impact, and technical depth actually demonstrated."
        )
    )
    depth_vs_breadth: Literal["deep_specialist", "strong_generalist", "shallow_generalist", "unclear"] = Field(
        description=(
            "'deep_specialist' = strong depth in 1-2 areas with production evidence; "
            "'strong_generalist' = solid across multiple areas with real projects; "
            "'shallow_generalist' = many skills listed but none well-evidenced; "
            "'unclear' = cannot determine"
        )
    )
    ownership_signals: List[str] = Field(
        default_factory=list,
        description=(
            "Concrete signals of individual ownership and impact. "
            "E.g. 'Led migration of monolith to microservices serving 2M users', "
            "'Solo-built the entire data pipeline from scratch'. "
            "Only include if clearly stated in the profile."
        )
    )
    red_flags: List[str] = Field(
        default_factory=list,
        description=(
            "Specific concerns a recruiter or EM would have. Be specific and blunt. "
            "E.g. 'Claims 5 years Python but all projects are tutorial-level CRUD apps', "
            "'3 jobs in 18 months with no explanation', "
            "'All project descriptions are vague: no metrics, no ownership clarity', "
            "'Skill list reads like a keyword dump — 15+ technologies with no depth evidence'"
        )
    )
    inflated_skills: List[str] = Field(
        default_factory=list,
        description=(
            "Skills where the claimed level is higher than what the evidence supports. "
            "E.g. 'Kubernetes: claims expert but only mentioned in passing once', "
            "'Machine Learning: listed but all projects are simple sklearn tutorials'"
        )
    )
    genuine_strengths: List[str] = Field(
        default_factory=list,
        description=(
            "Skills or areas where the profile shows genuine, evidenced strength. "
            "Only include things actually backed by concrete project/experience evidence."
        )
    )
    honest_summary: str = Field(
        description=(
            "A 2-3 sentence brutally honest summary of who this person actually is, "
            "written as if you're an engineering manager advising a recruiter off the record. "
            "What can this person actually do? What level are they really at? "
            "What would worry you about hiring them for a senior role?"
        )
    )
    candidate_identity: str = Field(
        default="",
        description=(
            "A precise, honest 1-paragraph profile of WHO this person is professionally. "
            "Cover: their primary technical identity (e.g. 'backend Python engineer'), "
            "the domain/industry they are genuinely experienced in, "
            "their actual seniority level, their working style signals, "
            "and what type of role/team they would thrive or struggle in. "
            "This is the 'in and out' picture of the candidate before any interview."
        )
    )
    five_w_h_summary: dict = Field(
        default_factory=dict,
        description=(
            "5W+H summary of the candidate: "
            "{'who': 'who they are professionally', "
            "'what': 'what they build/do', "
            "'when': 'timeline/career progression', "
            "'where': 'domains/companies/contexts they operate in', "
            "'why': 'what drives them / what problems they solve', "
            "'how': 'their technical approach and working style'}"
        )
    )
    interview_focus_areas: List[str] = Field(
        default_factory=list,
        description=(
            "The 2-3 most important areas to probe in a technical interview to validate "
            "or disprove what is claimed. E.g. 'Probe actual Kubernetes production experience — "
            "ask what they specifically configured and what broke', "
            "'Ask for the exact architecture of the payment system — the description is vague'"
        )
    )


class InterpretationFlag(BaseModel):
    """
    A single uncertain interpretation made by the LLM during extraction.
    Each flag = one clarification question to ask the user before finalising the graph.
    The graph node/edge it refers to is identified by `field` in the format Type:name:property.
    """
    field: str = Field(
        description=(
            "Dot-path to the interpreted field. Format: 'Type:Name:property'. "
            "Examples: 'Skill:Python:level', 'Project:PaymentAPI:contribution_type', "
            "'Experience:Senior Engineer at Stripe:accomplishments', 'Domain:FinTech:depth'"
        )
    )
    raw_text: str = Field(
        description="The exact text snippet from the resume that led to this interpretation. Quote it directly."
    )
    interpreted_as: str = Field(
        description="What the LLM decided this means. Be specific: e.g. 'level=advanced, years=3'"
    )
    confidence: Literal["high", "medium", "low"] = Field(
        description=(
            "'high' = clearly stated; 'medium' = inferred from context; "
            "'low' = assumed/guessed with minimal evidence"
        )
    )
    ambiguity_reason: str = Field(
        description=(
            "Why is this uncertain? E.g. 'Years not stated — inferred from job timeline', "
            "'Contribution unclear — resume uses we/our throughout', "
            "'Level inferred from seniority of role, not from technical depth described'"
        )
    )
    clarification_question: str = Field(
        description=(
            "The exact natural-language question to show the user to resolve this. "
            "Be specific and reference their actual resume content. "
            "E.g. 'Your resume says \"built a payment API\" — were you the sole engineer on this, "
            "or part of a larger team? What was your specific contribution?'"
        )
    )
    resolution_impact: Literal["critical", "important", "minor"] = Field(
        description=(
            "'critical' = directly affects job matching (skill level, years, domain depth); "
            "'important' = affects context quality (contribution type, project scale); "
            "'minor' = enrichment only (preferences, patterns)"
        )
    )
    suggested_options: Optional[List[str]] = Field(
        default=None,
        description="If this is a multiple-choice clarification, provide the options. Leave null for open-ended."
    )


class UserProfileExtraction(BaseModel):
    """Top-level schema for Gemini user profile extraction. Passed as response_schema."""
    skills: List[ExtractedSkill] = Field(default_factory=list)
    projects: List[ExtractedProject] = Field(default_factory=list)
    domains: List[ExtractedDomain] = Field(default_factory=list)
    experiences: List[ExtractedExperience] = Field(default_factory=list)
    preferences: List[ExtractedPreference] = Field(default_factory=list)
    patterns: List[ExtractedPattern] = Field(default_factory=list)
    assessment: Optional[CriticalAssessment] = Field(
        default=None,
        description="Critical recruiter/EM lens assessment of the entire profile"
    )
    interpretation_flags: List[InterpretationFlag] = Field(
        default_factory=list,
        description=(
            "All uncertain interpretations made during extraction that require user clarification. "
            "Generate a flag for EVERY field where confidence is medium or low, "
            "and for any inference that materially affects matching (skill levels, years, contribution types). "
            "Order by resolution_impact DESC (critical first)."
        )
    )


class ExtractedJobSkillRequirement(BaseModel):
    name: str = Field(description="Skill name")
    family: str = Field(
        description=(
            "Skill family. Must be one of: "
            "Programming Languages, Web Frameworks, Databases, Cloud & DevOps, "
            "ML & AI, Data Engineering, Mobile Development, Testing & QA, "
            "Analytics & Visualization, Other"
        )
    )
    required: bool = Field(default=True, description="True if required, False if nice-to-have")
    importance: Literal["must_have", "nice_to_have"] = Field(
        default="must_have",
        description="must_have for required skills, nice_to_have for preferred"
    )
    min_years: Optional[int] = Field(
        default=None, description="Minimum years required, null if not specified"
    )


class ExtractedJobDomainRequirement(BaseModel):
    name: str = Field(description="Domain area required, e.g. 'Payment Systems'")
    family: str = Field(
        description=(
            "Domain family. Must be one of: "
            "FinTech, Healthcare, E-commerce, SaaS, Enterprise, Gaming, Education, Other"
        )
    )
    min_years: Optional[int] = Field(default=None)


class ExtractedWorkStyle(BaseModel):
    style: str = Field(
        description=(
            "Work style or culture indicator, e.g. "
            "'async-first', 'fast-paced', 'high-autonomy', 'collaborative', 'remote-first'"
        )
    )


class JobPostingExtraction(BaseModel):
    """Top-level schema for Gemini job posting extraction. Passed as response_schema."""
    title: str = Field(description="Job title")
    company: Optional[str] = Field(default=None, description="Company name")
    skill_requirements: List[ExtractedJobSkillRequirement] = Field(default_factory=list)
    domain_requirements: List[ExtractedJobDomainRequirement] = Field(default_factory=list)
    work_styles: List[ExtractedWorkStyle] = Field(default_factory=list)
    remote_policy: Optional[str] = Field(
        default=None,
        description="Remote policy: 'remote', 'hybrid', 'onsite'"
    )
    company_size: Optional[str] = Field(
        default=None,
        description="Company size: 'startup', 'mid-size', 'enterprise'"
    )
    experience_years_min: Optional[int] = Field(
        default=None, description="Minimum years of experience required"
    )


# ──────────────────────────────────────────────────────────────────────────────
# FASTAPI REQUEST / RESPONSE SCHEMAS
# ──────────────────────────────────────────────────────────────────────────────

class IngestUserRequest(BaseModel):
    user_id: str = Field(description="Unique identifier for the user")
    profile_text: str = Field(
        description="Raw resume or profile text to process through the hybrid pipeline"
    )


class IngestJobRequest(BaseModel):
    job_id: str = Field(description="Unique identifier for the job posting")
    job_text: str = Field(
        description="Raw job posting text to process through the hybrid pipeline"
    )
    recruiter_id: Optional[str] = Field(default=None, description="ID of the recruiter who posted this job")


class MatchedSkill(BaseModel):
    skill: str
    user_years: Optional[float]
    user_level: Optional[str]
    required_years: Optional[int]
    importance: str
    contribution: float


class MatchResult(BaseModel):
    job_id: str
    job_title: str
    company: Optional[str]
    # Core score (0-1): dynamically weighted across available dimensions
    total_score: float
    # Individual dimension scores (0-1 each)
    skill_score: float          # evidence-weighted: claimed_only=0.3x, project_backed=0.8x, multiple_productions=1.0x
    domain_score: float         # depth-weighted: shallow=0.4x, moderate=0.7x, deep=1.0x
    soft_skill_score: float = 0.0   # 0 when job has no SoftSkillRequirements or user has no patterns
    culture_fit_score: float = 0.0  # 0 when either side lacks digital twin culture data
    # Legacy bonus signals (kept for backwards compat, not in total_score)
    culture_bonus: float        # work-style preference match ratio (old lightweight version)
    preference_bonus: float     # remote/company_size match ratio
    # Match detail
    matched_skills: List[str]
    missing_skills: List[str]
    matched_domains: List[str]
    missing_domains: List[str]
    behavioral_risk_flags: List[str] = Field(
        default_factory=list,
        description="Risk signals from BehavioralInsight nodes that conflict with dealbreaker soft skills"
    )
    explanation: str


class BatchMatchResponse(BaseModel):
    user_id: str
    results: List[MatchResult]
    total_jobs_ranked: int


class CandidateResult(BaseModel):
    """Reverse-match result: one user scored against a specific job."""
    user_id: str
    total_score: float
    skill_score: float
    domain_score: float
    soft_skill_score: float = 0.0
    culture_fit_score: float = 0.0
    culture_bonus: float
    preference_bonus: float
    matched_skills: List[str]
    missing_skills: List[str]
    matched_domains: List[str]
    missing_domains: List[str]
    behavioral_risk_flags: List[str] = Field(default_factory=list)
    explanation: str


class BatchCandidateResponse(BaseModel):
    job_id: str
    results: List[CandidateResult]
    total_users_ranked: int


class IngestionStats(BaseModel):
    entity_id: str
    entity_type: Literal["user", "job"]
    skills_extracted: int = 0
    domains_extracted: int = 0
    projects_extracted: int = 0
    experiences_extracted: int = 0


# ──────────────────────────────────────────────────────────────────────────────
# EDIT SESSION SCHEMAS
# ──────────────────────────────────────────────────────────────────────────────

class GraphMutation(BaseModel):
    """Structured set of graph mutations proposed by the LLM."""
    add_nodes: List[dict] = Field(default_factory=list)
    update_nodes: List[dict] = Field(default_factory=list)
    remove_nodes: List[str] = Field(default_factory=list, description="Node names to remove (e.g. 'GraphQL' or 'Skill:GraphQL')")
    add_edges: List[dict] = Field(
        default_factory=list,
        description=(
            "Each dict: {from: 'Type:name', rel: 'REL_TYPE', to: 'Type:name', context: '...'}. "
            "For DEMONSTRATES_SKILL edges, always include a 'context' field describing HOW the skill "
            "was used in that project (approach, tools, outcome)."
        )
    )


class GraphImpactItem(BaseModel):
    """A single node/edge change surfaced in the scrutability banner."""
    icon: Literal[
        "skill", "anecdote", "motivation", "value", "goal",
        "culture", "behavior", "domain", "project", "experience"
    ]
    label: str = Field(description="Human-readable name of the thing being changed, e.g. 'Kubernetes'")
    change_type: str = Field(description="Type of graph change: add|update|infer|flag|initiated")
    detail: str = Field(description="One-sentence explanation of what changed and why it matters to the profile")

    @field_validator("change_type", mode="before")
    @classmethod
    def coerce_change_type(cls, v: str) -> str:
        _VALID = {"add", "update", "infer", "flag", "initiated"}
        return v if v in _VALID else "update"


class GraphImpactBanner(BaseModel):
    """
    Scrutability banner shown to the user after each conversation turn.
    Tells them exactly how their answer is shaping their digital twin in the graph.
    """
    headline: str = Field(description="1-sentence summary, e.g. 'Your answer updated 3 nodes in your digital twin'")
    items: List[GraphImpactItem] = Field(default_factory=list)
    digital_twin_progress: Optional[str] = Field(
        default=None,
        description="Optional progress hint, e.g. 'Technical depth: 72% | Human depth: 31%'"
    )


class GraphMutationProposal(BaseModel):
    """LLM response: reasoning, proposed mutations, next interview question, and scrutability banner."""
    reasoning: str = Field(description="LLM's reasoning visible to the user")
    mutations: GraphMutation
    follow_up_question: str = Field(description="Next interview question to ask")
    graph_impact_banner: Optional[GraphImpactBanner] = Field(
        default=None,
        description="Scrutability banner showing what this conversation turn updates in the graph"
    )


class EditSessionMessage(BaseModel):
    role: str = Field(description="'user' | 'assistant' | 'system'")
    content: str
    proposal: Optional[GraphMutationProposal] = None


class EditSessionResponse(BaseModel):
    session_id: str
    opening_question: str
    graph_summary: dict
    interview_banner: str = Field(
        default=(
            "Everything you share in this conversation shapes your digital twin. "
            "Recruiters won't just see your skills — they'll see your stories, your motivations, "
            "and how you think. The more genuine your answers, the more accurately this profile "
            "will represent who you truly are. Every answer you give can update your graph in real time."
        ),
        description="Scrutability notice shown prominently when the session starts"
    )


class StartEditRequest(BaseModel):
    recruiter_id: Optional[str] = Field(default=None, description="Required for job edit sessions")


class SendMessageRequest(BaseModel):
    session_id: str
    message: str


class ApplyMutationsRequest(BaseModel):
    session_id: str
    mutations: GraphMutation


class RejectMutationsRequest(BaseModel):
    session_id: str


class ApplyMutationsResponse(BaseModel):
    auto_checkpoint_version_id: str
    nodes_added: int
    nodes_updated: int
    nodes_removed: int
    edges_added: int


class GraphVersion(BaseModel):
    version_id: str
    entity_type: str   # 'user' | 'job'
    entity_id: str
    session_id: Optional[str] = None
    label: str
    created_at: str


class CheckpointRequest(BaseModel):
    label: Optional[str] = Field(default=None, description="Human-readable label for this checkpoint")


class RollbackResponse(BaseModel):
    version_id: str
    entity_type: str
    entity_id: str
    status: str = "restored"


# ──────────────────────────────────────────────────────────────────────────────
# CLARIFICATION / DIGITAL TWIN VERIFICATION SCHEMAS
# ──────────────────────────────────────────────────────────────────────────────

class ClarificationQuestion(BaseModel):
    """A single pending clarification question shown to the user."""
    flag_id: str
    field: str                        # e.g. "Skill:Python:level"
    raw_text: str                     # the resume snippet that caused the ambiguity
    interpreted_as: str               # what the LLM assumed
    confidence: str                   # high / medium / low
    ambiguity_reason: str
    clarification_question: str       # question to show the user
    resolution_impact: str            # critical / important / minor
    suggested_options: Optional[List[str]] = None
    status: str = "pending"           # pending / confirmed / corrected / skipped


class ClarificationsResponse(BaseModel):
    user_id: str
    total_flags: int
    pending: int
    resolved: int
    questions: List[ClarificationQuestion]
    graph_verified: bool              # True once all critical flags are resolved


class ResolveFlagRequest(BaseModel):
    is_correct: bool = Field(
        description="True if the LLM's interpretation was correct. False if the user is correcting it."
    )
    user_answer: str = Field(
        description="The user's answer in their own words."
    )
    correction: Optional[str] = Field(
        default=None,
        description=(
            "If is_correct=False, provide the correct value. "
            "For multiple-choice fields use the exact option. "
            "For text fields write the corrected value."
        )
    )


class ResolveFlagResponse(BaseModel):
    flag_id: str
    status: str                        # confirmed / corrected
    graph_updated: bool
    updated_field: Optional[str] = None
    updated_value: Optional[str] = None
    remaining_critical: int            # how many critical flags still pending


# ──────────────────────────────────────────────────────────────────────────────
# DIGITAL TWIN COMPLETENESS
# ──────────────────────────────────────────────────────────────────────────────

class TechnicalDepthBreakdown(BaseModel):
    score_pct: int                          # 0-100
    skills_total: int
    skills_evidenced: int                   # evidence_strength != claimed_only
    skills_with_anecdotes: int              # GROUNDED_IN → Anecdote edges
    skills_claimed_only: int                # full weight penalty in matching
    projects_total: int
    projects_with_impact: int               # has_measurable_impact = true
    experiences_total: int
    experiences_with_accomplishments: int   # non-empty accomplishments list
    has_critical_assessment: bool


class HumanDepthBreakdown(BaseModel):
    score_pct: int                          # 0-100
    anecdotes_count: int                    # total Anecdote nodes
    anecdotes_target: int = 5              # how many we consider "complete"
    motivations_identified: bool            # has >= 1 Motivation node
    values_identified: bool                 # has >= 1 Value node
    goal_set: bool                          # has >= 1 Goal node
    culture_identity_built: bool            # has CultureIdentity node
    behavioral_insights_count: int          # total BehavioralInsight nodes
    # Culture fit scoring is disabled if this is False — surfaced to user
    culture_matching_enabled: bool


class DigitalTwinCompleteness(BaseModel):
    """
    Computed (not LLM-generated) profile completeness score.
    Shows how fully the digital twin represents the person across both
    technical depth and human depth dimensions.

    Both dimensions must be strong for full matching power:
      - Technical depth affects skill/domain scoring accuracy
      - Human depth enables soft skill and culture fit scoring
    """
    overall_pct: int                        # weighted average of both dimensions
    technical_depth: TechnicalDepthBreakdown
    human_depth: HumanDepthBreakdown

    # Matching capability flags — shown to user so they understand impact
    evidence_weighted_scoring_active: bool  # True when skills have evidence beyond claimed_only
    soft_skill_scoring_active: bool         # True when ProblemSolvingPattern nodes exist
    culture_fit_scoring_active: bool        # True when CultureIdentity node exists
    profile_verified: bool                  # True when all critical clarification flags resolved

    # Actionable gaps — specific, honest, with matching impact
    missing_dimensions: List[str]
    # The single most impactful next action
    next_action: str
