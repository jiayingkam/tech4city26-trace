<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import {
  confirmRemediation,
  cancelRemediation,
  revertEdit,
  restoreEdit,
  downloadRemediated,
  updateEditRegion,
  addManualEdit,
  addManualFaceEdit,
  deleteEdit,
  renameDetection,
  sendTeachableMomentChat,
  saveCleanedCaption,
} from '../api'
import TeachableChatPanel from '../components/TeachableChatPanel.vue'

const props = defineProps({
  draftId: { type: String, required: true },
  remediation: { type: Object, required: true },
  photoUrl: { type: String, default: null },
  detections: { type: Array, default: () => [] },
  teachableMoment: { type: Object, default: null },
})
const emit = defineEmits(['restart'])

const proposedEdits = ref(
  (props.remediation.proposed_edits || [])
    .map((e) => ({ ...e }))
    .sort((a, b) => {
      const aManual = props.detections.find((d) => d.detection_id === a.detection_id)?.model_version === 'manual'
      const bManual = props.detections.find((d) => d.detection_id === b.detection_id)?.model_version === 'manual'
      return aManual === bManual ? 0 : aManual ? 1 : -1
    })
)
const redaction = props.remediation.text_redaction

// Edits don't carry their own description of what they're for (just a
// region and a type) — this looks up each edit's own detail via its
// detection_id, the real link the backend now stores (remediate_content's
// propose step sets it, and addManualEdit's created edit carries the
// detection it was made for). reactive (not a plain object) because
// renaming a self-marked area below overwrites an entry after mount and
// editLabel needs to pick that up.
const detailByEditId = reactive({})
for (const edit of proposedEdits.value) {
  const match = props.detections.find((d) => d.detection_id === edit.detection_id)
  if (match?.detail) detailByEditId[edit.edit_id] = match.detail
}

// Renaming only makes sense for self-marked areas (see addManualEdit) —
// scanner-found ones already have a detail from the scan itself. Every edit
// now carries a detection_id either way, so this can't just check for its
// presence — it checks the underlying detection's model_version instead,
// falling back to this session's own record of what it just created for
// edits added after mount (those never appear in the static `detections`
// prop, which only reflects what existed when this view opened).
const manualEditIds = reactive(new Set())
function isManualEdit(edit) {
  if (manualEditIds.has(edit.edit_id)) return true
  return props.detections.find((d) => d.detection_id === edit.detection_id)?.model_version === 'manual'
}

// Text-only leaks (a caption fix with no photo edit) have nothing for
// /remediate/confirm to apply — the copy-paste suggestion above is the whole
// fix. Only show "Confirm" when at least one image edit is still pending.
const hasPendingImageEdits = computed(() => proposedEdits.value.some((e) => e.status !== 'reverted'))

const blurEdits = computed(() => proposedEdits.value.filter((e) => e.edit_type === 'blur'))
const stripEdits = computed(() => proposedEdits.value.filter((e) => e.edit_type === 'metadata_strip'))
// The scanner no longer proposes face covers at all, so every emoji edit is
// one the user drew themselves via "Cover a face" — which means they belong
// in the same list as any other self-marked area (and need its remove
// button), rather than the separate opt-in panel they used to live in.
const riskEdits = computed(() => proposedEdits.value)
// Still needed to render emoji covers on the canvas and make them draggable.
const faceEdits = computed(() => proposedEdits.value.filter((e) => e.edit_type === 'emoji'))

function editLabel(edit) {
  const detail = detailByEditId[edit.edit_id]
  if (edit.edit_type === 'blur') {
    if (detail) return `Blur: ${detail}`
    return blurEdits.value.length > 1
      ? `Blur flagged area ${blurEdits.value.indexOf(edit) + 1}`
      : 'Blur the flagged area in your photo'
  }
  if (edit.edit_type === 'metadata_strip') {
    return stripEdits.value.length > 1
      ? `Remove hidden GPS location data (${stripEdits.value.indexOf(edit) + 1})`
      : 'Remove hidden GPS location data'
  }
  if (edit.edit_type === 'emoji') {
    return faceEdits.value.length > 1
      ? `Cover face ${faceEdits.value.indexOf(edit) + 1} with an emoji`
      : 'Cover this face with an emoji'
  }
  return edit.edit_type
}

