<script setup>
import { ref, computed, onMounted } from 'vue'
import { confirmRemediation, revertEdit, restoreEdit, downloadUrl, updateEditRegion, addManualEdit } from '../api'

const props = defineProps({
  draftId: { type: String, required: true },
  remediation: { type: Object, required: true },
  photoUrl: { type: String, default: null },
  detections: { type: Array, default: () => [] },
})
defineEmits(['restart'])

const proposedEdits = ref((props.remediation.proposed_edits || []).map((e) => ({ ...e })))
const redaction = props.remediation.text_redaction

// Edits don't carry the scanner's own description of what they're for (no
// detail field, no link back to the Detection they were proposed from —
// see remediate_content's propose step, which only copies the region) so
// without this a box no bigger than a dot has no way to tell the user what
// it actually is beyond a bare number. Matched once, up front, by exact
// region — a plain object rather than a computed since it only needs the
// edits' original (pre-drag) regions, taken as they arrived as props.
const detailByEditId = {}
for (const edit of proposedEdits.value) {
  const region = edit.region_affected
  if (!region) continue
  const match = props.detections.find((d) => {
    const r = d.bounding_region
    return r && r.x === region.x && r.y === region.y && r.w === region.w && r.h === region.h
  })
  if (match?.detail) detailByEditId[edit.edit_id] = match.detail
}

// Text-only leaks (a caption fix with no photo edit) have nothing for
// /remediate/confirm to apply — the copy-paste suggestion above is the whole
// fix. Only show "Confirm" when at least one image edit is still pending.
const hasPendingImageEdits = computed(() => proposedEdits.value.some((e) => e.status !== 'reverted'))

const blurEdits = computed(() => proposedEdits.value.filter((e) => e.edit_type === 'blur'))
const stripEdits = computed(() => proposedEdits.value.filter((e) => e.edit_type === 'metadata_strip'))

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
  return edit.edit_type
}

const confirming = ref(false)
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

  updateScale()
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
  blurEdits.value.filter((e) => e.status !== 'reverted' && e.region_affected)
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
// instead of adjusting one that already exists.
const addMode = ref(false)
const newBoxDraft = ref(null)

function toggleAddMode() {
  addMode.value = !addMode.value
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
    newBoxDraft.value = null
    addMode.value = false
    if (!region || region.w < MIN_BOX_SIZE || region.h < MIN_BOX_SIZE) return
    try {
      const edit = await addManualEdit(props.draftId, region)
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
  try {
    const updated = restoring ? await restoreEdit(edit.edit_id) : await revertEdit(edit.edit_id)
    edit.status = updated.status
    drawPreview()
  } catch (err) {
    error.value = err.message || 'Could not update that edit.'
  }
}

async function confirm() {
  confirming.value = true
  error.value = ''
  try {
    await confirmRemediation(props.draftId)
    const blob = await fetch(downloadUrl(props.draftId)).then((r) => r.blob())
    cleanedUrl.value = URL.createObjectURL(blob)
    confirmed.value = true
  } catch (err) {
    error.value = err.message || 'Something went wrong cleaning up your post.'
  } finally {
    confirming.value = false
  }
}

async function copySuggested() {
  await navigator.clipboard.writeText(redaction.suggested_caption)
  copied.value = true
  setTimeout(() => (copied.value = false), 1500)
}
</script>

<template>
  <div class="d-flex flex-column h-100">
    <div class="border-bottom p-3 text-center fw-bold">Clean up before sharing</div>

    <div class="p-3 flex-grow-1 overflow-auto">
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
      <p v-if="confirmed" class="text-success small text-center mb-3">✅ Cleaned version</p>
      <template v-else-if="photoUrl">
        <button class="btn btn-sm mb-2" :class="addMode ? 'btn-secondary' : 'btn-outline-primary'" @click="toggleAddMode">
          {{ addMode ? 'Cancel' : '+ Mark a missed area' }}
        </button>
        <p v-if="addMode" class="text-muted small text-center mb-3">Drag on the photo to draw a box around it.</p>
        <p v-else-if="editableBoxes.length" class="text-muted small text-center mb-3">
          Drag a box to move it, or the corner handle to resize it.
        </p>
      </template>
      <div v-else class="mb-3"></div>

      <div v-if="proposedEdits.length" class="mb-3">
        <p class="fw-semibold small mb-2">Suggested fixes</p>
        <div v-for="edit in proposedEdits" :key="edit.edit_id" class="form-check form-switch mb-2">
          <input
            :id="edit.edit_id"
            class="form-check-input"
            type="checkbox"
            :checked="edit.status !== 'reverted'"
            :disabled="confirmed"
            @change="toggleEdit(edit)"
          />
          <label class="form-check-label small" :for="edit.edit_id">
            {{ editLabel(edit) }}
          </label>
        </div>
      </div>

      <div v-if="redaction" class="mb-3">
        <p class="fw-semibold small mb-1">Caption</p>
        <p class="text-muted small text-decoration-line-through mb-1">{{ redaction.original_caption }}</p>
        <p class="small mb-2">{{ redaction.suggested_caption }}</p>
        <button class="btn btn-sm btn-outline-secondary" @click="copySuggested">
          {{ copied ? 'Copied!' : 'Copy suggested caption' }}
        </button>
      </div>

      <p v-if="error" class="text-danger small">{{ error }}</p>
    </div>

    <div class="p-3 border-top d-flex flex-column gap-2">
      <button
        v-if="!confirmed && hasPendingImageEdits"
        class="btn btn-primary w-100"
        :disabled="confirming"
        @click="confirm"
      >
        {{ confirming ? 'Cleaning up…' : 'Confirm & clean up' }}
      </button>
      <a v-else-if="confirmed" class="btn btn-success w-100" :href="cleanedUrl" download="trace_clean_photo.jpg">
        Download cleaned photo
      </a>
      <button class="btn btn-outline-secondary w-100" @click="$emit('restart')">Back to start</button>
    </div>
  </div>
</template>

<style scoped>
.canvas-wrap {
  position: relative;
  line-height: 0;
  touch-action: none;
}
.canvas-wrap.add-mode {
  cursor: crosshair;
}
.edit-box {
  position: absolute;
  border: 2px solid #0d6efd;
  border-radius: 4px;
  cursor: move;
  touch-action: none;
}
.resize-handle {
  position: absolute;
  right: -7px;
  bottom: -7px;
  width: 14px;
  height: 14px;
  background: #0d6efd;
  border: 2px solid #fff;
  border-radius: 50%;
  cursor: nwse-resize;
  touch-action: none;
}
.new-box {
  position: absolute;
  border: 2px dashed #198754;
  border-radius: 4px;
  background: rgba(25, 135, 84, 0.15);
  pointer-events: none;
}
</style>
