<script setup>
import { computed, ref } from 'vue'
import { downloadRemediated, sendTeachableMomentChat } from '../api'
import TeachableChatPanel from '../components/TeachableChatPanel.vue'

const props = defineProps({
  post: { type: Object, required: true },
  photoUrl: { type: String, default: null },
  detections: { type: Array, default: () => [] },
  teachableMoment: { type: Object, default: null },
})
defineEmits(['restart'])

const CATEGORY_LABELS = {
  face: 'Face',
  location: 'Location detail',
  document: 'Identifying document',
  financial: 'Financial detail',
  contact: 'Contact detail',
  credentials: 'Password or access code',
  metadata: 'Hidden location metadata',
}

const RESOLUTION_LABELS = { accepted: 'Accepted', rejected: 'Rejected' }
const STATUS_LABELS = { accepted: 'Accepted', rejected: 'Rejected', quarantined: 'Quarantined', pending: 'Pending' }

function detectionLabel(d) {
  return d.detail || CATEGORY_LABELS[d.category] || d.category
}

function formatDateTime(iso) {
  const d = new Date(iso)
  const pad = (n) => String(n).padStart(2, '0')
  return `${pad(d.getDate())}/${pad(d.getMonth() + 1)}/${d.getFullYear()}  ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

// A cleaned copy only exists once remediate_content's confirm step has
// actually run for this draft — the only place that ever sets a detection's
// resolution to "accepted" (release-as-is and cancel/reject both leave
// every detection at "rejected", never "accepted"). Checking that first
// means the request is only made when a file is actually expected to exist,
// instead of firing a fetch that's guaranteed to 400 and showing up as a
// (harmless) network error in the console for every rejected/never-fixed post.
const cleanedUrl = ref(null)
if (props.post.has_image && props.detections.some((d) => d.resolution === 'accepted')) {
  downloadRemediated(props.post.draft_id)
    .then((blob) => { cleanedUrl.value = URL.createObjectURL(blob) })
    .catch(() => {})
}

const displayUrl = computed(() => cleanedUrl.value || props.photoUrl)

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
      <h1 class="app-title">Post details</h1>
      <p class="app-subtitle">{{ formatDateTime(post.captured_at) }}</p>
    </div>

    <div class="app-content">
      <img v-if="displayUrl" :src="displayUrl" class="w-100 rounded mb-2" alt="Your photo" />
      <p v-if="cleanedUrl" class="status-chip safe mx-auto mb-3">Cleaned version</p>

      <p class="status-chip mb-3" :class="post.status === 'rejected' ? 'danger' : 'safe'">
        {{ STATUS_LABELS[post.status] || 'Pending' }}
      </p>

      <p v-if="post.caption" class="small mb-3">{{ post.caption }}</p>

      <div v-if="detections.length" class="finding-panel mb-3">
        <p class="fw-bold small mb-2">What was found</p>
        <ul class="list-unstyled small mb-0">
          <li v-for="d in detections" :key="d.detection_id" class="finding-row">
            <span>{{ detectionLabel(d) }}</span>
            <span class="small fw-semibold" :class="d.resolution === 'rejected' ? 'text-danger' : 'text-success'">
              {{ RESOLUTION_LABELS[d.resolution] || 'Pending' }}
            </span>
          </li>
        </ul>
      </div>
      <div v-else class="empty-state trace-card">
        <p class="soft-note mb-0">No sensitive content was flagged on this post.</p>
      </div>

      <div v-if="teachableMoment" class="coach-card mt-3">
        <p class="eyebrow mb-1">Why this matters</p>
        <p class="fw-semibold mb-1">{{ teachableMoment.title }}</p>
        <p class="small mb-2">{{ teachableMoment.explanation }}</p>
        <p class="small mb-0"><strong>Safer move:</strong> {{ teachableMoment.safer_action }}</p>

        <div class="chat-section mt-3">
          <button
            type="button"
            class="chat-expand-btn"
            aria-label="Expand chat"
            @click="chatExpanded = true"
          >⤢</button>
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
      <button class="btn btn-outline-secondary w-100" @click="$emit('restart')">Back</button>
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
.finding-panel {
  padding: 12px 14px;
  border: 1px solid var(--trace-line);
  border-radius: 14px;
  background: #fff;
}
.finding-row {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  padding: 6px 0;
  border-top: 1px solid #eef2f7;
}
.finding-row:first-child {
  border-top: 0;
}
.status-chip.danger {
  background: #fbeceb;
  color: var(--trace-danger);
}
.chat-section {
  position: relative;
  border-top: 1px solid var(--trace-line);
  padding-top: 10px;
}
.chat-expand-btn {
  position: absolute;
  top: -4px;
  right: 0;
  background: none;
  border: none;
  font-size: 1.05rem;
  line-height: 1;
  color: #667085;
  padding: 4px 6px;
  cursor: pointer;
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
