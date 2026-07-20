<script setup>
import { ref, onUnmounted } from 'vue'
import PhoneFrame from './components/PhoneFrame.vue'
import HamburgerMenu from './components/HamburgerMenu.vue'
import LoginView from './views/LoginView.vue'
import ComposeView from './views/ComposeView.vue'
import ResultsView from './views/ResultsView.vue'
import RemediationView from './views/RemediationView.vue'
import QuarantineView from './views/QuarantineView.vue'
import HistoryView from './views/HistoryView.vue'
import SettingsView from './views/SettingsView.vue'
import MosaicView from './views/MosaicView.vue'
import { uploadPost, processDraft, getDetections, getTeachableMoment, getMosaicRisk, getToken, getMe, logout as apiLogout } from './api'
import { quickTeachTips } from './content/loadQuickTeach'

// 0 login, 1 compose, 2 scanning, 3 results, 4 action, 5 error — skip
// straight past login if a token from earlier this tab session is still
// around (sessionStorage, so a closed tab always lands back on login).
const step = ref(getToken() ? 1 : 0)
const photoPreviewUrl = ref(null)
const detections = ref([])
const draftId = ref(null)
const scanOutcome = ref(null)
const teachableMoment = ref(null)
const mosaicRisk = ref(null)
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
// This is the tips that would be shown when the screen is loading
const quickTeachTip = ref('')
const scanMascot = ref(quickTeachTips[0]?.mascot || 'camera')

async function openSettings() {
  errorMessage.value = ''
  try {
    settingsUser.value = await getMe()
    screen.value = 'settings'
  } catch (err) {
    errorMessage.value = err.message || 'Could not load your settings.'
    screen.value = 'app'
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
  startQuickTeach()
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
    const [detections_, me_] = await Promise.all([
      getDetections(draft.draft_id, onRetry),
      getMe(),
    ])
    detections.value = detections_
    const [tm, mosaic] = await Promise.all([
      getTeachableMoment(draft.draft_id, onRetry).catch(() => null),
      getMosaicRisk(me_.user_id, draft.draft_id).catch(() => null),
    ])
    teachableMoment.value = tm
    mosaicRisk.value = mosaic
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
    stopQuickTeach()
  }
}

function handleQuarantineEdit(remediation) {
  activeRemediation.value = remediation
  scanOutcome.value = { ...scanOutcome.value, outcome: 'remediated' }
}

function restart() {
  stopQuickTeach()
  step.value = 1
  if (photoPreviewUrl.value) URL.revokeObjectURL(photoPreviewUrl.value)
  photoPreviewUrl.value = null
  detections.value = []
  draftId.value = null
  scanOutcome.value = null
  teachableMoment.value = null
  mosaicRisk.value = null
  activeRemediation.value = null
  errorMessage.value = ''
}
let quickTeachTimer = null
let remainingQuickTeachTips = []
let previousQuickTeachTip = null

function refillQuickTeachTips() {
  remainingQuickTeachTips = [...quickTeachTips]
}

function pickQuickTeachTip() {
  if (remainingQuickTeachTips.length === 0) refillQuickTeachTips()

  const variedCandidates = remainingQuickTeachTips.filter((tip) => (
    tip.text !== previousQuickTeachTip?.text
    && tip.mascot !== previousQuickTeachTip?.mascot
  ))
  const candidates = variedCandidates.length > 0
    ? variedCandidates
    : remainingQuickTeachTips.filter((tip) => tip.text !== previousQuickTeachTip?.text)
  const pool = candidates.length > 0 ? candidates : remainingQuickTeachTips
  const next = pool[Math.floor(Math.random() * pool.length)]

  remainingQuickTeachTips = remainingQuickTeachTips.filter((tip) => tip !== next)
  previousQuickTeachTip = next
  quickTeachTip.value = next.text
  scanMascot.value = next.mascot
}

function startQuickTeach() {
  refillQuickTeachTips()
  previousQuickTeachTip = null
  pickQuickTeachTip()
  clearInterval(quickTeachTimer)
  quickTeachTimer = setInterval(pickQuickTeachTip, 5000)
}

function stopQuickTeach() {
  clearInterval(quickTeachTimer)
  quickTeachTimer = null
}

onUnmounted(stopQuickTeach)

</script>