const confirming = ref(false)
const cancelling = ref(false)
const confirmed = ref(false)
const cleanedUrl = ref(null)
const error = ref('')
const copied = ref(false)

// A live, client-side approximation of the blur — so toggling a fix shows
// something immediately instead of only after the real server-side confirm.
// Approximated by drawing each flagged region at a fraction of its size and
// scaling it back up, rather than via ctx.filter: ctx.filter combined with
// ctx.clip() is unreliable in Safari (it silently no-ops there instead of
// blurring), but drawImage-based scaling is basic canvas functionality
// supported identically everywhere.
const canvasEl = ref(null)
let sourceImage = null
const PREVIEW_BLUR_SCALE = 0.08

function drawPreview() {
  if (!sourceImage || !canvasEl.value) return
  const canvas = canvasEl.value
  canvas.width = sourceImage.naturalWidth
  canvas.height = sourceImage.naturalHeight
  const ctx = canvas.getContext('2d')
  ctx.drawImage(sourceImage, 0, 0)

  for (const edit of blurEdits.value) {
    if (edit.status === 'reverted' || !edit.region_affected) continue
    const { x, y, w, h } = edit.region_affected

    const small = document.createElement('canvas')
    small.width = Math.max(1, Math.round(w * PREVIEW_BLUR_SCALE))
    small.height = Math.max(1, Math.round(h * PREVIEW_BLUR_SCALE))
    small.getContext('2d').drawImage(sourceImage, x, y, w, h, 0, 0, small.width, small.height)

    ctx.imageSmoothingEnabled = true
    ctx.drawImage(small, 0, 0, small.width, small.height, x, y, w, h)
  }

  for (const edit of faceEdits.value) {
    if (edit.status === 'reverted' || !edit.region_affected) continue
    drawEmojiPreview(ctx, edit.region_affected)
  }

  updateScale()
}

// Client-side approximation of the backend's generated smiley (see
// _generate_emoji in remediate_content) — just enough to preview the effect
// before confirming; the real, server-rendered version is what actually gets
// baked into the downloaded photo.
function drawEmojiPreview(ctx, region) {
  const { x, y, w, h } = region
  // Sized to the box's SMALLER side and centered — not stretched to fill an
  // arbitrary w x h — so dragging the box into a non-square shape just adds
  // padding around a still-circular face instead of squashing it into an
  // oval (matches _generate_emoji server-side).
  const dim = Math.min(w, h)
  const cx = x + w / 2
  const cy = y + h / 2
  const r = dim / 2
  const top = cy - r
  const left = cx - r

  ctx.save()
  ctx.beginPath()
  ctx.arc(cx, cy, r, 0, Math.PI * 2)
  ctx.fillStyle = '#ffcd28'
  ctx.fill()

  ctx.fillStyle = '#462d0a'
  const eyeR = Math.max(1, dim / 12)
  const eyeY = top + dim * 0.38
  for (const eyeX of [left + dim * 0.30, left + dim * 0.70]) {
    ctx.beginPath()
    ctx.arc(eyeX, eyeY, eyeR, 0, Math.PI * 2)
    ctx.fill()
  }

  ctx.beginPath()
  ctx.strokeStyle = '#462d0a'
  ctx.lineWidth = Math.max(2, dim / 18)
  ctx.lineCap = 'round'
  ctx.arc(cx, top + dim * 0.55, dim * 0.28, 0.35 * Math.PI, 0.65 * Math.PI)
  ctx.stroke()
  ctx.restore()
}

onMounted(() => {
  if (!props.photoUrl) return
  sourceImage = new Image()
  sourceImage.onload = drawPreview
  sourceImage.src = props.photoUrl
})

// Boxes people can drag/resize before confirming, in case a scan missed or
// mis-placed a region — same pixel-coordinate-vs-displayed-size scaling as
// ResultsView's finding boxes, kept in sync with the canvas's own rendered
// size (which is set to the image's natural size in drawPreview above).
const scale = ref(1)

