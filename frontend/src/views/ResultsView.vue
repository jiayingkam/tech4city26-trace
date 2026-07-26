<script setup>
import { ref, computed } from 'vue'
import { sendTeachableMomentChat } from '../api'
import TeachableChatPanel from '../components/TeachableChatPanel.vue'

const props = defineProps({
  photoUrl: { type: String, default: null },
  contentType: { type: String, default: 'image' },
  detections: { type: Array, default: () => [] },
  // scan_draft's process outcome's `remediation` field — for a video draft
  // this is where a caption redaction suggestion (if any) lives, since video
  // findings never reach step 4's blur editor (see the "Done" button below).
  remediation: { type: Object, default: null },
  teachableMoment: { type: Object, default: null },
  mosaicRisk: { type: Object, default: null },
})

defineEmits(['restart', 'continue'])

const CATEGORY_LABELS = {
  location: 'Location detail',
  document: 'Identifying document',
  financial: 'Financial detail',
  contact: 'Contact detail',
  credentials: 'Password or access code',
}

// Bounding boxes come back in pixels against the *original* image's
// dimensions — the on-screen <img> is rendered at whatever size fits the
// phone frame, so boxes have to be rescaled by that ratio to land correctly.
const imgEl = ref(null)
const scale = ref(1)

function onImageLoad() {
  if (!imgEl.value) return
  scale.value = imgEl.value.clientWidth / imgEl.value.naturalWidth
}

function boxStyle(region) {
  return {
    left: `${region.x * scale.value}px`,
    top: `${region.y * scale.value}px`,
    width: `${region.w * scale.value}px`,
    height: `${region.h * scale.value}px`,
  }
}

const imageFindings = computed(() =>
  props.detections.filter((d) => d.source_type === 'image' && d.bounding_region)
)
const metadataFindings = computed(() => props.detections.filter((d) => d.category === 'metadata'))
const textFindings = computed(() => props.detections.filter((d) => d.source_type === 'text'))
const hasFindings = computed(() => props.detections.length > 0)

const isVideo = computed(() => props.contentType === 'video')

// Sorted by when each thing appears, so the list reads top-to-bottom the
// same way the clip plays — unlike image findings, a time_range only makes
// a moment on a shared timeline meaningful once findings are put in order.
const videoFindings = computed(() =>
  [...props.detections]
    .filter((d) => d.source_type === 'video' && d.time_range)
    .sort((a, b) => a.time_range.start - b.time_range.start)
)

const videoEl = ref(null)

