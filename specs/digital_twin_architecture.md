# Digital Twin Architecture

## Vision

The job recommender does not store a resume. It builds a **digital twin** — a living graph
portrait of the person behind the resume: what drives them, how they think, the real stories
behind their work, and where they are headed.

When a recruiter views a matched candidate, they should know not just what the person has built,
but who they are. The graph is the person.

---

## Two Layers of Depth

### Layer 1 — Technical Depth (pre-existing)
What the person knows and can do, evidenced by real work:

| Node | Purpose |
|------|---------|
| `Skill` | Technology/capability with evidence strength (claimed_only → multiple_productions) |
| `Domain` | Industry/problem space expertise |
| `Project` | Concrete work with 5W+H context on every skill edge |
| `Experience` | Work history with accomplishments and contribution type |
| `ProblemSolvingPattern` | Working style inferred from evidence |
| `CriticalAssessment` | AI-generated recruiter lens: honest summary, red flags, seniority |

### Layer 2 — Human Depth (new)
Who the person is beyond their CV:

| Node | Purpose |
|------|---------|
| `Anecdote` | STAR-format story behind a skill, project, or decision |
| `Motivation` | What drives them (passion, impact, financial, autonomy, etc.) |
| `Value` | What they protect and prioritize (autonomy, craft, growth, security) |
| `Goal` | Where they are trying to go (5-year, career peak, life) |
| `CultureIdentity` | How they work: team preference, conflict style, energy sources |
| `BehavioralInsight` | Conversation observations: push-back, deflection, spontaneous depth |

---

## New Graph Relationships

```
User ──MOTIVATED_BY──────► Motivation
User ──HOLDS_VALUE───────► Value
User ──ASPIRES_TO────────► Goal
User ──HAS_ANECDOTE──────► Anecdote
User ──HAS_CULTURE_IDENTITY──► CultureIdentity
User ──HAS_BEHAVIORAL_INSIGHT──► BehavioralInsight

Skill ──GROUNDED_IN──────► Anecdote    (the story behind the skill)
Project ──GROUNDED_IN────► Anecdote    (the story behind the project)
Anecdote ──REVEALS_TRAIT─► ProblemSolvingPattern
```

---

## Node Schemas

### Anecdote
The STAR story behind a skill or decision. More valuable to a recruiter than any claimed level.

```
name              — short descriptive title, e.g. "K8s Migration at Stripe 2023"
situation         — context and constraints the person was in
task              — what they were specifically responsible for
action            — what they actually did (be specific — no "we")
result            — what came out of it, ideally with a metric
lesson_learned    — what they took away
emotion_valence   — positive | negative | mixed
confidence_signal — high | medium | low (inferred from HOW they told it, not what they said)
spontaneous       — did they volunteer this unprompted?
source            — 'conversation'
```

### Motivation
What drives the person, inferred from patterns across stories — never asked directly.

```
name      — matches category (e.g. "impact_driven")
category  — impact_driven | passion_driven | financial_security | wealth_accumulation
            | recognition_driven | stability_seeking | growth_seeking | autonomy_seeking
strength  — 0.0–1.0
evidence  — brief quote or behavior that revealed this
source    — 'conversation'
```

### Value
What the person protects and prioritizes.

```
name          — e.g. "autonomy", "craft_quality", "work_life_balance"
priority_rank — 1 (highest) to 10
evidence      — what they said or did that revealed this
source        — 'conversation'
```

### Goal
Where they are trying to go.

```
name            — short title, e.g. "Lead infra at a company solving hard problems"
type            — 5_year | career_peak | immediate | life
description     — full description
timeframe_years — integer
clarity_level   — vague | directional | specific
source          — 'conversation'
```

### CultureIdentity
How they work and what environment brings out their best.

```
team_size_preference  — solo | small_tight | large_structured
leadership_style      — servant | directive | collaborative | invisible
conflict_style        — direct | diplomatic | avoidant | analytical
feedback_preference   — frequent_small | milestone_big | self_directed
energy_sources        — JSON array, e.g. ["hard problems", "shipping", "mentoring"]
energy_drains         — JSON array, e.g. ["meetings", "politics", "ambiguity"]
pace_preference       — sprint | steady | deliberate
source                — 'conversation'
```

### BehavioralInsight
Observations from the conversation itself. These are data about the person, not just what they said.

```
name             — short unique id, e.g. "push_back_k8s_mar2024"
insight_type     — push_back | rehearsed_answer | deflection | spontaneous_depth
                   | inconsistency | avoidance | openness
trigger          — what question prompted this behavior
response_pattern — what they said or did
implication      — what this signals about them as a person
source           — 'conversation'
```

---

## The Interview System

### Interviewer Persona
The LLM edit agent is a **sincere, deeply curious interviewer** — not a form-filler.
Its goal is to understand the person, then build the graph from what it learns.