function updateScale() {
  if (!canvasEl.value || !canvasEl.value.width) return
  scale.value = canvasEl.value.clientWidth / canvasEl.value.width
}

const editableBoxes = computed(() =>
  [...blurEdits.value, ...faceEdits.value].filter((e) => e.status !== 'reverted' && e.region_affected)
)

function boxStyle(region) {
  return {
    left: `${region.x * scale.value}px`,
    top: `${region.y * scale.value}px`,
    width: `${region.w * scale.value}px`,
    height: `${region.h * scale.value}px`,
  }
}

const MIN_BOX_SIZE = 15
const dragState = ref(null)

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), Math.max(min, max))
}

function beginDrag(edit, mode, evt) {
  if (confirmed.value || confirming.value) return
  evt.preventDefault()
  dragState.value = {
    edit,
    mode,
    startX: evt.clientX,
    startY: evt.clientY,
    startRegion: { ...edit.region_affected },
  }
  window.addEventListener('pointermove', onDragMove)
  window.addEventListener('pointerup', onDragEnd)
}

function startMove(edit, evt) {
  beginDrag(edit, 'move', evt)
}

function startResize(edit, evt) {
  evt.stopPropagation()
  beginDrag(edit, 'resize', evt)
}

// Lets someone mark a spot the scanner missed entirely, same interaction
// as move/resize above but drawing a fresh rectangle from a start point
// instead of adjusting one that already exists. Holds false, 'blur', or
// 'face' — which kind determines which API call onDragEnd makes once the
// box is drawn.
const addMode = ref(false)
const newBoxDraft = ref(null)

function toggleAddMode(kind) {
  addMode.value = addMode.value === kind ? false : kind
  newBoxDraft.value = null
}

function canvasPoint(evt) {
  const rect = canvasEl.value.getBoundingClientRect()
  return {
    x: clamp((evt.clientX - rect.left) / scale.value, 0, canvasEl.value.width),
    y: clamp((evt.clientY - rect.top) / scale.value, 0, canvasEl.value.height),
  }
}

function startNewBox(evt) {
  if (!addMode.value || confirmed.value || confirming.value || !canvasEl.value) return
  // Only start drawing on the canvas background itself, not on top of an
  // existing box (those already have their own pointerdown handling).
  if (evt.target !== canvasEl.value) return
  evt.preventDefault()
  const origin = canvasPoint(evt)
  newBoxDraft.value = { x: Math.round(origin.x), y: Math.round(origin.y), w: 0, h: 0 }
  dragState.value = { mode: 'draw', origin }
  window.addEventListener('pointermove', onDragMove)
  window.addEventListener('pointerup', onDragEnd)
}

function onDragMove(evt) {
  const d = dragState.value
  if (!d || !canvasEl.value) return

  if (d.mode === 'draw') {
    const cur = canvasPoint(evt)
    newBoxDraft.value = {
      x: Math.round(Math.min(d.origin.x, cur.x)), y: Math.round(Math.min(d.origin.y, cur.y)),
      w: Math.round(Math.abs(cur.x - d.origin.x)), h: Math.round(Math.abs(cur.y - d.origin.y)),
    }
    return
  }

  const dx = (evt.clientX - d.startX) / scale.value
  const dy = (evt.clientY - d.startY) / scale.value
  const maxW = canvasEl.value.width
  const maxH = canvasEl.value.height
  const region = { ...d.startRegion }

  if (d.mode === 'move') {
    region.x = clamp(d.startRegion.x + dx, 0, maxW - region.w)
    region.y = clamp(d.startRegion.y + dy, 0, maxH - region.h)
  } else {
    region.w = clamp(d.startRegion.w + dx, MIN_BOX_SIZE, maxW - region.x)
    region.h = clamp(d.startRegion.h + dy, MIN_BOX_SIZE, maxH - region.y)
  }

  d.edit.region_affected = {
    x: Math.round(region.x), y: Math.round(region.y),
    w: Math.round(region.w), h: Math.round(region.h),
  }
  drawPreview()
}

