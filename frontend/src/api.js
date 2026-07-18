const UPLOAD_POST_URL = import.meta.env.VITE_UPLOAD_POST_URL || 'http://localhost:5014'
const SCAN_DRAFT_URL = import.meta.env.VITE_SCAN_DRAFT_URL || 'http://localhost:5012'
const DETECTIONS_URL = import.meta.env.VITE_DETECTIONS_URL || 'http://localhost:5003'
const EDITS_URL = import.meta.env.VITE_EDITS_URL || 'http://localhost:5004'
const REMEDIATE_CONTENT_URL = import.meta.env.VITE_REMEDIATE_CONTENT_URL || 'http://localhost:5011'
const QUARANTINE_HIGH_RISK_URL = import.meta.env.VITE_QUARANTINE_HIGH_RISK_URL || 'http://localhost:5010'
const GENERATE_TEACHABLE_MOMENT_URL = import.meta.env.VITE_GENERATE_TEACHABLE_MOMENT_URL || 'http://localhost:5009'
const USERS_URL = import.meta.env.VITE_USERS_URL || 'http://localhost:5001'
const MANAGE_HISTORY_URL = import.meta.env.VITE_MANAGE_HISTORY_URL || 'http://localhost:5015'

// sessionStorage (not localStorage) so the token disappears when the tab
// closes, rather than lingering on the device indefinitely — the closest
// realistic match to "session" for a login that spans several backend
// services on different origins, where a real browser cookie set by one of
// them wouldn't be sent to the others anyway.
const TOKEN_KEY = 'trace_token'

export function getToken() {
  return sessionStorage.getItem(TOKEN_KEY)
}

export function setToken(token) {
  sessionStorage.setItem(TOKEN_KEY, token)
}

export function clearToken() {
  sessionStorage.removeItem(TOKEN_KEY)
}

function authHeaders() {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function parseOrThrow(res) {
  const data = await res.json()
  if (!res.ok) {
    // A stale/expired/garbage token reads the same everywhere: drop it so
    // the app falls back to the login screen instead of repeating the same
    // failed call.
    if (res.status === 401) clearToken()
    throw new Error(data.error || `Request failed (${res.status})`)
  }
  return data
}

// Render's free tier spins services down after 15 min idle. The first request
// back can fail at the network level (connection reset) while the container
// is still booting, rather than just being slow — so we retry on fetch()
// throwing, not on ordinary HTTP error responses. Each attempt gets its own
// bounded timeout (rather than trusting the browser's own, much longer and
// less predictable default) so a stalled cold-starting request doesn't just
// hang — we abort it and retry sooner instead.
async function fetchWithRetry(url, options, { retries = 6, attemptTimeoutMs = 12000, delayMs = 4000, onRetry } = {}) {
  // Every call goes through here, so this is the one place the token needs
  // to be attached rather than at each of the many call sites below.
  const mergedOptions = { ...options, headers: { ...authHeaders(), ...options?.headers } }
  for (let attempt = 0; ; attempt++) {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), attemptTimeoutMs)
    try {
      return await fetch(url, { ...mergedOptions, signal: controller.signal })
    } catch (err) {
      if (attempt >= retries) throw err
      onRetry?.(attempt + 1, retries)
      await new Promise((resolve) => setTimeout(resolve, delayMs))
    } finally {
      clearTimeout(timer)
    }
  }
}

