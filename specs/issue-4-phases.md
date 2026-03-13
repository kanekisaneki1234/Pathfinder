# Implementation Plan: Issue #4 — Edit User Profile & Job Model Graphs

This document breaks the work into four self-contained phases. Each phase ends with a working, mergeable state. Phases build on each other but never leave the app in a broken state mid-phase.

---

## Phase 1 — SQLite Foundation & Checkpointing

**Goal**: Introduce SQLite, wire it into startup, and ship a working snapshot/rollback system independent of any UI or LLM changes. Proves the persistence layer before anything else touches it.

### Backend tasks

- [ ] Add `aiosqlite` to `requirements.txt`
- [ ] Create `database/sqlite_client.py`
  - `SQLiteClient` class with `init_schema()`, `execute()`, `fetchall()`, `fetchone()`
  - DB path from env var `SQLITE_DB_PATH`, default `.data_storage/lumino.db`
- [ ] Create the three tables in `init_schema()`:
  - `edit_sessions`
  - `session_messages`
  - `graph_snapshots`
- [ ] Wire `SQLiteClient.init_schema()` into FastAPI startup in `main.py` alongside Neo4j constraint init
- [ ] Create `services/checkpoint_service.py`
  - `create_checkpoint(entity_type, entity_id, session_id, label)` — serializes full Neo4j subgraph to JSON, writes to `graph_snapshots`
  - `list_versions(entity_type, entity_id)` — reads from SQLite, returns last 10, ordered by `created_at DESC`
  - `rollback(entity_type, entity_id, version_id)` — loads snapshot from SQLite, `DETACH DELETE` entity subgraph in Neo4j, re-inserts nodes + edges, re-runs match linking, re-generates visualization
- [ ] Add Pydantic models to `models/schemas.py`:
  - `GraphVersion`, `GraphSnapshotResponse`
- [ ] Add API routes to `api/routes.py`:
  - `GET  /api/v1/users/{user_id}/graph/versions`
  - `POST /api/v1/users/{user_id}/graph/rollback/{version_id}`
  - `GET  /api/v1/jobs/{job_id}/graph/versions`
  - `POST /api/v1/jobs/{job_id}/graph/rollback/{version_id}`
  - `POST /api/v1/users/{user_id}/graph/checkpoint` (manual save)
  - `POST /api/v1/jobs/{job_id}/graph/checkpoint` (manual save)

### Deliverable
- SQLite initializes on startup with no errors.
- Can `POST /checkpoint` after ingestion and get a `version_id` back.
- Can `GET /versions` and see the list.
- Can `POST /rollback/{version_id}` and have the Neo4j graph restored correctly.

---

## Phase 2 — Node Expertise Weights

**Goal**: Compute and store `weight` on `Skill` and `Domain` nodes. Update visualization to reflect weights as node size. No new pages needed — purely a backend + visualization enhancement visible on the existing `UserModel` page.

### Backend tasks

- [ ] Add weight computation helper in `utils/helpers.py`:
  ```
  weight = clamp(
    years_experience * 0.4 +
    num_projects_demonstrating * 0.3 +
    level_mapping[level] * 0.3
  , 0.0, 1.0)
  ```
  where `level_mapping = {beginner: 0.2, intermediate: 0.6, advanced: 1.0}`
- [ ] Update `services/llm_ingestion.py`:
  - After writing `Skill` nodes, query count of `DEMONSTRATES_SKILL` edges and compute + `SET n.weight`
  - Same for `Domain` nodes using `HAS_DOMAIN` edge count as proxy
- [ ] Update `services/graph_edit_service.py` (Phase 3 will create this file, but weight recompute logic can be a standalone function called by both ingestion and edit apply)
  - Extract `recompute_weights(user_id)` as a standalone async function in `services/weights.py`

### Visualization tasks

- [ ] Update `services/visualization.py` `generate_user_graph()`:
  - Read `n.weight` for `Skill` and `Domain` nodes
  - Map weight (0.0–1.0) → pyvis node size (10–40)
  - Add weight to node tooltip: `"React | 4 yrs | advanced | weight: 0.82"`