async function onDragEnd() {
  window.removeEventListener('pointermove', onDragMove)
  window.removeEventListener('pointerup', onDragEnd)
  const d = dragState.value
  dragState.value = null
  if (!d) return

  if (d.mode === 'draw') {
    const region = newBoxDraft.value
    const kind = addMode.value
    newBoxDraft.value = null
    addMode.value = false
    if (!region || region.w < MIN_BOX_SIZE || region.h < MIN_BOX_SIZE) return
    try {
      const edit = kind === 'face'
        ? await addManualFaceEdit(props.draftId, region)
        : await addManualEdit(props.draftId, region)
      manualEditIds.add(edit.edit_id)
      proposedEdits.value.push({ ...edit })
      drawPreview()
    } catch (err) {
      error.value = err.message || 'Could not add that area.'
    }
    return
  }

  const unchanged = JSON.stringify(d.startRegion) === JSON.stringify(d.edit.region_affected)
  if (unchanged) return

  try {
    await updateEditRegion(d.edit.edit_id, d.edit.region_affected)
  } catch (err) {
    error.value = err.message || 'Could not save that adjustment.'
    d.edit.region_affected = d.startRegion
    drawPreview()
  }
}

async function toggleEdit(edit) {
  error.value = ''
  const restoring = edit.status === 'reverted'
  // Flip + redraw immediately so the box/blur preview tracks the checkbox
  // with no visible lag; the server call below reconciles (or rolls back
  // on failure) rather than being the thing that first applies the change.
  const previousStatus = edit.status
  edit.status = restoring ? 'pending' : 'reverted'
  drawPreview()
  try {
    const updated = restoring ? await restoreEdit(edit.edit_id) : await revertEdit(edit.edit_id)
    edit.status = updated.status
    drawPreview()
  } catch (err) {
    edit.status = previousStatus
    drawPreview()
    error.value = err.message || 'Could not update that edit.'
  }
}

// Renaming only applies to self-marked areas (edits carrying a detection_id
// — see addManualEdit) since scanner-found ones already have a detail from
// the scan itself.
const renamingEditId = ref(null)
const renameDraft = ref('')

function startRename(edit) {
  renamingEditId.value = edit.edit_id
  renameDraft.value = detailByEditId[edit.edit_id] || ''
}

function cancelRename() {
  renamingEditId.value = null
}

// Enter and Esc explicitly blur the input (see template) before calling
// this, rather than leaving Vue to remove a still-focused element from the
// DOM when renamingEditId flips back to null. A focused element that gets
// disconnected has its focus reassigned by the browser to some other
// focusable element in the document — not necessarily <body> — which on
// this list can land on an unrelated checkbox and spuriously fire its
// change handler. Explicit blur() first sends focus to the safe default,
// so there's nothing left for the browser to reassign once Vue removes it.
async function removeManualEdit(edit) {
  try {
    await deleteEdit(edit.edit_id)
    proposedEdits.value = proposedEdits.value.filter((e) => e.edit_id !== edit.edit_id)
    manualEditIds.delete(edit.edit_id)
    // The canvas is a plain bitmap — removing the edit from the array alone
    // only hides its overlay box; whatever was already painted (blur/emoji)
    // stays baked into the pixels until the next full redraw.
    drawPreview()
  } catch (err) {
    error.value = err.message || 'Could not remove that area.'
  }
}

async function saveRename(edit) {
  // Both the explicit blur() below (Enter/Esc) and a real click-away funnel
  // through this same @blur handler; the guard makes a second call a no-op
  // instead of a duplicate request.
  if (renamingEditId.value !== edit.edit_id) return
  renamingEditId.value = null
  const label = renameDraft.value.trim()
  if (!label || label === detailByEditId[edit.edit_id]) return
  try {
    await renameDetection(edit.detection_id, label)
    detailByEditId[edit.edit_id] = label
  } catch (err) {
    error.value = err.message || 'Could not rename that area.'
  }
}

async function confirm() {
  confirming.value = true
  error.value = ''
  try {
    await confirmRemediation(props.draftId)
    const blob = await downloadRemediated(props.draftId)
    cleanedUrl.value = URL.createObjectURL(blob)
    confirmed.value = true
  } catch (err) {
    error.value = err.message || 'Something went wrong cleaning up your post.'
  } finally {
    confirming.value = false
  }
}

