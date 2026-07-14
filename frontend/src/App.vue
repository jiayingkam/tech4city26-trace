<script setup>
import { ref } from 'vue'
import PhoneFrame from './components/PhoneFrame.vue'
import ComposeView from './views/ComposeView.vue'
import { uploadPost, processDraft } from './api'

// No auth yet (users service is still a stub) — every post shares this owner_id.
const DEMO_OWNER_ID = 'demo-user'

const step = ref(1) // 1 compose, 2 scanning, 3 results, 4 error
const caption = ref('')
const draftId = ref(null)
const scanOutcome = ref(null)
const errorMessage = ref('')

async function handleShare(payload) {
  caption.value = payload.caption
  errorMessage.value = ''
  step.value = 2

  try {
    const draft = await uploadPost({
      ownerId: DEMO_OWNER_ID,
      contentType: 'image',
      sourceApp: 'trace-web',
      caption: payload.caption,
      photoFile: payload.photoFile,
    })
    draftId.value = draft.draft_id

    scanOutcome.value = await processDraft(draft.draft_id)
    step.value = 3
  } catch (err) {
    errorMessage.value = err.message || 'Something went wrong. Please try again.'
    step.value = 4
  }
}

function restart() {
  step.value = 1
  caption.value = ''
  draftId.value = null
  scanOutcome.value = null
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
        <p class="fw-semibold mb-1">Scanning your post</p>
        <p class="text-muted small">Checking for faces, locations, and hidden data…</p>
      </div>

      <!-- Step 3: Results (placeholder — real findings UI is the next step) -->
      <div v-else-if="step === 3" class="p-4 text-center">
        <p class="fw-semibold">Scan complete: {{ scanOutcome?.outcome }}</p>
        <p class="text-muted small">draft_id: {{ draftId }}</p>
        <p class="text-muted small">Results screen goes here next.</p>
        <button class="btn btn-outline-secondary" @click="restart">Back to start</button>
      </div>

      <!-- Step 4: Error -->
      <div v-else-if="step === 4" class="p-4 text-center">
        <p class="text-danger fw-semibold">{{ errorMessage }}</p>
        <button class="btn btn-outline-secondary" @click="restart">Try again</button>
      </div>

    </PhoneFrame>
  </div>
</template>