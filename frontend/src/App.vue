<script setup>
import { ref } from 'vue'
import PhoneFrame from './components/PhoneFrame.vue'
import ComposeView from './views/ComposeView.vue'
import ResultsView from './views/ResultsView.vue'
import RemediationView from './views/RemediationView.vue'
import QuarantineView from './views/QuarantineView.vue'
import { uploadPost, processDraft, getDetections } from './api'

// No auth yet (users service is still a stub) — every post shares this owner_id.
const DEMO_OWNER_ID = 'demo-user'

const step = ref(1) // 1 compose, 2 scanning, 3 results, 4 action, 5 error
const photoPreviewUrl = ref(null)
const detections = ref([])
const draftId = ref(null)
const scanOutcome = ref(null)
// Set directly from scanOutcome.remediation, or replaced by quarantine's
// "edit" handoff, which also produces a remediation payload to act on.
const activeRemediation = ref(null)
const errorMessage = ref('')
// Set while a request is being retried after a network-level failure.
const wakingUp = ref(false)

function onRetry() {
  wakingUp.value = true
}

async function handleShare(payload) {
  errorMessage.value = ''
  wakingUp.value = false
  step.value = 2

  if (photoPreviewUrl.value) URL.revokeObjectURL(photoPreviewUrl.value)
  photoPreviewUrl.value = URL.createObjectURL(payload.photoFile)

  try {
    const draft = await uploadPost({
      ownerId: DEMO_OWNER_ID,
      contentType: 'image',
      sourceApp: 'trace-web',
      caption: payload.caption,
      photoFile: payload.photoFile,
    }, onRetry)
    draftId.value = draft.draft_id

    scanOutcome.value = await processDraft(draft.draft_id, onRetry)
    detections.value = await getDetections(draft.draft_id, onRetry)
    if (scanOutcome.value.outcome === 'remediated') {
      activeRemediation.value = scanOutcome.value.remediation
    }
    step.value = 3
  } catch (err) {
    // Network-level failures (fetch throwing, or our own abort-timeout) surface
    // raw browser wording like "Load failed" — not something to show as-is.
    // Only messages our own API layer attached (via parseOrThrow) are meant
    // for display.
    const isNetworkError = err instanceof TypeError || err.name === 'AbortError'
    errorMessage.value = isNetworkError
      ? "We're having trouble connecting right now. Please try again in a moment."
      : err.message || 'Something went wrong. Please try again.'
    step.value = 5
  } finally {
    wakingUp.value = false
  }
}

function handleQuarantineEdit(remediation) {
  activeRemediation.value = remediation
  scanOutcome.value = { ...scanOutcome.value, outcome: 'remediated' }
}

function restart() {
  step.value = 1
  if (photoPreviewUrl.value) URL.revokeObjectURL(photoPreviewUrl.value)
  photoPreviewUrl.value = null
  detections.value = []
  draftId.value = null
  scanOutcome.value = null
  activeRemediation.value = null
  errorMessage.value = ''
}
</script>

<template>
  <div class="d-flex justify-content-center align-items-center min-vh-100 bg-light">
    <PhoneFrame>

      <!-- Step 1: Compose -->
      <ComposeView v-if="step === 1" @share="handleShare" />

      <!-- Step 2: Scanning -->
      <div v-else-if="step === 2" class="d-flex flex-column h-100 align-items-center justify-content-center text-center p-4">
        <div class="spinner-border text-primary mb-3" role="status">
          <span class="visually-hidden">Scanning…</span>
        </div>
        <template v-if="wakingUp">
          <p class="fw-semibold mb-1">Scanning your post</p>
          <p class="text-muted small">This is taking a little longer than usual — thanks for your patience.</p>
        </template>
        <template v-else>
          <p class="fw-semibold mb-1">Scanning your post</p>
          <p class="text-muted small">Checking for faces, locations, and hidden data…</p>
        </template>
      </div>

      <!-- Step 3: Results -->
      <ResultsView
        v-else-if="step === 3"
        :photo-url="photoPreviewUrl"
        :detections="detections"
        @restart="restart"
        @continue="step = 4"
      />

      <!-- Step 4: Take action (remediate or quarantine) -->
      <RemediationView
        v-else-if="step === 4 && scanOutcome?.outcome === 'remediated'"
        :draft-id="draftId"
        :remediation="activeRemediation"
        :photo-url="photoPreviewUrl"
        :detections="detections"
        @restart="restart"
      />
      <QuarantineView
        v-else-if="step === 4 && scanOutcome?.outcome === 'quarantined'"
        :quarantine="scanOutcome.quarantine"
        :photo-url="photoPreviewUrl"
        @restart="restart"
        @edit="handleQuarantineEdit"
      />

      <!-- Step 5: Error -->
      <div v-else-if="step === 5" class="p-4 text-center">
        <p class="text-danger fw-semibold">{{ errorMessage }}</p>
        <button class="btn btn-outline-secondary" @click="restart">Try again</button>
      </div>

    </PhoneFrame>
  </div>
</template>