It does NOT:
- Validate a resume
- Accept claims at face value
- Flatter the user ("great answer!")
- Ask multiple questions at once
- Hallucinate — if unsure, it asks

It DOES:
- Ask why before adding anything
- Collect the story behind every skill
- Infer motivation from patterns, not from direct questions
- Record push-back as behavioral data
- Apply mental models to every answer

### Mental Models Applied to Probing

**First Principles** — Strip away labels and ask what is actually true.
> "You said you led the migration. What does lead mean here — did you make architectural decisions, or coordinate execution?"

**Second Order Thinking** — Ask about the consequences of decisions.
> "That worked. What problems did it create downstream, 6 months later?"

**Inversion** — Ask about failure to find what success actually means.
> "What would have gone wrong if you hadn't done this?"
> "What almost made this fail?"
> "What would make you never want to do this kind of work again?"

**Occam's Razor** — When the story is complex, look for the simpler truth.
> "Set aside the team context. What did YOU specifically contribute?"

**5W+H** — Used as a completeness checklist on every technical claim.
Do not write a `DEMONSTRATES_SKILL` edge until WHO, WHAT, WHY, and HOW are all present.

### The Why-Ladder
When someone adds a skill or makes a claim:
1. Ask why they learned it / used it
2. Ask what the specific situation was
3. Ask what they personally did (not the team)
4. Ask what broke or went wrong
5. Keep going until a genuine story emerges

### Push-Back Protocol
If the user says "just add it" without explanation:
1. Add the node immediately (they feel heard)
2. Gently redirect: "Added. Is there a project where this was central? I want that story."
3. Create a `BehavioralInsight` node: `push_back`, what triggered it, what it implies
4. The recruiter sees the skill AND the behavioral signal

---

## The Scrutability Banner

Every conversation turn returns a `GraphImpactBanner` in the `GraphMutationProposal`.
This is shown to the user in the UI to make the graph building visible and transparent.

```json
{
  "headline": "Your answer updated 3 nodes in your digital twin",
  "items": [
    {
      "icon": "skill",
      "label": "Kubernetes",
      "change_type": "update",
      "detail": "Evidence upgraded: mentioned_once → project_backed"
    },
    {
      "icon": "anecdote",
      "label": "K8s Migration at Stripe 2023",
      "change_type": "add",
      "detail": "New story added — recruiters can now read the context behind this skill"
    },
    {
      "icon": "motivation",
      "label": "impact_driven",
      "change_type": "infer",
      "detail": "Inferred from your pattern of choosing hard problems over comfortable roles"
    }
  ],
  "digital_twin_progress": "Technical depth: 72% | Human depth: 31%"
}
```

At session start, an `interview_banner` is shown:

> "Everything you share in this conversation shapes your digital twin. Recruiters won't just
> see your skills — they'll see your stories, your motivations, and how you think. The more
> genuine your answers, the more accurately this profile will represent who you truly are."

### Human Depth Score (estimated by LLM)
| Signal | Weight |
|--------|--------|
| Anecdotes per skill family | 30% |
| Motivations + Values confirmed | 25% |
| Goal clarity | 20% |
| CultureIdentity present | 15% |
| BehavioralInsights recorded | 10% |

---

## What the Recruiter Sees

When a recruiter views a matched candidate, they get:

**Technical match** (existing):
- Matched skills with evidence, years, level
- 5W+H context on every skill-project edge
- Domain match depth

**Human portrait** (new):
- The story behind their most important skills (via `GROUNDED_IN` → `Anecdote`)
- What drives them (`MOTIVATED_BY` → `Motivation`)
- Their 5-year goal (`ASPIRES_TO` → `Goal`)
- How they like to work (`HAS_CULTURE_IDENTITY` → `CultureIdentity`)
- Conversation signals (`HAS_BEHAVIORAL_INSIGHT` → `BehavioralInsight`)

**Interview guidance** (existing `CriticalAssessment`, enriched):
- Focus areas derived from behavioral insights and motivation patterns
- Push-back patterns flagged for follow-up in the real interview

---

## File Reference

| File | Change |
|------|--------|
| `models/schemas.py` | Added `GraphImpactItem`, `GraphImpactBanner`; updated `GraphMutationProposal` with `graph_impact_banner`; updated `EditSessionResponse` with `interview_banner` |
| `services/llm_edit_agent.py` | Rewritten system prompt: sincere interviewer persona, why-ladder, push-back protocol, anecdote extraction, motivation inference, mental models (First Principles, Second Order Thinking, Inversion, Occam's Razor, 5W+H), graph impact banner instructions |
| `services/graph_edit_service.py` | Added `_add_node()` handlers for: `Anecdote`, `Motivation`, `Value`, `Goal`, `CultureIdentity`, `BehavioralInsight` — each auto-links to `User` node |
| `database/neo4j_client.py` | Added uniqueness constraints for all 6 new node types |