async function cancel() {
  cancelling.value = true
  error.value = ''
  try {
    await cancelRemediation(props.draftId)
    emit('restart')
  } catch (err) {
    error.value = err.message || 'Could not cancel this post.'
    cancelling.value = false
  }
}

// Copying the caption and saving it are one action from the user's side —
// "use this caption" — even though they're two calls: the clipboard write is
// what actually lets them paste it into the real post, and the save is what
// lets Trace score the version they took instead of the original forever.
// The save is best-effort and never blocks or undoes the copy: if it fails,
// the user still has the clean text on their clipboard, just with the
// privacy-score credit not yet reflecting it.
async function copySuggested() {
  await navigator.clipboard.writeText(redaction.suggested_caption)
  copied.value = true
  setTimeout(() => (copied.value = false), 1500)

  try {
    await saveCleanedCaption(props.draftId, redaction.suggested_caption)
    window.__mosaicCache = null
  } catch (err) {
    error.value = err.message || 'Copied, but could not save the caption for scoring.'
  }
}

const chatMessages = ref([])
const chatInput = ref('')
const chatLoading = ref(false)
const chatError = ref(null)
const chatExpanded = ref(false)

async function sendChat(text) {
  const message = (text ?? chatInput.value).trim()
  if (!message || chatLoading.value) return

  const history = chatMessages.value.slice()
  chatMessages.value.push({ role: 'user', content: message })
  chatInput.value = ''
  chatError.value = null
  chatLoading.value = true
  try {
    const { reply } = await sendTeachableMomentChat(props.draftId, message, history)
    chatMessages.value.push({ role: 'assistant', content: reply })
  } catch (err) {
    chatError.value = "Couldn't get an answer — try again."
  } finally {
    chatLoading.value = false
  }
}
</script>

