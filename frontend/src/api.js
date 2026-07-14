const UPLOAD_POST_URL = 'http://localhost:5014'
const SCAN_DRAFT_URL = 'http://localhost:5012'

async function parseOrThrow(res) {
  const data = await res.json()
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`)
  return data
}

export async function uploadPost({ ownerId, contentType, sourceApp, caption, photoFile }) {
  const form = new FormData()
  form.append('owner_id', ownerId)
  form.append('content_type', contentType)
  if (sourceApp) form.append('source_app', sourceApp)
  if (caption) form.append('text_content', caption)
  if (photoFile) form.append('file', photoFile)

  const res = await fetch(`${UPLOAD_POST_URL}/drafts`, { method: 'POST', body: form })
  return parseOrThrow(res)
}

export async function processDraft(draftId) {
  const res = await fetch(`${SCAN_DRAFT_URL}/drafts/${draftId}/process`, { method: 'POST' })
  return parseOrThrow(res)
}