export async function login(email, password) {
  const res = await fetchWithRetry(`${USERS_URL}/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })
  const data = await parseOrThrow(res)
  setToken(data.token)
  return data.user
}

export async function signup(email, password) {
  const res = await fetchWithRetry(`${USERS_URL}/signup`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })
  const data = await parseOrThrow(res)
  setToken(data.token)
  return data.user
}

export async function logout() {
  try {
    await fetchWithRetry(`${USERS_URL}/logout`, { method: 'POST' })
  } finally {
    // The token is discarded either way — logging out is meant to work even
    // if the server call itself fails (e.g. already-expired token).
    clearToken()
  }
}

// owner_id is no longer sent — upload_post derives it from the caller's own
// token now, so a client can't create a draft under someone else's identity
// just by naming a different id.
export async function uploadPost({ contentType, sourceApp, caption, photoFile }, onRetry) {
  const form = new FormData()
  form.append('content_type', contentType)
  if (sourceApp) form.append('source_app', sourceApp)
  if (caption) form.append('text_content', caption)
  if (photoFile) form.append('file', photoFile)

  const res = await fetchWithRetry(`${UPLOAD_POST_URL}/drafts`, { method: 'POST', body: form }, { onRetry })
  return parseOrThrow(res)
}

export async function processDraft(draftId, onRetry) {
  const res = await fetchWithRetry(`${SCAN_DRAFT_URL}/drafts/${draftId}/process`, { method: 'POST' }, { onRetry })
  return parseOrThrow(res)
}

export async function getDetections(draftId, onRetry) {
  const res = await fetchWithRetry(`${DETECTIONS_URL}/drafts/${draftId}/detections`, undefined, { onRetry })
  return parseOrThrow(res)
}

export async function getTeachableMoment(draftId, onRetry) {
  const res = await fetchWithRetry(`${GENERATE_TEACHABLE_MOMENT_URL}/drafts/${draftId}/teachable-moment`, {
    method: 'POST',
  }, { onRetry })
  return parseOrThrow(res)
}

export async function confirmRemediation(draftId) {
  const res = await fetchWithRetry(`${REMEDIATE_CONTENT_URL}/drafts/${draftId}/remediate/confirm`, { method: 'POST' })
  return parseOrThrow(res)
}

// Re-fetches (or, the first time, re-derives) the proposed edits for a
// draft that was already scanned — how a "Pending" post in History resumes
// the clean-up screen. Safe to call again on an already-proposed draft:
// remediate_content's propose step matches by detection_id, so this just
// returns the existing proposal instead of creating duplicate edits.
export async function resumeRemediation(draftId) {
  const res = await fetchWithRetry(`${REMEDIATE_CONTENT_URL}/drafts/${draftId}/remediate`, { method: 'POST' })
  return parseOrThrow(res)
}

// The user's "no, don't post this" — marks the draft rejected instead of
// leaving it stuck pending forever if they just navigate away.
export async function cancelRemediation(draftId) {
  const res = await fetchWithRetry(`${REMEDIATE_CONTENT_URL}/drafts/${draftId}/remediate/cancel`, { method: 'POST' })
  return parseOrThrow(res)
}

export function downloadUrl(draftId) {
  return `${REMEDIATE_CONTENT_URL}/drafts/${draftId}/download`
}

// The download route is behind the same auth gate as everything else now,
// so it can no longer be fetched with a bare, unauthenticated fetch() —
// this wraps it the same way every other call in this file already is.
export async function downloadRemediated(draftId) {
  const res = await fetchWithRetry(downloadUrl(draftId), undefined)
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.error || `Request failed (${res.status})`)
  }
  return res.blob()
}

export async function revertEdit(editId) {
  const res = await fetchWithRetry(`${REMEDIATE_CONTENT_URL}/edits/${editId}/revert`, { method: 'POST' })
  return parseOrThrow(res)
}

export async function restoreEdit(editId) {
  const res = await fetchWithRetry(`${REMEDIATE_CONTENT_URL}/edits/${editId}/restore`, { method: 'POST' })
  return parseOrThrow(res)
}

// Talks to the edits atomic service directly (same pattern as getDetections
// talking directly to the detections atomic service) rather than through
// remediate_content — a region edit only needs to be correct by the time
// /remediate/confirm reads pending edits, it doesn't need to trigger a
// re-render itself the way revert does.
export async function updateEditRegion(editId, region) {
  const res = await fetchWithRetry(`${EDITS_URL}/edits/${editId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ region_affected: region }),
  })
  return parseOrThrow(res)
}

