<script setup>
import { ref, computed, onMounted } from 'vue'
import { confirmRemediation, revertEdit, restoreEdit, downloadUrl } from '../api'

const props = defineProps({
  draftId: { type: String, required: true },
  remediation: { type: Object, required: true },
  photoUrl: { type: String, default: null },
})
defineEmits(['restart'])

const proposedEdits = ref((props.remediation.proposed_edits || []).map((e) => ({ ...e })))
const redaction = props.remediation.text_redaction

// Text-only leaks (a caption fix with no photo edit) have nothing for
// /remediate/confirm to apply — the copy-paste suggestion above is the whole
// fix. Only show "Confirm" when at least one image edit is still pending.
const hasPendingImageEdits = computed(() => proposedEdits.value.some((e) => e.status !== 'reverted'))

const blurEdits = computed(() => proposedEdits.value.filter((e) => e.edit_type === 'blur'))
const stripEdits = computed(() => proposedEdits.value.filter((e) => e.edit_type === 'metadata_strip'))

function editLabel(edit) {
  if (edit.edit_type === 'blur') {
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
// A solid fill rather than a canvas blur filter: ctx.filter combined with
// ctx.clip() is unreliable in Safari (it silently no-ops there instead of
// blurring), and the real server-side blur at the radius remediate_content
// uses already renders small flagged regions as a near-solid block anyway —
// so this reads the same in practice while working identically everywhere.
const canvasEl = ref(null)
let sourceImage = null

function drawPreview() {
  if (!sourceImage || !canvasEl.value) return
  const canvas = canvasEl.value
  canvas.width = sourceImage.naturalWidth
  canvas.height = sourceImage.naturalHeight
  const ctx = canvas.getContext('2d')
  ctx.drawImage(sourceImage, 0, 0)

  ctx.fillStyle = 'rgb(20, 20, 20)'
  for (const edit of blurEdits.value) {
    if (edit.status === 'reverted' || !edit.region_affected) continue
    const { x, y, w, h } = edit.region_affected
    ctx.fillRect(x, y, w, h)
  }
}

onMounted(() => {
  if (!props.photoUrl) return
  sourceImage = new Image()
  sourceImage.onload = drawPreview
  sourceImage.src = props.photoUrl
})

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
      <canvas v-if="!confirmed && photoUrl" ref="canvasEl" class="w-100 rounded mb-1"></canvas>
      <img v-else-if="confirmed && cleanedUrl" :src="cleanedUrl" class="w-100 rounded mb-1" alt="Cleaned photo" />
      <p v-if="confirmed" class="text-success small text-center mb-3">✅ Cleaned version</p>
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