### Deliverable
- Re-ingesting a profile shows variable-size nodes in the graph.
- Tooltip shows weight breakdown.
- Existing graph API and matching are unaffected.

---

## Phase 3 — LLM Edit Agent & Backend Edit Endpoints

**Goal**: Ship the full backend edit flow — sessions, First Principles chat, mutation proposals, apply/reject — all backed by SQLite. No frontend yet; testable via API directly (curl / Postman).

### Backend tasks

- [ ] Add Pydantic models to `models/schemas.py`:
  - `GraphMutation` (add_nodes, update_nodes, remove_nodes, add_edges)
  - `GraphMutationProposal` (reasoning, mutations, follow_up_question)
  - `EditSessionMessage` (role, content, proposal)
  - `EditSessionResponse` (session_id, opening_question, graph_summary)
- [ ] Create `services/llm_edit_agent.py`
  - `LLMEditAgent.get_next_question(session_id, user_message)`:
    1. Load message history from SQLite `session_messages`
    2. Load current graph summary from Neo4j (node counts by category + weakest skill by years)
    3. Build Groq messages array: system prompt + history + new user message
    4. System prompt instructs: First Principles mode, output `GraphMutationProposal` JSON schema
    5. Call Groq with `response_model=GraphMutationProposal` (structured output)
    6. Return proposal
- [ ] Create `services/graph_edit_service.py`
  - `start_session(entity_type, entity_id, recruiter_id)`:
    - For job sessions: verify `recruiter_id` owns `job_id` (query Neo4j `Job.recruiter_id`); raise 403 if not
    - Insert row into `edit_sessions`
    - Load graph summary, call `LLMEditAgent` with empty history for opening question
    - Return `EditSessionResponse`
  - `send_message(session_id, message)`:
    - Append user message to `session_messages`
    - Call `LLMEditAgent.get_next_question()`
    - Append assistant message + proposal JSON to `session_messages`
    - Return `GraphMutationProposal`
  - `apply_mutations(session_id, mutations)`:
    - Create checkpoint via `CheckpointService` (auto-snapshot before change)
    - Run Cypher: `MERGE` new nodes (`source='user_edit'`), `SET` updates, `DETACH DELETE` removals, `MERGE` new edges
    - Re-run `link_skill_matches()` / `link_domain_matches()`
    - Re-run `recompute_weights(entity_id)`
    - Re-generate visualization
    - Return `IngestionStats`
  - `reject_mutations(session_id)`:
    - Log rejection event in `session_messages` (role='system', content='mutations_rejected')
    - Return next follow-up question from LLM
  - `get_session_history(session_id)` → list of `EditSessionMessage`
- [ ] Add API routes to `api/routes.py`:
  - `POST /api/v1/users/{user_id}/graph/edit/start`
  - `POST /api/v1/users/{user_id}/graph/edit/message`
  - `POST /api/v1/users/{user_id}/graph/edit/apply`
  - `POST /api/v1/users/{user_id}/graph/edit/reject`
  - `GET  /api/v1/users/{user_id}/graph/edit/history?session_id=`
  - `POST /api/v1/jobs/{job_id}/graph/edit/start`
  - `POST /api/v1/jobs/{job_id}/graph/edit/message`
  - `POST /api/v1/jobs/{job_id}/graph/edit/apply`
  - `POST /api/v1/jobs/{job_id}/graph/edit/reject`

### Deliverable
- `POST /graph/edit/start` returns a session ID and an opening First Principles question.
- Multi-turn chat produces `GraphMutationProposal` objects with structured mutations.
- `POST /apply` modifies the Neo4j graph, auto-checkpoints, re-visualizes.
- `POST /reject` returns a follow-up question without touching the graph.
- Session history persists across restarts.

---

## Phase 4 — Frontend Edit UI

**Goal**: Build the edit pages and connect them to the Phase 3 endpoints. Users can chat, see mutation diffs, accept/reject, view version history, and roll back — all from the browser.

