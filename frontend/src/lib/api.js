const BASE = '/api/v1'

async function get(path) {
  const res = await fetch(BASE + path)
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(detail.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

async function post(path, body) {
  const res = await fetch(BASE + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(detail.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

async function del(path) {
  const res = await fetch(BASE + path, { method: 'DELETE' })
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(detail.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

async function postForm(path, formData) {
  const res = await fetch(BASE + path, {
    method: 'POST',
    body: formData,
  })
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(detail.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

export const api = {
  // Ingestion — text
  ingestUser:       (userId, profileText)             => post('/users/ingest', { user_id: userId, profile_text: profileText }),
  ingestJob:        (jobId, jobText, recruiterId)     => post('/jobs/ingest',  { job_id: jobId, job_text: jobText, recruiter_id: recruiterId }),

  // Ingestion — PDF (multipart)
  uploadUserPdf(userId, file) {
    const fd = new FormData()
    fd.append('user_id', userId)
    fd.append('file', file)
    return postForm('/users/upload', fd)
  },
  uploadJobPdf(jobId, file, recruiterId) {
    const fd = new FormData()
    fd.append('job_id', jobId)
    fd.append('file', file)
    if (recruiterId) fd.append('recruiter_id', recruiterId)
    return postForm('/jobs/upload', fd)
  },

  // Listings
  listJobs:         (recruiterId)          => get(`/jobs${recruiterId ? `?recruiter_id=${recruiterId}` : ''}`),
  listUsers:        ()                     => get('/users'),

  // Matching
  getMatches:       (userId)               => get(`/users/${userId}/matches`),
  getCandidates:    (jobId)                => get(`/jobs/${jobId}/matches`),
  getMatchDetail:   (userId, jobId)        => get(`/users/${userId}/matches/${jobId}`),
  getMatchPaths:    (userId, jobId, limit) => get(`/users/${userId}/matches/${jobId}/paths${limit ? `?limit=${limit}` : ''}`),
  explainMatch:     (userId, jobId, perspective) => post(`/users/${userId}/matches/${jobId}/explain?perspective=${perspective || 'recruiter'}`, {}),

  // Visualization (POST generates, GET url used in iframe src)
  generateUserViz:  (userId)               => post(`/users/${userId}/visualize`),
  generateJobViz:   (jobId)                => post(`/jobs/${jobId}/visualize`),
  generateMatchViz: (userId, jobId)        => post(`/users/${userId}/matches/${jobId}/visualize`),

  // Iframe src URLs (relative — proxied by Vite)
  userVizUrl:       (userId)               => `${BASE}/users/${userId}/visualize`,
  jobVizUrl:        (jobId)                => `${BASE}/jobs/${jobId}/visualize`,
  matchVizUrl:      (userId, jobId)        => `${BASE}/users/${userId}/matches/${jobId}/visualize`,

  // Stats
  getUserStats:     (userId)               => get(`/users/${userId}/graph-stats`),

  // Clarification / Digital Twin Verification
  getClarifications:  (userId)             => get(`/users/${userId}/clarifications`),
  resolveFlag: (userId, flagId, isCorrect, userAnswer, correction) =>
    post(`/users/${userId}/clarifications/${flagId}/resolve`, {
      is_correct: isCorrect,
      user_answer: userAnswer,
      correction: correction || null,
    }),
  skipFlag: (userId, flagId) => post(`/users/${userId}/clarifications/${flagId}/skip`, {}),
  interpretFlag: (userId, flagId, answer) =>
    post(`/users/${userId}/clarifications/${flagId}/interpret`, { answer }),
  describeUser: (userId) => get(`/users/${userId}/describe`),

  // Admin — delete
  deleteUser: (userId) => del(`/users/${userId}`),
  deleteJob:  (jobId)  => del(`/jobs/${jobId}`),

  // Graph editing — sessions
  startEditSession: (entityType, entityId, recruiterId) => {
    const base = entityType === 'user' ? `/users/${entityId}` : `/jobs/${entityId}`
    return post(`${base}/graph/edit/start`, recruiterId ? { recruiter_id: recruiterId } : {})
  },
  sendEditMessage: (entityType, entityId, sessionId, message) => {
    const base = entityType === 'user' ? `/users/${entityId}` : `/jobs/${entityId}`
    return post(`${base}/graph/edit/message`, { session_id: sessionId, message })
  },
  applyMutations: (entityType, entityId, sessionId, mutations) => {
    const base = entityType === 'user' ? `/users/${entityId}` : `/jobs/${entityId}`
    return post(`${base}/graph/edit/apply`, { session_id: sessionId, mutations })
  },
  rejectMutations: (entityType, entityId, sessionId) => {
    const base = entityType === 'user' ? `/users/${entityId}` : `/jobs/${entityId}`
    return post(`${base}/graph/edit/reject`, { session_id: sessionId })
  },
  getEditHistory: (entityType, entityId, sessionId) => {
    const base = entityType === 'user' ? `/users/${entityId}` : `/jobs/${entityId}`
    return get(`${base}/graph/edit/history?session_id=${sessionId}`)
  },

  // Graph versioning
  listVersions: (entityType, entityId) => {
    const base = entityType === 'user' ? `/users/${entityId}` : `/jobs/${entityId}`
    return get(`${base}/graph/versions`)
  },
  rollback: (entityType, entityId, versionId) => {
    const base = entityType === 'user' ? `/users/${entityId}` : `/jobs/${entityId}`
    return post(`${base}/graph/rollback/${versionId}`, {})
  },
  saveCheckpoint: (entityType, entityId, label) => {
    const base = entityType === 'user' ? `/users/${entityId}` : `/jobs/${entityId}`
    return post(`${base}/graph/checkpoint`, { label: label || 'manual' })
  },
}
