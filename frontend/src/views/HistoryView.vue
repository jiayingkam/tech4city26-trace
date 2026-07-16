<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import HamburgerMenu from '../components/HamburgerMenu.vue'
import QuarantineView from './QuarantineView.vue'
import RemediationView from './RemediationView.vue'
import { getHistory, deleteHistoryItems, getDraftThumbnail, getMe, getDetections, resumeRemediation } from '../api'

defineEmits(['back', 'history', 'settings', 'logout'])

// Tapping a quarantined post takes over the whole screen with the same
// "held for review" / "clean up" flow used right after scanning — reused
// as-is rather than rebuilt, so Edit/Reject/Delete behave identically here
// and from the compose flow.
const activePost = ref(null)
const subScreen = ref(null) // null | 'quarantine' | 'remediate'
const activeRemediation = ref(null)
const activeDetections = ref([])

function openQuarantinedPost(post) {
  activePost.value = post
  subScreen.value = 'quarantine'
}

async function handleQuarantineEdit(remediation) {
  activeRemediation.value = remediation
  try {
    activeDetections.value = await getDetections(activePost.value.draft_id)
  } catch {
    activeDetections.value = []
  }
  subScreen.value = 'remediate'
}

// A "Pending" post was already scanned and proposed, just never confirmed
// or dismissed — it was never quarantined, so this skips straight to the
// clean-up screen instead of the "held for review" one.
async function openPendingPost(post) {
  activePost.value = post
  error.value = ''
  try {
    const [remediation, detections] = await Promise.all([
      resumeRemediation(post.draft_id),
      getDetections(post.draft_id),
    ])
    activeRemediation.value = remediation
    activeDetections.value = detections
    subScreen.value = 'remediate'
  } catch (err) {
    error.value = err.message || 'Could not resume this post.'
    activePost.value = null
  }
}

function closeSubScreen() {
  activePost.value = null
  subScreen.value = null
  activeRemediation.value = null
  activeDetections.value = []
  load() // the post's status likely just changed (edited/released/deleted)
}

const STATUS_LABELS = {
  accepted: 'Accepted',
  rejected: 'Rejected',
  quarantined: 'Quarantined',
  pending: 'Pending',
}

// Quarantined and pending are the two statuses with something left to
// decide — everything else (accepted/rejected) is a closed record.
function isTappable(post) {
  return post.status === 'quarantined' || post.status === 'pending'
}

const TABS = [
  { key: 'all', label: 'All' },
  { key: 'accepted', label: 'Accepted' },
  { key: 'rejected', label: 'Rejected' },
  { key: 'quarantined', label: 'Quarantined' },
  { key: 'pending', label: 'Pending' },
]

const activeTab = ref('all')
const posts = ref([])
const thumbnails = ref({}) // draft_id -> blob url
const loading = ref(false)
const error = ref('')
const deleting = ref(false)
const retentionMode = ref(null)

// Selection is only reachable via long-press, not always-visible checkboxes
// — matches a "tap to view, long-press to manage" mobile pattern instead of
// permanently cluttering every card with a checkbox.
const selectionMode = ref(false)
const selectedIds = ref(new Set())
const allSelected = computed(() => posts.value.length > 0 && selectedIds.value.size === posts.value.length)

let longPressTimer = null
const LONG_PRESS_MS = 500

function startLongPress(draftId) {
  clearLongPress()
  longPressTimer = setTimeout(() => {
    selectionMode.value = true
    toggleSelected(draftId)
  }, LONG_PRESS_MS)
}
function clearLongPress() {
  if (longPressTimer) clearTimeout(longPressTimer)
  longPressTimer = null
}
function handleCardTap(post) {
  // Once in selection mode, a plain tap toggles selection instead of
  // needing another long-press for every subsequent card. Otherwise, only
  // the two statuses with something left to decide are tappable.
  if (selectionMode.value) {
    toggleSelected(post.draft_id)
  } else if (post.status === 'quarantined') {
    openQuarantinedPost(post)
  } else if (post.status === 'pending') {
    openPendingPost(post)
  }
}
function toggleSelected(draftId) {
  const next = new Set(selectedIds.value)
  next.has(draftId) ? next.delete(draftId) : next.add(draftId)
  selectedIds.value = next
}
function toggleSelectAll() {
  selectedIds.value = allSelected.value ? new Set() : new Set(posts.value.map((p) => p.draft_id))
}
function cancelSelection() {
  selectionMode.value = false
  selectedIds.value = new Set()
}