<template>
  <div class="app-screen">
    <div class="app-header">
      <h1 class="app-title">Clean up</h1>
      <p class="app-subtitle">Choose what to blur, remove, or rewrite.</p>
    </div>

    <div class="app-content">
      <div
        v-if="!confirmed && photoUrl"
        class="canvas-wrap mb-1"
        :class="{ 'add-mode': addMode }"
        @pointerdown="startNewBox"
      >
        <canvas ref="canvasEl" class="w-100 rounded d-block"></canvas>
        <div
          v-for="edit in editableBoxes"
          :key="edit.edit_id"
          class="edit-box"
          :class="{ 'pe-none': addMode }"
          :style="boxStyle(edit.region_affected)"
          @pointerdown="startMove(edit, $event)"
        >
          <div class="resize-handle" @pointerdown="startResize(edit, $event)"></div>
        </div>
        <div v-if="newBoxDraft" class="new-box" :style="boxStyle(newBoxDraft)"></div>
      </div>
      <img v-else-if="confirmed && cleanedUrl" :src="cleanedUrl" class="w-100 rounded mb-1" alt="Cleaned photo" />
      <p v-if="confirmed" class="status-chip safe mx-auto mb-3">Cleaned version</p>
      <template v-else-if="photoUrl">
        <div class="d-flex gap-2 mb-2 flex-wrap justify-content-center">
          <button
            class="btn btn-sm"
            :class="addMode === 'blur' ? 'btn-secondary' : 'btn-outline-primary'"
            @click="toggleAddMode('blur')"
          >
            {{ addMode === 'blur' ? 'Cancel marking' : 'Mark a missed area' }}
          </button>
          <button
            class="btn btn-sm"
            :class="addMode === 'face' ? 'btn-secondary' : 'btn-outline-primary'"
            @click="toggleAddMode('face')"
          >
            {{ addMode === 'face' ? 'Cancel marking' : 'Cover a face' }}
          </button>
        </div>
        <p v-if="addMode" class="soft-note text-center mb-3">Drag on the photo to draw a box around it.</p>
        <p v-else-if="editableBoxes.length" class="soft-note text-center mb-3">
          Drag a box to move it, or its corner to resize.
        </p>
      </template>
      <div v-else class="mb-3"></div>

      <div v-if="riskEdits.length" class="fix-panel mb-3">
        <p class="fw-bold small mb-2">Suggested fixes</p>
        <div v-for="edit in riskEdits" :key="edit.edit_id" class="form-check form-switch fix-row">
          <input
            :id="edit.edit_id"
            class="form-check-input"
            type="checkbox"
            :checked="edit.status !== 'reverted'"
            :disabled="confirmed"
            @change="toggleEdit(edit)"
          />
          <template v-if="renamingEditId === edit.edit_id">
            <input
              v-model="renameDraft"
              type="text"
              class="form-control form-control-sm d-inline-block w-auto align-middle"
              style="max-width: 180px"
              maxlength="255"
              autofocus
              placeholder="Name this area"
              @keyup.enter="$event.target.blur()"
              @keyup.esc="cancelRename(); $event.target.blur()"
              @blur="saveRename(edit)"
            />
            <button
              type="button"
              class="btn btn-link btn-sm p-0 ms-2 text-secondary"
              style="font-size:0.78rem"
              @mousedown.prevent="cancelRename()"
            >
              Cancel
            </button>
          </template>
          <label v-else class="form-check-label small fw-semibold" :for="edit.edit_id">
            {{ editLabel(edit) }}
            <button
              v-if="isManualEdit(edit) && !confirmed"
              type="button"
              class="rename-btn"
              aria-label="Rename this area"
              @click.stop.prevent="startRename(edit)"
            >
              Edit
            </button>
            <button
              v-if="isManualEdit(edit) && !confirmed"
              type="button"
              class="remove-btn"
              aria-label="Remove this area"
              @click.stop.prevent="removeManualEdit(edit)"
            >
              ×
            </button>
          </label>
        </div>
      </div>


      <div v-if="redaction" class="fix-panel mb-3">
        <p class="fw-bold small mb-1">Caption</p>
        <p class="text-muted small text-decoration-line-through mb-1">{{ redaction.original_caption }}</p>
        <p class="small mb-2 suggested-caption">{{ redaction.suggested_caption }}</p>
        <button class="btn btn-sm btn-outline-secondary" @click="copySuggested">
          {{ copied ? 'Copied!' : 'Use this caption' }}
        </button>
      </div>

      <p v-if="error" class="text-danger small">{{ error }}</p>

      <div v-if="teachableMoment" class="coach-card mt-3">
        <p class="eyebrow mb-1">Why this matters</p>
        <p class="fw-semibold mb-1">{{ teachableMoment.title }}</p>
        <p class="small mb-2">{{ teachableMoment.explanation }}</p>
        <p class="small mb-0"><strong>Safer move:</strong> {{ teachableMoment.safer_action }}</p>

        <div class="chat-section mt-3">
          <div class="chat-section-head">
            <span class="chat-section-title">Ask a question</span>
            <button
              type="button"
              class="chat-expand-btn"
              aria-label="Expand chat"
              @click="chatExpanded = true"
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <path d="M8 3H5a2 2 0 0 0-2 2v3M16 3h3a2 2 0 0 1 2 2v3M8 21H5a2 2 0 0 1-2-2v-3M16 21h3a2 2 0 0 0 2-2v-3"
                  stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
              </svg>
            </button>
          </div>
          <TeachableChatPanel
            v-model="chatInput"
            :messages="chatMessages"
            :loading="chatLoading"
            :error="chatError"
            :discussion-prompt="teachableMoment.discussion_prompt"
            :show-sim-suggestion="!!teachableMoment.category"
            @send="sendChat"
          />
        </div>
      </div>
    </div>

    <div class="app-action-bar">
      <button
        v-if="!confirmed && hasPendingImageEdits"
        class="btn btn-primary w-100"
        :disabled="confirming || cancelling"
        @click="confirm"
      >
        {{ confirming ? 'Cleaning up…' : 'Create cleaned copy' }}
      </button>
      <a v-else-if="confirmed" class="btn btn-success w-100" :href="cleanedUrl" download="trace_clean_photo.jpg">
        Download cleaned photo
      </a>
      <button
        v-if="!confirmed"
        class="btn btn-outline-danger w-100"
        :disabled="confirming || cancelling"
        @click="cancel"
      >
        {{ cancelling ? 'Cancelling…' : 'Cancel this post' }}
      </button>
      <button class="btn btn-outline-secondary w-100" :disabled="cancelling" @click="emit('restart')">Back</button>
    </div>

    <div v-if="chatExpanded && teachableMoment" class="chat-fullscreen">
      <div class="chat-fullscreen-header">
        <button type="button" class="chat-back-btn" @click="chatExpanded = false">← Back</button>
        <p class="chat-fullscreen-title mb-0">Ask a question</p>
      </div>
      <TeachableChatPanel
        v-model="chatInput"
        fullscreen
        :messages="chatMessages"
        :loading="chatLoading"
        :error="chatError"
        :discussion-prompt="teachableMoment.discussion_prompt"
        :show-sim-suggestion="!!teachableMoment.category"
        @send="sendChat"
      />
    </div>
  </div>