### Frontend tasks

#### New pages

- [ ] `frontend/src/pages/user/EditGraph.jsx`
  - Split layout: graph iframe left (60%), chat panel right (40%)
  - Top bar: "Save Checkpoint" button + `<VersionHistory>` dropdown
  - Collapsible `<SkillGapPanel>` below graph (only shown when navigated from a job match)
  - On mount: call `POST /graph/edit/start`, store `session_id` in component state
  - On unmount / page close: no cleanup needed (session persists in SQLite)

- [ ] `frontend/src/pages/recruiter/EditJobGraph.jsx`
  - Same layout as `EditGraph.jsx`, bound to `job_id` from route params
  - Uses job edit endpoints

#### New components

- [ ] `frontend/src/components/ChatPanel.jsx`
  - Scrollable message history (user bubbles right, assistant bubbles left)
  - Shows assistant messages with an embedded `<MutationDiffCard>` when `proposal` is present
  - Text input + Send button; disabled while awaiting response
  - On send: `POST /graph/edit/message` → appends response to history

- [ ] `frontend/src/components/MutationDiffCard.jsx`
  - Shows three sections: "Add", "Update", "Remove" as collapsible lists
  - Each item has an individual Accept / Reject checkbox
  - "Apply selected" button → calls `POST /graph/edit/apply` with checked mutations
  - "Reject all" button → calls `POST /graph/edit/reject`
  - On apply success: triggers graph iframe reload

- [ ] `frontend/src/components/VersionHistory.jsx`
  - Fetches `GET /graph/versions` on open
  - Lists versions as: `<timestamp> — <label>` (max 10)
  - "Rollback" button on each row → confirmation modal → `POST /rollback/{version_id}` → graph reload

- [ ] `frontend/src/components/SkillGapPanel.jsx`
  - Receives `job_id` as prop (passed from Dashboard navigation state)
  - Fetches `GET /users/{user_id}/matches/{job_id}`
  - Renders matched skills as green `<SkillBadge>` and missing as orange
  - Clicking missing skill calls `ChatPanel`'s pre-seed function with: `"Tell me about your experience with {skill}"`

#### API client additions (`frontend/src/lib/api.js`)

- [ ] `api.startEditSession(entityType, entityId)`
- [ ] `api.sendEditMessage(entityType, entityId, sessionId, message)`
- [ ] `api.applyMutations(entityType, entityId, sessionId, mutations)`
- [ ] `api.rejectMutations(entityType, entityId, sessionId)`
- [ ] `api.getEditHistory(entityType, entityId, sessionId)`
- [ ] `api.listVersions(entityType, entityId)`
- [ ] `api.rollback(entityType, entityId, versionId)`
- [ ] `api.saveCheckpoint(entityType, entityId)`

#### Routing & integration

- [ ] Add route `/user/edit-graph` → `EditGraph.jsx` in `App.jsx`
- [ ] Add route `/recruiter/edit-job/:jobId` → `EditJobGraph.jsx` in `App.jsx`
- [ ] Add "Edit Graph" button to `UserModel.jsx` → navigates to `/user/edit-graph`
- [ ] Add "Edit Graph" button to `JobModel.jsx` → navigates to `/recruiter/edit-job/:jobId`
- [ ] Both navigation calls pass `job_id` in router state when coming from `MatchExplorer` (for SkillGapPanel)

### Deliverable
- Full end-to-end edit flow works in the browser.
- All acceptance criteria from the spec are met.
- No regressions on existing Upload, UserModel, Dashboard, MatchExplorer pages.

---

## Phase Summary

| Phase | Scope | Depends on |
|-------|-------|-----------|
| 1 | SQLite client + checkpointing endpoints | Nothing |
| 2 | Node weights + visualization update | Nothing (can run parallel to Phase 1) |
| 3 | LLM edit agent + backend edit endpoints | Phase 1 (SQLite), Phase 2 (weights recompute) |
| 4 | Frontend edit UI | Phase 3 (all endpoints) |