<template>
  <div class="app-stage d-flex justify-content-center align-items-center">
    <PhoneFrame>

      <HamburgerMenu
        v-if="step !== 0 && screen === 'app'"
        @history="screen = 'history'"
        @settings="openSettings"
        @mosaic="screen = 'mosaic'"
        @logout="handleLogout"
      />

      <!-- Hamburger menu: History / Settings -->
      <HistoryView
        v-if="screen === 'history'"
        @back="screen = 'app'"
        @history="screen = 'history'"
        @settings="openSettings"
        @mosaic="screen = 'mosaic'"
        @logout="handleLogout"
      />
      <SettingsView
        v-else-if="screen === 'settings' && settingsUser"
        :user="settingsUser"
        @updated="settingsUser = $event"
        @back="screen = 'app'"
        @history="screen = 'history'"
        @settings="openSettings"
        @mosaic="screen = 'mosaic'"
        @logout="handleLogout"
      />
      <MosaicView
        v-else-if="screen === 'mosaic'"
        @back="screen = 'app'"
        @history="screen = 'history'"
        @settings="openSettings"
        @mosaic="screen = 'mosaic'"
        @logout="handleLogout"
      />

      <!-- Step 0: Login -->
      <LoginView v-else-if="step === 0" @success="step = 1" />

      <!-- Step 1: Compose -->
      <ComposeView v-else-if="step === 1" @share="handleShare" />

      <!-- Step 2: Scanning -->
      <div v-else-if="step === 2" class="app-screen align-items-center justify-content-center text-center p-4">
        <div class="scan-mascot mb-3" role="status" aria-label="Scanning">
          <svg v-if="scanMascot === 'camera'" class="scan-mascot-icon" viewBox="0 0 96 96" aria-hidden="true">
            <rect class="scan-camera-body" x="18" y="28" width="60" height="42" rx="12" />
            <path class="scan-camera-top" d="M36 28l5-8h16l5 8" />
            <circle class="scan-camera-lens" cx="48" cy="49" r="14" />
            <circle class="scan-camera-dot" cx="66" cy="39" r="4" />
            <path class="scan-glint" d="M42 44c2.2-2.2 5.4-3.2 8.6-2.6" />
          </svg>
          <svg v-else-if="scanMascot === 'shield'" class="scan-mascot-icon" viewBox="0 0 96 96" aria-hidden="true">
            <path
              class="scan-shield"
              d="M48 8 76 18v25c0 18.5-11.5 34.8-28 42-16.5-7.2-28-23.5-28-42V18L48 8Z"
            />
            <path
              class="scan-shield-highlight"
              d="M48 16 68 23v19c0 13.5-7.6 25.8-20 32.5V16Z"
            />
            <circle class="scan-lens" cx="45" cy="43" r="13" />
            <path class="scan-handle" d="m55 53 13 13" />
            <path class="scan-glint" d="M39 38c2.2-2.2 5.4-3.2 8.6-2.6" />
          </svg>
          <svg v-else-if="scanMascot === 'pencil'" class="scan-mascot-icon" viewBox="0 0 96 96" aria-hidden="true">
            <path class="scan-pencil-body" d="M25 66 62 29l13 13-37 37-17 4 4-17Z" />
            <path class="scan-pencil-tip" d="m21 83 4-17 13 13-17 4Z" />
            <path class="scan-pencil-eraser" d="m62 29 7-7c2.4-2.4 6.2-2.4 8.6 0l4.4 4.4c2.4 2.4 2.4 6.2 0 8.6l-7 7-13-13Z" />
            <path class="scan-pencil-line" d="M32 66 62 36" />
          </svg>
          <svg v-else-if="scanMascot === 'magnifier'" class="scan-mascot-icon" viewBox="0 0 96 96" aria-hidden="true">
            <circle class="scan-magnifier-lens" cx="42" cy="40" r="22" />
            <path class="scan-magnifier-handle" d="m58 57 19 19" />
            <path class="scan-magnifier-scan" d="M30 41h24M36 32h13M36 50h9" />
          </svg>
          <svg v-else class="scan-mascot-icon" viewBox="0 0 96 96" aria-hidden="true">
            <rect class="scan-phone-body" x="28" y="10" width="40" height="76" rx="12" />
            <rect class="scan-phone-screen" x="34" y="20" width="28" height="50" rx="5" />
            <circle class="scan-phone-button" cx="48" cy="77" r="3" />
            <path class="scan-phone-scan" d="M39 37h18M39 46h14M39 55h10" />
          </svg>
          <span class="scan-mascot-shadow" aria-hidden="true"></span>
          <span class="visually-hidden">Scanning…</span>
        </div>
        <p class="fw-bold mb-1">Scanning your post<span class="scan-dot">.</span><span class="scan-dot">.</span><span class="scan-dot">.</span></p>
        <div v-if="quickTeachTip" class="mt-3 text-center">
          <p class="small mb-0 bold-note">{{ quickTeachTip }}</p>
        </div>
      </div>

      <!-- Step 3: Results -->
      <ResultsView
        v-else-if="step === 3"
        :photo-url="photoPreviewUrl"
        :detections="detections"
        :teachable-moment="teachableMoment"
        :mosaic-risk="mosaicRisk"
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