</template>

<style scoped>
.canvas-wrap {
  position: relative;
  line-height: 0;
  touch-action: none;
  border: 1px solid var(--trace-line);
  border-radius: 18px;
  overflow: hidden;
}
.canvas-wrap.add-mode {
  cursor: crosshair;
}
.edit-box {
  position: absolute;
  border: 2px solid var(--trace-primary);
  border-radius: 8px;
  cursor: move;
  touch-action: none;
}
.resize-handle {
  position: absolute;
  right: -7px;
  bottom: -7px;
  width: 14px;
  height: 14px;
  background: var(--trace-primary);
  border: 2px solid #fff;
  border-radius: 50%;
  cursor: nwse-resize;
  touch-action: none;
}
.new-box {
  position: absolute;
  border: 2px dashed var(--trace-mint);
  border-radius: 8px;
  background: rgba(21, 165, 139, 0.15);
  pointer-events: none;
}
.fix-panel {
  padding: 12px 14px;
  border: 1px solid var(--trace-line);
  border-radius: 14px;
  background: #fff;
}
.x-small {
  font-size: 0.72rem;
}
.fix-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 0;
  padding-left: 0 !important;
  border-top: 1px solid #eef2f7;
}
.fix-row .form-check-input {
  float: none;
  margin: 0;
  flex-shrink: 0;
  position: static;
}
.fix-row .form-check-label {
  display: flex;
  align-items: center;
  flex: 1;
  margin-bottom: 0;
  padding-left: 0;
}
.rename-btn {
  border: none;
  background: #eef0f3;
  color: #6b7280;
  font-size: 0.7rem;
  font-weight: 600;
  padding: 2px 7px;
  border-radius: 6px;
  margin-left: 6px;
  line-height: 1.4;
  cursor: pointer;
}
.rename-btn:hover {
  background: #e2e5ea;
  color: #374151;
}
.fix-row:first-of-type {
  border-top: 0;
}
.remove-btn {
  border: none;
  background: none;
  color: #9ca3af;
  font-size: 1rem;
  line-height: 1;
  margin-left: auto;
  padding: 0 2px;
  cursor: pointer;
}
.remove-btn:hover {
  color: #dc3545;
}
.suggested-caption {
  padding: 10px;
  border-radius: 12px;
  background: #f4fbf8;
}
.chat-section {
  position: relative;
  border-top: 1px solid var(--trace-line);
  padding-top: 10px;
}
.chat-section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.chat-section-title {
  font-size: 0.8rem;
  font-weight: 700;
  color: #667085;
}
.chat-expand-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: none;
  border: none;
  color: #98a2b3;
  padding: 2px;
  cursor: pointer;
}
.chat-expand-btn:hover {
  color: #667085;
}
.chat-fullscreen {
  position: absolute;
  inset: 0;
  z-index: 20;
  background: #fff;
  display: flex;
  flex-direction: column;
  padding: 16px;
}
.chat-fullscreen-header {
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: center;
  gap: 12px;
  padding-bottom: 12px;
  margin-bottom: 12px;
  border-bottom: 1px solid var(--trace-line);
}
.chat-back-btn {
  justify-self: start;
  background: none;
  border: none;
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--trace-coral);
  padding: 4px 0;
  cursor: pointer;
}
.chat-fullscreen-title {
  font-weight: 700;
  font-size: 0.95rem;
  text-align: center;
}
</style>