// For a spot the scanner missed entirely: records a Detection (so there's
// still an audit trail of what got flagged and why, same as every
// scanner-found one, just with model_version "manual") and then an Edit
// pointing at the same region and detection_id, mirroring exactly what
// remediate_content's propose step already does per-detection — just
// triggered from the frontend instead of a scanner.
export async function addManualEdit(draftId, region) {
  const detection = await parseOrThrow(
    await fetchWithRetry(`${DETECTIONS_URL}/detections`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        draft_id: draftId,
        category: 'document',
        source_type: 'image',
        exposure_score: 3,
        model_version: 'manual',
        bounding_region: region,
      }),
    })
  )

  const res = await fetchWithRetry(`${EDITS_URL}/edits`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      draft_id: draftId,
      edit_type: 'blur',
      region_affected: region,
      detection_id: detection.detection_id,
    }),
  })
  return parseOrThrow(res)
}

// Renames a self-marked area by updating the underlying Detection's detail
// (the one-line description RemediationView shows next to its checkbox).
export async function renameDetection(detectionId, detail) {
  const res = await fetchWithRetry(`${DETECTIONS_URL}/detections/${detectionId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ detail }),
  })
  return parseOrThrow(res)
}

// quarantine_high_risk has no standalone /quarantine/<id>/cooldown route — that
// lives on the atomic quarantine_items service. The composite-level way to poll
// cooldown status is this drafts-scoped list, which comes back pre-enriched.
export async function getQuarantineForDraft(draftId) {
  const res = await fetchWithRetry(`${QUARANTINE_HIGH_RISK_URL}/drafts/${draftId}/quarantine`)
  return parseOrThrow(res)
}

export async function releaseQuarantine(quarantineId) {
  const res = await fetchWithRetry(`${QUARANTINE_HIGH_RISK_URL}/quarantine/${quarantineId}/release`, { method: 'POST' })
  return parseOrThrow(res)
}

export async function editQuarantine(quarantineId) {
  const res = await fetchWithRetry(`${QUARANTINE_HIGH_RISK_URL}/quarantine/${quarantineId}/edit`, { method: 'POST' })
  return parseOrThrow(res)
}

export async function deleteQuarantine(quarantineId) {
  const res = await fetchWithRetry(`${QUARANTINE_HIGH_RISK_URL}/quarantine/${quarantineId}/delete`, { method: 'POST' })
  return parseOrThrow(res)
}

export async function getMe() {
  const res = await fetchWithRetry(`${USERS_URL}/me`)
  return parseOrThrow(res)
}

export async function updateRetentionMode(userId, retentionMode) {
  const res = await fetchWithRetry(`${USERS_URL}/users/${userId}/settings`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ retention_mode: retentionMode }),
  })
  return parseOrThrow(res)
}

// One card per post — filter is 'all' | 'accepted' | 'rejected' | 'quarantined'.
export async function getHistory(filter = 'all', onRetry) {
  const res = await fetchWithRetry(`${MANAGE_HISTORY_URL}/history?filter=${filter}`, undefined, { onRetry })
  return parseOrThrow(res)
}

// A mixed batch of whatever's currently selected/checked in the History
// screen — "select all" is just the frontend sending every currently-visible
// id. The History screen operates at whole-post granularity, so this is
// almost always called with draftIds; detectionIds/quarantineIds exist for
// finer-grained deletes the composite already supports.
export async function deleteHistoryItems({ draftIds = [], detectionIds = [], quarantineIds = [] }) {
  const res = await fetchWithRetry(`${MANAGE_HISTORY_URL}/history/delete`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      draft_ids: draftIds,
      detection_ids: detectionIds,
      quarantine_ids: quarantineIds,
    }),
  })
  return parseOrThrow(res)
}

// The History screen's per-card thumbnail. upload_post's /original route is
// behind the same auth gate as everything else, so — same reasoning as
// downloadRemediated — this can't just be a plain <img src>; it has to be a
// real fetch with the token attached, turned into a local blob URL.
export async function getDraftThumbnail(draftId) {
  const res = await fetchWithRetry(`${UPLOAD_POST_URL}/drafts/${draftId}/original`)
  if (!res.ok) return null
  return URL.createObjectURL(await res.blob())
}