function formatTime(seconds) {
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${String(s).padStart(2, '0')}`
}

function seekTo(seconds) {
  if (!videoEl.value) return
  videoEl.value.currentTime = seconds
  videoEl.value.play()
}

const captionSuggestion = computed(() => props.remediation?.text_redaction || null)
const copyState = ref('idle') // 'idle' | 'copied'

async function copySuggestedCaption() {
  if (!captionSuggestion.value) return
  await navigator.clipboard.writeText(captionSuggestion.value.suggested_caption)
  copyState.value = 'copied'
  setTimeout(() => { copyState.value = 'idle' }, 2000)
}

const chatMessages = ref([])
const chatInput = ref('')
const chatLoading = ref(false)
const chatError = ref(null)
const chatExpanded = ref(false)

async function sendChat(text) {
  const message = (text ?? chatInput.value).trim()
  if (!message || chatLoading.value) return

  // History is everything *before* this new turn — pushed first so the
  // slice below stays correct regardless of when the request resolves.
  const history = chatMessages.value.slice()
  chatMessages.value.push({ role: 'user', content: message })
  chatInput.value = ''
  chatError.value = null
  chatLoading.value = true
  try {
    const { reply } = await sendTeachableMomentChat(props.teachableMoment.draft_id, message, history)
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
      <h1 class="app-title">Scan results</h1>
      <p class="app-subtitle">{{ hasFindings ? 'A few details could use a second look.' : 'No personal details stood out.' }}</p>
    </div>

    <div class="app-content">
      <div v-if="photoUrl && isVideo" class="photo-wrap mb-3">
        <video ref="videoEl" :src="photoUrl" class="w-100 d-block" controls></video>
      </div>
      <div v-else-if="photoUrl" class="photo-wrap mb-3">
        <img ref="imgEl" :src="photoUrl" class="w-100 d-block" alt="Your photo" @load="onImageLoad" />
        <div
          v-for="(d, i) in imageFindings"
          :key="i"
          class="finding-box"
          :style="boxStyle(d.bounding_region)"
        >
          <span class="finding-label">{{ CATEGORY_LABELS[d.category] || d.category }}</span>
        </div>
      </div>

      <div v-if="!hasFindings" class="empty-state trace-card">
        <span class="status-chip safe">Looks clear</span>
        <p class="fw-bold mb-0">This post looks ready.</p>
        <p class="soft-note mb-0">Trace did not find faces, places, contact info, or hidden photo data.</p>
      </div>

      <template v-else>
        <div v-if="metadataFindings.length" class="finding-panel warn mb-3">
          <p class="status-chip warn mb-2">Hidden photo data</p>
          <div v-for="(d, i) in metadataFindings" :key="i" class="small">{{ d.detail }}</div>
        </div>

        <div v-if="imageFindings.length" class="finding-panel mb-3">
          <p class="fw-bold small mb-2">In your photo</p>
          <ul class="list-unstyled small mb-0">
            <li v-for="(d, i) in imageFindings" :key="i" class="mb-1">
              <strong>{{ CATEGORY_LABELS[d.category] || d.category }}:</strong> {{ d.detail }}
            </li>
          </ul>
        </div>

        <div v-if="videoFindings.length" class="finding-panel mb-3">
          <p class="fw-bold small mb-2">In your video</p>
          <ul class="list-unstyled small mb-0">
            <li v-for="(d, i) in videoFindings" :key="i" class="mb-2 d-flex align-items-start gap-2">
              <button type="button" class="btn btn-sm btn-outline-secondary timestamp-chip" @click="seekTo(d.time_range.start)">
                {{ formatTime(d.time_range.start) }}
              </button>
              <span><strong>{{ d.category === 'face' ? 'Face' : (CATEGORY_LABELS[d.category] || d.category) }}:</strong> {{ d.detail }}</span>
            </li>
          </ul>
        </div>

        <div v-if="textFindings.length" class="finding-panel mb-3">
          <p class="fw-bold small mb-2">In your caption</p>
          <ul class="list-unstyled small mb-0">
            <li v-for="(d, i) in textFindings" :key="i" class="mb-1">
              <strong>{{ d.category }}:</strong> {{ d.detail }}
            </li>
          </ul>
        </div>

        <div v-if="isVideo && captionSuggestion" class="finding-panel mb-3">
          <p class="fw-bold small mb-2">Suggested caption</p>
          <p class="small mb-2">{{ captionSuggestion.suggested_caption || '(empty)' }}</p>
          <button type="button" class="btn btn-sm btn-outline-secondary" @click="copySuggestedCaption">
            {{ copyState === 'copied' ? 'Copied!' : 'Copy suggested caption' }}
          </button>
        </div>

        <div v-if="teachableMoment" class="coach-card mt-3">
          <p class="eyebrow mb-1">Why this matters</p>
          <p class="fw-semibold mb-1">{{ teachableMoment.title }}</p>
          <p class="small mb-2">{{ teachableMoment.explanation }}</p>
          <p class="small mb-0"><span class="safer-label">Safer move:</span> {{ teachableMoment.safer_action }}</p>

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
      </template>

    </div>

    <div class="app-action-bar">
      <!-- Video has no pixel/frame editor (report-only for now — see
      remediate_content's video_detections handling): its findings are
      already resolved by the time this screen shows, so there's nothing
      for step 4's blur editor to do. Copying the caption suggestion above
      is the only action left, so this is just an acknowledgement. -->
      <button v-if="isVideo" class="btn btn-primary w-100" @click="$emit('restart')">Done</button>
      <template v-else>
        <button v-if="hasFindings" class="btn btn-primary w-100" @click="$emit('continue')">Fix the risky parts</button>
        <button class="btn btn-outline-secondary w-100" @click="$emit('restart')">Back</button>
      </template>
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
/* Ties the card's call-to-action to the teal eyebrow above it */
.safer-label {
  font-weight: 700;
  color: #247767;
}
.photo-wrap {
  position: relative;
  border-radius: 18px;
  overflow: hidden;
  line-height: 0;
  border: 1px solid var(--trace-line);
}
.finding-box {
  position: absolute;
  border: 2px solid var(--trace-coral);
  border-radius: 8px;
  pointer-events: none;
}
.finding-label {
  position: absolute;
  top: -1.4rem;
  left: 0;
  background: var(--trace-coral);
  color: #fff;
  font-size: 0.65rem;
  padding: 1px 6px;
  border-radius: 6px 6px 0 0;
  white-space: nowrap;
}
.finding-panel {
  padding: 12px 14px;
  border: 1px solid var(--trace-line);
  border-radius: 14px;
  background: #fff;
}
.finding-panel.warn {
  border-color: #f3d48b;
  background: #fffaf0;
}
.timestamp-chip {
  flex-shrink: 0;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
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
  display: flex;
  align-items: center;
  gap: 12px;
  padding-bottom: 12px;
  margin-bottom: 12px;
  border-bottom: 1px solid var(--trace-line);
}
.chat-back-btn {
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
}
</style>
