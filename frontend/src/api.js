const UPLOAD_POST_URL = import.meta.env.VITE_UPLOAD_POST_URL || 'http://localhost:5014'
const SCAN_DRAFT_URL = import.meta.env.VITE_SCAN_DRAFT_URL || 'http://localhost:5012'
const DETECTIONS_URL = import.meta.env.VITE_DETECTIONS_URL || 'http://localhost:5003'
const REMEDIATE_CONTENT_URL = import.meta.env.VITE_REMEDIATE_CONTENT_URL || 'http://localhost:5011'
const QUARANTINE_HIGH_RISK_URL = import.meta.env.VITE_QUARANTINE_HIGH_RISK_URL || 'http://localhost:5010'

async function parseOrThrow(res) {
  const data = await res.json()
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`)
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
  for (let attempt = 0; ; attempt++) {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), attemptTimeoutMs)
    try {
      return await fetch(url, { ...options, signal: controller.signal })
    } catch (err) {
      if (attempt >= retries) throw err
      onRetry?.(attempt + 1, retries)
      await new Promise((resolve) => setTimeout(resolve, delayMs))
    } finally {
      clearTimeout(timer)
    }
  }
}

export async function uploadPost({ ownerId, contentType, sourceApp, caption, photoFile }, onRetry) {
  const form = new FormData()
  form.append('owner_id', ownerId)
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

export async function confirmRemediation(draftId) {
  const res = await fetchWithRetry(`${REMEDIATE_CONTENT_URL}/drafts/${draftId}/remediate/confirm`, { method: 'POST' })
  return parseOrThrow(res)
}

export function downloadUrl(draftId) {
  return `${REMEDIATE_CONTENT_URL}/drafts/${draftId}/download`
}

export async function revertEdit(editId) {
  const res = await fetchWithRetry(`${REMEDIATE_CONTENT_URL}/edits/${editId}/revert`, { method: 'POST' })
  return parseOrThrow(res)
}

export async function restoreEdit(editId) {
  const res = await fetchWithRetry(`${REMEDIATE_CONTENT_URL}/edits/${editId}/restore`, { method: 'POST' })
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

