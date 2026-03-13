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

  // Admin — delete
  deleteUser: (userId) => del(`/users/${userId}`),
  deleteJob:  (jobId)  => del(`/jobs/${jobId}`),
}
