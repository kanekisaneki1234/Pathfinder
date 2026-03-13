# Spec: Scrutability to Edit User Profile & Job Model Graphs

**Issue**: [#4](https://github.com/AjinkyaTaranekar/Lumino/issues/4)
**Assignees**: AjinkyaTaranekar, ShreshthaKamboj, xizhenluo
**Status**: Backlog

---

## Problem Statement

Users currently have no way to correct, refine, or augment the knowledge graph that the LLM extracted from their resume. The graph is a "black box write" — once ingested, it's fixed. This is a trust and accuracy problem: LLM extraction makes mistakes, users have nuanced context the LLM cannot infer, and graphs become stale as people grow.

---

## Goals

1. Let users edit their profile graph via a conversational LLM interface (First Principles questioning).
2. Let recruiters/admins similarly edit job model graphs.
3. Show real-time graph re-visualization after each change.
4. Support versioning / rollback so users can recover from bad edits.
5. Surface skill-level expertise weights on graph nodes.
6. Show matched vs. missing skills inline.

---

## User Stories

| As a... | I want to... | So that... |
|---------|-------------|------------|
| Job seeker | Click "Edit" on my profile graph | I can correct or add missing skills/experiences |
| Job seeker | Chat with an LLM using First Principles questions | I can articulate depth of experience the LLM didn't infer |
| Job seeker | See my graph update live during the chat | I understand what changed and why |
| Job seeker | Accept or reject the LLM's proactive suggestions | I stay in control of my own data |
| Job seeker | Roll back to a previous graph version | I can undo bad edits |
| Recruiter | Edit a job requirement graph | I can fix incorrectly extracted requirements |
| Any user | See node weight / expertise level visually | I can identify my strongest vs. weakest areas |
| Any user | See matched vs. missing skills highlighted | I understand my gap at a glance |

---

## Non-Goals (out of scope for this issue)

- Bulk import / re-upload of resume to replace graph.
- Admin-side graph merging across users.
- Real-time collaboration between multiple users on one graph.

---

## Architecture Overview

```
Frontend (React)
  └── EditProfilePage.jsx          ← new page (user graph)
  └── EditJobModelPage.jsx         ← new page (job graph, recruiter)
        ├── GraphViewer (existing) ← live re-render via version polling
        ├── ChatPanel (new)        ← LLM First Principles conversation
        └── SuggestionPanel (new)  ← proactive LLM suggestions (accept/reject)

Backend (FastAPI)
  └── POST /api/v1/users/{user_id}/graph/edit/start        ← start edit session
  └── POST /api/v1/users/{user_id}/graph/edit/message      ← send chat turn
  └── POST /api/v1/users/{user_id}/graph/edit/apply        ← commit LLM-proposed changes
  └── POST /api/v1/users/{user_id}/graph/edit/reject       ← discard proposed changes
  └── GET  /api/v1/users/{user_id}/graph/versions          ← list checkpoints
  └── POST /api/v1/users/{user_id}/graph/rollback/{version_id} ← restore version
  └── POST /api/v1/jobs/{job_id}/graph/edit/*              ← same pattern for jobs

Services
  └── GraphEditService (new)       ← orchestrates sessions, diffs, checkpoints
  └── LLMEditAgent (new)          ← First Principles conversation loop
  └── CheckpointService (new)     ← snapshot/restore graph subgraphs

Storage
  └── SQLite (.data_storage/lumino.db) ← edit sessions + message history + graph snapshots
  └── Neo4j                            ← live graph (unchanged role)
```

---

## Detailed Feature Breakdown

### 1. Edit Mode Entry Point

- Add an **"Edit Graph"** button to `UserModel.jsx` and `JobModel.jsx`.
- Navigates to `/user/edit-graph` (or `/recruiter/edit-job/:jobId`).
- Page layout: split view — graph on the left, chat panel on the right.

---

### 2. LLM First Principles Chat

The LLM agent does not take free-form edits. Instead it **interviews the user** using the Socratic / First Principles method:

**Session start**: LLM receives the user's current graph (serialized as JSON summary — nodes + edge counts by category) and opens with a focused question about an area to clarify.

**Question strategy (prompt-engineered)**:
- Start with the _weakest_ area (lowest `years` value or no supporting project/experience nodes).
- Ask open-ended "why" and "how" questions: _"You listed React as a skill — can you walk me through a project where you made architectural decisions using React?"_
- From the answer, extract: new skills, new projects, updated `years` values, new relationships between existing nodes.
- Propose specific graph mutations before applying them.

**Proposed mutation format** (structured JSON, shown in SuggestionPanel):
```json
{
  "add_nodes": [
    {"label": "Skill", "name": "GraphQL", "years": 2, "level": "intermediate"}
  ],
  "update_nodes": [
    {"label": "Skill", "name": "React", "years": 4}
  ],
  "remove_nodes": [],
  "add_edges": [
    {"from": "Project:E-commerce Platform", "rel": "DEMONSTRATES_SKILL", "to": "Skill:GraphQL"}
  ]
}
```

User sees a **diff view** of proposed changes, then accepts or rejects each change individually or all at once.

**Implementation**:
- New `LLMEditAgent` service wraps Groq with a multi-turn conversation array.
- System prompt includes: current graph summary JSON + edit instructions + output format schema.
- Uses Pydantic `GraphMutationProposal` schema as Groq response model (structured output).
- Conversation history is persisted in SQLite (`session_messages`) so sessions survive page refreshes.

---

### 3. Graph Mutation Application

When user accepts mutations:

1. `GraphEditService.apply_mutation(user_id, proposal)` runs Cypher transactions:
   - `MERGE` for new nodes (with `source='user_edit'` provenance tag).
   - `SET` for property updates.
   - `DETACH DELETE` for removed nodes.
   - `MERGE` for new edges.
2. Re-run `link_skill_matches()` / `link_domain_matches()` to update MATCHES edges.
3. Trigger re-visualization: `VisualizationService.generate_user_graph(user_id)`.
4. Frontend polls or receives a response signal to reload the graph iframe.

---

### 4. Versioning / Checkpointing

Snapshots and edit sessions are stored in **SQLite** at `.data_storage/lumino.db`, not in Neo4j. This avoids Neo4j's 1MB property limit and keeps transient/historical data out of the graph database.

**SQLite schema**:

```sql
-- Edit sessions (one per "Edit Graph" entry)
CREATE TABLE edit_sessions (
    session_id   TEXT PRIMARY KEY,
    entity_type  TEXT NOT NULL,   -- 'user' | 'job'
    entity_id    TEXT NOT NULL,
    recruiter_id TEXT,            -- set for job sessions; enforces ownership
    started_at   TEXT NOT NULL,
    last_active  TEXT NOT NULL
);

-- Per-turn message history (survives page refresh)
CREATE TABLE session_messages (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT NOT NULL REFERENCES edit_sessions(session_id),
    role         TEXT NOT NULL,   -- 'user' | 'assistant'
    content      TEXT NOT NULL,
    proposal_json TEXT,           -- serialized GraphMutationProposal if role='assistant'
    created_at   TEXT NOT NULL
);

-- Graph snapshots (checkpoints)
CREATE TABLE graph_snapshots (
    version_id   TEXT PRIMARY KEY,
    entity_type  TEXT NOT NULL,   -- 'user' | 'job'
    entity_id    TEXT NOT NULL,
    session_id   TEXT REFERENCES edit_sessions(session_id),
    label        TEXT NOT NULL,
    snapshot_json TEXT NOT NULL,  -- full serialized subgraph (nodes + rels as JSON)
    created_at   TEXT NOT NULL
);
```

**Checkpoint triggers**:
- Automatically before every accepted mutation batch.
- Manually when user clicks "Save checkpoint".

**Rollback**:
- `CheckpointService.rollback(entity_type, entity_id, version_id)`:
  1. Load `snapshot_json` from SQLite.
  2. `DETACH DELETE` all current entity-owned nodes in Neo4j.
  3. Deserialize and re-insert all nodes + edges.
  4. Re-run match linking.
  5. Re-generate visualization.
- Show the last 10 versions in a dropdown on the edit page.

---

### 5. Node Expertise Weights

Add a `weight` property to `Skill` and `Domain` nodes representing depth of expertise (0.0–1.0).

**Weight computation** (run during ingestion and edit):
```
weight = normalize(
  years_experience * 0.4 +
  num_projects_demonstrating * 0.3 +
  level_mapping[level] * 0.3   # beginner=0.2, intermediate=0.6, advanced=1.0
)
```

**Visual representation**: Node size in the pyvis graph scales with `weight`. Tooltip shows the weight score and breakdown.

Update `VisualizationService` to read `weight` and pass it to `pyvis.Node(size=...)`.

---

### 6. Matched / Missing Skills Display

Already partially available via `MatchResult.matched_skills` and `MatchResult.missing_skills`. Expose this directly on the edit page:

- Add a **"Skills Gap"** panel alongside the graph on the edit page.
- Fetches `GET /api/v1/users/{user_id}/matches/{job_id}` for the currently viewed job (if user came from Dashboard).
- Matched skills shown in green badges; missing skills in orange.
- Clicking a missing skill opens the chat panel pre-seeded with: _"Tell me about your experience with [skill name]"_.

---

## New Backend Components

### `models/schemas.py` additions

```python
class GraphMutation(BaseModel):
    add_nodes: list[dict]
    update_nodes: list[dict]
    remove_nodes: list[str]  # node names
    add_edges: list[dict]

class GraphMutationProposal(BaseModel):
    reasoning: str           # LLM's internal reasoning shown to user
    mutations: GraphMutation
    follow_up_question: str  # next First Principles question

class GraphVersion(BaseModel):
    version_id: str
    user_id: str
    created_at: str
    label: str
    snapshot_json: str

class EditSessionMessage(BaseModel):
    role: str                # "user" | "assistant"
    content: str
    proposal: GraphMutationProposal | None = None
```

### `database/sqlite_client.py` (new)

Thin async wrapper around Python's built-in `sqlite3` (or `aiosqlite` for non-blocking I/O):

```python
class SQLiteClient:
    def __init__(self, db_path: str = ".data_storage/lumino.db")
    async def init_schema() -> None          # runs CREATE TABLE IF NOT EXISTS on startup
    async def execute(query, params) -> None
    async def fetchall(query, params) -> list[dict]
    async def fetchone(query, params) -> dict | None
```

Called once at FastAPI startup alongside Neo4j constraint initialization.

### `services/graph_edit_service.py` (new)

```python
class GraphEditService:
    # Writes new row to edit_sessions in SQLite
    async def start_session(entity_type: str, entity_id: str, recruiter_id: str | None) -> EditSession
    # Appends to session_messages; calls LLMEditAgent; returns proposal
    async def send_message(session_id: str, message: str) -> GraphMutationProposal
    # Creates checkpoint, applies Cypher mutations, re-links, re-visualizes
    async def apply_mutations(session_id: str, mutations: GraphMutation) -> IngestionStats
    # No-op on Neo4j; just logs rejection in session_messages
    async def reject_mutations(session_id: str) -> None
    # Loads full message history from SQLite for a session
    async def get_session_history(session_id: str) -> list[EditSessionMessage]

class CheckpointService:
    # Serializes Neo4j subgraph to JSON, writes row to graph_snapshots in SQLite
    async def create_checkpoint(entity_type: str, entity_id: str, session_id: str, label: str) -> GraphVersion
    # Reads from graph_snapshots SQLite table
    async def list_versions(entity_type: str, entity_id: str) -> list[GraphVersion]
    # Reads snapshot from SQLite, restores to Neo4j
    async def rollback(entity_type: str, entity_id: str, version_id: str) -> None

class LLMEditAgent:
    # Loads history from SQLite, builds Groq messages array, returns structured proposal
    async def get_next_question(session_id: str, user_message: str) -> GraphMutationProposal
```

---

## New Frontend Components

### `frontend/src/pages/user/EditGraph.jsx`

- Split layout: `<GraphViewer>` left + `<ChatPanel>` right.
- Top bar: "Save Checkpoint" button + version rollback dropdown.
- `<SkillGapPanel>` below graph (collapsible).

### `frontend/src/components/ChatPanel.jsx`

- Message history display (user + assistant turns).
- Text input + Send button.
- Shows `GraphMutationProposal` as an inline diff card with Accept / Reject buttons.

### `frontend/src/components/SuggestionPanel.jsx`

- Shows pending LLM-proposed mutations in structured form (add/update/remove lists).
- Per-mutation accept/reject toggles.
- "Apply selected" CTA.

### `frontend/src/components/VersionHistory.jsx`

- Dropdown or side drawer listing `GraphVersion` snapshots.
- Clicking a version shows its timestamp + label.
- "Rollback" button with confirmation modal.

---

## API Endpoints (new)

```
POST /api/v1/users/{user_id}/graph/edit/start
  Response: { session_id, opening_question, graph_summary }

POST /api/v1/users/{user_id}/graph/edit/message
  Body: { session_id, message }
  Response: GraphMutationProposal

POST /api/v1/users/{user_id}/graph/edit/apply
  Body: { session_id, mutations: GraphMutation }
  Response: { stats: IngestionStats, version_id }

POST /api/v1/users/{user_id}/graph/edit/reject
  Body: { session_id }
  Response: { follow_up_question }

GET  /api/v1/users/{user_id}/graph/versions
  Response: list[GraphVersion]

POST /api/v1/users/{user_id}/graph/rollback/{version_id}
  Response: { stats: IngestionStats }

# Same pattern for jobs:
POST /api/v1/jobs/{job_id}/graph/edit/start
POST /api/v1/jobs/{job_id}/graph/edit/message
POST /api/v1/jobs/{job_id}/graph/edit/apply
POST /api/v1/jobs/{job_id}/graph/rollback/{version_id}
GET  /api/v1/jobs/{job_id}/graph/versions
```

---

## Data Model Changes

### SQLite (new — `.data_storage/lumino.db`)

Three tables: `edit_sessions`, `session_messages`, `graph_snapshots` — see schema in Section 4 above.

Add `aiosqlite` to `requirements.txt`.

### Neo4j changes

```cypher
// Weight property on Skill + Domain nodes (added during ingestion and edit)
// No schema change needed — Neo4j is schemaless; just SET n.weight = value

// Provenance tagging: source='user_edit' (vs existing source='llm')
// No schema change needed
```

No new Neo4j node labels or constraints needed. `GraphVersion` is removed from Neo4j entirely — it lives in SQLite.

---

## Acceptance Criteria

- [ ] "Edit Graph" button visible on UserModel page; navigates to edit page.
- [ ] Edit page loads with current graph visualization + chat panel.
- [ ] LLM opens with a First Principles question about the user's weakest/least-evidenced skill area.
- [ ] Each LLM response includes a structured mutation proposal shown as a diff.
- [ ] User can accept or reject proposed mutations individually.
- [ ] On accept: graph updates in Neo4j and visualization re-renders within 3 seconds.
- [ ] A checkpoint is saved before every accepted mutation batch.
- [ ] User can list and rollback to any of the last 10 checkpoints.
- [ ] Skill nodes display size proportional to their expertise weight.
- [ ] Missing skills (vs. a selected job) are shown as orange badges; clicking one pre-fills the chat.
- [ ] Recruiter can edit job model graph via the same pattern from JobModel page.
- [ ] All new nodes written with `source='user_edit'` provenance tag.

---

## Implementation Order

1. **Backend**: `SQLiteClient` + schema init wired into FastAPI startup.
2. **Backend**: `CheckpointService` + `/versions` + `/rollback` endpoints (reads/writes SQLite, no LLM dependency).
3. **Backend**: Node weight computation in `LLMIngestionService`.
4. **Backend**: `LLMEditAgent` + `GraphEditService` + edit endpoints (session messages persisted to SQLite).
5. **Frontend**: `EditGraph.jsx` skeleton + `ChatPanel.jsx`.
6. **Frontend**: `SuggestionPanel.jsx` with accept/reject.
7. **Frontend**: `VersionHistory.jsx` rollback UI.
8. **Frontend**: `SkillGapPanel` on edit page.
9. **Integration**: Wire edit button on `UserModel.jsx` + `JobModel.jsx`.

---

## Decisions

| Question | Decision |
|----------|----------|
| Where to store snapshots + session history? | SQLite (`.data_storage/lumino.db`) — avoids Neo4j 1MB limit, keeps transient data separate |
| LLM session persistence | Sessions survive page refreshes; history loaded from SQLite on re-open |
| Max turn count per session? | None — open-ended conversation |
| Recruiter job ownership | Recruiters can only edit jobs tagged with their `recruiter_id`; enforced in `GraphEditService.start_session` |