function revokeThumbnails() {
  for (const url of Object.values(thumbnails.value)) URL.revokeObjectURL(url)
  thumbnails.value = {}
}

async function load() {
  loading.value = true
  error.value = ''
  cancelSelection()
  revokeThumbnails()
  try {
    posts.value = await getHistory(activeTab.value)
    const entries = await Promise.all(
      posts.value
        .filter((p) => p.has_image)
        .map(async (p) => [p.draft_id, await getDraftThumbnail(p.draft_id)])
    )
    thumbnails.value = Object.fromEntries(entries.filter(([, url]) => url))
  } catch (err) {
    error.value = err.message || 'Could not load your history.'
  } finally {
    loading.value = false
  }
}

watch(activeTab, load)
onMounted(async () => {
  load()
  try {
    retentionMode.value = (await getMe()).retention_mode
  } catch {
    // Non-critical — the status line just stays blank if this fails.
  }
})
onBeforeUnmount(revokeThumbnails)

async function deleteSelected() {
  if (selectedIds.value.size === 0) return
  deleting.value = true
  error.value = ''
  try {
    await deleteHistoryItems({ draftIds: [...selectedIds.value] })
    await load()
  } catch (err) {
    error.value = err.message || 'Could not delete the selected posts.'
  } finally {
    deleting.value = false
  }
}

