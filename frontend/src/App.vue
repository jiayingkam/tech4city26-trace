<script setup>
import { ref } from 'vue'
import PhoneFrame from './components/PhoneFrame.vue'
import HamburgerMenu from './components/HamburgerMenu.vue'
import LoginView from './views/LoginView.vue'
import ComposeView from './views/ComposeView.vue'
import ResultsView from './views/ResultsView.vue'
import RemediationView from './views/RemediationView.vue'
import QuarantineView from './views/QuarantineView.vue'
import HistoryView from './views/HistoryView.vue'
import SettingsView from './views/SettingsView.vue'
import { uploadPost, processDraft, getDetections, getTeachableMoment, getToken, getMe, logout as apiLogout } from './api'

// 0 login, 1 compose, 2 scanning, 3 results, 4 action, 5 error — skip
// straight past login if a token from earlier this tab session is still
// around (sessionStorage, so a closed tab always lands back on login).
const step = ref(getToken() ? 1 : 0)
const photoPreviewUrl = ref(null)
const detections = ref([])
const draftId = ref(null)
const scanOutcome = ref(null)
const teachableMoment = ref(null)
// Set directly from scanOutcome.remediation, or replaced by quarantine's
// "edit" handoff, which also produces a remediation payload to act on.
const activeRemediation = ref(null)
const errorMessage = ref('')
// Set while a request is being retried after a network-level failure.
const wakingUp = ref(false)

// The hamburger menu (History/Settings) sits alongside the compose flow
// rather than inside its step numbering — reachable from any step once
// logged in, and returning to 'app' resumes wherever the step flow was.
const screen = ref('app')
const settingsUser = ref(null)

async function openSettings() {
  errorMessage.value = ''
  try {
    settingsUser.value = await getMe()
    screen.value = 'settings'
  } catch (err) {
    // screen stays 'app', so route through the existing step=5 error
    // display rather than a message with nowhere to render.
    errorMessage.value = err.message || 'Could not load your settings.'
    step.value = 5
  }
}

async function handleLogout() {
  await apiLogout()
  screen.value = 'app'
  restart()
  step.value = 0
}

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
      contentType: 'image',
      sourceApp: 'trace-web',
      caption: payload.caption,
      photoFile: payload.photoFile,
    }, onRetry)
    draftId.value = draft.draft_id

    scanOutcome.value = await processDraft(draft.draft_id, onRetry)
    detections.value = await getDetections(draft.draft_id, onRetry)
    try {
      teachableMoment.value = await getTeachableMoment(draft.draft_id, onRetry)
    } catch {
      teachableMoment.value = null
    }
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
  teachableMoment.value = null
  activeRemediation.value = null
  errorMessage.value = ''
}
</script>

<template>
  <div class="app-stage d-flex justify-content-center align-items-center">
    <PhoneFrame>

      <HamburgerMenu
        v-if="step !== 0 && screen === 'app'"
        @history="screen = 'history'"
        @settings="openSettings"
        @logout="handleLogout"
      />

      <!-- Hamburger menu: History / Settings -->
      <HistoryView
        v-if="screen === 'history'"
        @back="screen = 'app'"
        @history="screen = 'history'"
        @settings="openSettings"
        @logout="handleLogout"
      />
      <SettingsView
        v-else-if="screen === 'settings' && settingsUser"
        :user="settingsUser"
        @updated="settingsUser = $event"
        @back="screen = 'app'"
        @history="screen = 'history'"
        @logout="handleLogout"
      />

      <!-- Step 0: Login -->
      <LoginView v-else-if="step === 0" @success="step = 1" />

      <!-- Step 1: Compose -->
      <ComposeView v-else-if="step === 1" @share="handleShare" />

      <!-- Step 2: Scanning -->
      <div v-else-if="step === 2" class="app-screen align-items-center justify-content-center text-center p-4">
        <div class="spinner-border text-primary mb-3" role="status">
          <span class="visually-hidden">Scanning…</span>
        </div>
        <template v-if="wakingUp">
          <p class="fw-bold mb-1">Scanning your post</p>
          <p class="soft-note">This is taking a little longer than usual. Thanks for hanging tight.</p>
        </template>
        <template v-else>
          <p class="fw-bold mb-1">Scanning your post</p>
          <p class="soft-note">Checking for faces, places, text, and hidden photo data.</p>
        </template>
      </div>

      <!-- Step 3: Results -->
      <ResultsView
        v-else-if="step === 3"
        :photo-url="photoPreviewUrl"
        :detections="detections"
        :teachable-moment="teachableMoment"
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
      <div v-else-if="step === 5" class="app-screen justify-content-center p-4 text-center">
        <p class="text-danger fw-semibold">{{ errorMessage }}</p>
        <button class="btn btn-outline-secondary" @click="restart">Try again</button>
      </div>

    </PhoneFrame>
  </div>
</template>