function formatDateTime(iso) {
  const d = new Date(iso)
  const pad = (n) => String(n).padStart(2, '0')
  return `${pad(d.getDate())}/${pad(d.getMonth() + 1)}/${d.getFullYear()}  ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

function cooldownRemaining(post) {
  if (post.status !== 'quarantined' || !post.cooldown_expiry) return ''
  const ms = new Date(post.cooldown_expiry).getTime() - Date.now()
  if (ms <= 0) return '0:00 left'
  const m = Math.floor(ms / 60000)
  const s = Math.floor((ms % 60000) / 1000)
  return `${m}:${String(s).padStart(2, '0')} left`
}
</script>

<template>
  <!-- Reviewing a quarantined post takes over the whole screen, same as the
       compose flow's own step 4 -->
  <QuarantineView
    v-if="subScreen === 'quarantine'"
    :quarantine="activePost"
    :photo-url="thumbnails[activePost.draft_id]"
    @restart="closeSubScreen"
    @edit="handleQuarantineEdit"
  />
  <RemediationView
    v-else-if="subScreen === 'remediate'"
    :draft-id="activePost.draft_id"
    :remediation="activeRemediation"
    :photo-url="thumbnails[activePost.draft_id]"
    :detections="activeDetections"
    @restart="closeSubScreen"
  />

  <div v-else class="d-flex flex-column h-100">
    <div class="border-bottom p-3 text-center fw-bold position-relative">
      <HamburgerMenu @history="$emit('history')" @settings="$emit('settings')" @logout="$emit('logout')" />
      History
    </div>

    <div class="d-flex border-bottom">
      <button
        v-for="tab in TABS"
        :key="tab.key"
        class="tab-btn flex-fill"
        :class="{ active: activeTab === tab.key }"
        @click="activeTab = tab.key"
      >
        {{ tab.label }}
      </button>
    </div>

    <div class="p-3 flex-grow-1 overflow-auto">
      <p v-if="retentionMode" class="text-center text-muted small fst-italic mb-3">
        Auto-delete after 3 months: {{ retentionMode === 'auto_expire' ? 'On' : 'Off' }}
      </p>

      <div v-if="selectionMode" class="d-flex align-items-center justify-content-between mb-2">
        <div class="form-check mb-0">
          <input
            id="select-all"
            class="form-check-input"
            type="checkbox"
            :checked="allSelected"
            @change="toggleSelectAll"
          />
          <label class="form-check-label small" for="select-all">Select All</label>
        </div>
        <div class="d-flex align-items-center gap-3">
          <button class="btn btn-link btn-sm p-0 text-muted" @click="cancelSelection">Cancel</button>
          <button
            class="btn btn-link btn-sm p-0 text-danger fs-5"
            :disabled="deleting || selectedIds.size === 0"
            aria-label="Delete selected"
            @click="deleteSelected"
          >
            🗑
          </button>
        </div>
      </div>

      <div v-if="loading" class="text-center text-muted small py-4">Loading…</div>
      <p v-else-if="error" class="text-danger small">{{ error }}</p>
      <div v-else-if="posts.length === 0" class="text-center text-muted small py-4">Nothing here yet.</div>

      <div
        v-for="post in posts"
        :key="post.draft_id"
        class="post-card mb-3"
        :class="{ selected: selectedIds.has(post.draft_id), tappable: isTappable(post) && !selectionMode }"
        @pointerdown="startLongPress(post.draft_id)"
        @pointerup="clearLongPress"
        @pointerleave="clearLongPress"
        @click="handleCardTap(post)"
      >
        <div class="d-flex justify-content-between align-items-start">
          <div>
            <div class="small">{{ formatDateTime(post.captured_at) }}</div>
            <div class="fw-semibold" :class="`status-${post.status}`">
              {{ STATUS_LABELS[post.status] }}
              <span v-if="post.status === 'quarantined'" class="text-muted small fw-normal">
                {{ cooldownRemaining(post) }}
              </span>
            </div>
            <div class="small fst-italic text-muted mt-1">{{ post.summary }}</div>
          </div>
          <img v-if="thumbnails[post.draft_id]" :src="thumbnails[post.draft_id]" class="thumb" alt="" />
          <div v-else class="thumb thumb-placeholder">🖼</div>
        </div>
        <div v-if="selectionMode" class="form-check position-absolute select-checkbox">
          <input
            class="form-check-input"
            type="checkbox"
            :checked="selectedIds.has(post.draft_id)"
            @click.stop
            @change="toggleSelected(post.draft_id)"
          />
        </div>
      </div>
    </div>

    <div class="p-3 border-top">
      <button class="btn btn-outline-secondary w-100" @click="$emit('back')">Back</button>
    </div>
  </div>
</template>

<style scoped>
.tab-btn {
  border: none;
  background: none;
  padding: 8px 4px;
  font-size: 0.8rem;
  color: #6c757d;
  border-bottom: 2px solid transparent;
}
.tab-btn.active {
  color: #0d6efd;
  border-bottom-color: #0d6efd;
  font-weight: 600;
}
.post-card {
  position: relative;
  border: 1px solid #dee2e6;
  border-radius: 10px;
  padding: 12px 14px;
  user-select: none;
  touch-action: manipulation;
}
.post-card.selected {
  border-color: #0d6efd;
  background: rgba(13, 110, 253, 0.05);
}
.post-card.tappable {
  cursor: pointer;
  border-color: #0d6efd;
}
.status-accepted { color: #198754; }
.status-rejected { color: #dc3545; }
.status-quarantined { color: #b8860b; }
.status-pending { color: #6c757d; }
.thumb {
  width: 56px;
  height: 56px;
  border-radius: 8px;
  object-fit: cover;
  flex-shrink: 0;
}
.thumb-placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f1f3f5;
  font-size: 1.3rem;
}
.select-checkbox {
  top: 10px;
  right: 10px;
}
</style>
