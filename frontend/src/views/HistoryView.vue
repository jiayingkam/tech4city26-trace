<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import HamburgerMenu from '../components/HamburgerMenu.vue'
import QuarantineView from './QuarantineView.vue'
import RemediationView from './RemediationView.vue'
import PostDetailView from './PostDetailView.vue'
import {
  getHistory,
  deleteHistoryItems,
  getDraftThumbnail,
  getMe,
  getDetections,
  getTeachableMoment,
  resumeRemediation,
} from '../api'

defineEmits(['back', 'history', 'settings', 'mosaic', 'logout'])

// Tapping a quarantined post takes over the whole screen with the same
// "held for review" / "clean up" flow used right after scanning — reused
// as-is rather than rebuilt, so Edit/Reject/Delete behave identically here
// and from the compose flow.
const activePost = ref(null)
const subScreen = ref(null) // null | 'quarantine' | 'remediate' | 'detail'
const activeRemediation = ref(null)
const activeDetections = ref([])
const activeTeachableMoment = ref(null)

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

// Accepted/rejected posts are closed records — nothing left to decide, just
// a read-only look at what was found, how it was resolved, and why it
// mattered (same teachable-moment lesson shown right after the original scan).
async function openClosedPost(post) {
  activePost.value = post
  error.value = ''
  try {
    activeDetections.value = await getDetections(post.draft_id)
    subScreen.value = 'detail'
    try {
      activeTeachableMoment.value = await getTeachableMoment(post.draft_id)
    } catch {
      activeTeachableMoment.value = null
    }
  } catch (err) {
    error.value = err.message || 'Could not load this post.'
    activePost.value = null
  }
}

function closeSubScreen() {
  activePost.value = null
  subScreen.value = null
  activeRemediation.value = null
  activeDetections.value = []
  activeTeachableMoment.value = null
  // Post status changed — privacy score may have shifted.
  window.__mosaicCache = null
  load()
}

const STATUS_LABELS = {
  accepted: 'Accepted',
  rejected: 'Rejected',
  quarantined: 'Quarantined',
  pending: 'Pending',
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
const retryStatus = ref('')
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
let longPressFired = false
const LONG_PRESS_MS = 500

function startLongPress(draftId) {
  clearLongPress()
  longPressFired = false
  longPressTimer = setTimeout(() => {
    longPressFired = true
    swipeOpenId.value = null
    selectionMode.value = true
    toggleSelected(draftId)
  }, LONG_PRESS_MS)
}
function clearLongPress() {
  if (longPressTimer) clearTimeout(longPressTimer)
  longPressTimer = null
}

// ── Swipe-to-delete ──────────────────────────────────────────────────────
// Each card can be dragged left to reveal a Delete action, iOS-list style.
// The same pointer stream also drives tap (open the post) and long-press
// (enter multi-select), so all three gestures are resolved here rather than
// via a separate @click.
const swipeOpenId = ref(null) // draft_id of the card currently swiped open
const drag = ref({ id: null, startX: 0, startY: 0, dx: 0, mode: null })
const SWIPE_WIDTH = 76 // px the card slides to expose Delete
const SWIPE_TRIGGER = 45 // px past which release snaps open
const TAP_SLOP = 8 // px of movement still treated as a tap

function onCardPointerDown(post, e) {
  drag.value = { id: post.draft_id, startX: e.clientX, startY: e.clientY, dx: 0, mode: null }
  startLongPress(post.draft_id)
  try { e.currentTarget.setPointerCapture(e.pointerId) } catch { /* older browsers */ }
}
function onCardPointerMove(e) {
  const d = drag.value
  if (!d.id) return
  const dx = e.clientX - d.startX
  const dy = e.clientY - d.startY
  if (d.mode === null) {
    // Decide gesture: horizontal past the slop = swipe; vertical = let it scroll.
    if (!selectionMode.value && Math.abs(dx) > TAP_SLOP && Math.abs(dx) > Math.abs(dy)) {
      d.mode = 'swipe'
      clearLongPress()
    } else if (Math.abs(dy) > TAP_SLOP) {
      d.mode = 'scroll'
      clearLongPress()
    }
  }
  if (d.mode === 'swipe') {
    const base = swipeOpenId.value === d.id ? -SWIPE_WIDTH : 0
    d.dx = Math.min(0, Math.max(-SWIPE_WIDTH, base + dx))
  }
}
function onCardPointerUp(post) {
  const d = drag.value
  clearLongPress()
  if (longPressFired) {
    // long-press already entered selection + toggled this card
  } else if (d.mode === 'swipe') {
    swipeOpenId.value = d.dx <= -SWIPE_TRIGGER ? post.draft_id : null
  } else if (d.mode === null) {
    // A tap. If a card is swiped open, first tap just closes it.
    if (swipeOpenId.value) {
      swipeOpenId.value = null
    } else {
      handleCardTap(post)
    }
  }
  drag.value = { id: null, startX: 0, startY: 0, dx: 0, mode: null }
}
function onCardPointerCancel() {
  clearLongPress()
  drag.value = { id: null, startX: 0, startY: 0, dx: 0, mode: null }
}

function cardStyle(draftId) {
  const d = drag.value
  const dragging = d.id === draftId && d.mode === 'swipe'
  const x = dragging ? d.dx : (swipeOpenId.value === draftId ? -SWIPE_WIDTH : 0)
  return {
    transform: `translateX(${x}px)`,
    transition: dragging ? 'none' : 'transform 0.2s ease',
  }
}

function enterSelection() {
  swipeOpenId.value = null
  selectionMode.value = true
}
function handleCardTap(post) {
  // Once in selection mode, a plain tap toggles selection instead of
  // needing another long-press for every subsequent card. Otherwise every
  // card opens something: quarantined/pending have something left to
  // decide, accepted/rejected just show a read-only detail view.
  if (selectionMode.value) {
    toggleSelected(post.draft_id)
  } else if (post.status === 'quarantined') {
    openQuarantinedPost(post)
  } else if (post.status === 'pending') {
    openPendingPost(post)
  } else {
    openClosedPost(post)
  }
}
function toggleSelected(draftId) {
  const next = new Set(selectedIds.value)
  if (next.has(draftId)) {
    next.delete(draftId)
  } else {
    next.add(draftId)
  }
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
  retryStatus.value = ''
  error.value = ''
  cancelSelection()
  revokeThumbnails()
  try {
    // A backend service that's still waking its database from idle can take
    // a while to respond — surface that as a retry count instead of leaving
    // "Loading…" up with nothing to suggest it isn't just stuck.
    posts.value = await getHistory(activeTab.value, (attempt, total) => {
      retryStatus.value = `Still waking up the server, this can take a minute… (${attempt}/${total})`
    })
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
    retryStatus.value = ''
  }
}

watch(activeTab, load)

// Drives cooldownRemaining below — Date.now() on its own isn't reactive, so
// without this the countdown next to a quarantined card would only update
// on the next unrelated re-render (switching tabs, deleting, etc.) instead
// of ticking down live, same live-countdown approach as QuarantineView.
const now = ref(Date.now())
let clock
onMounted(async () => {
  load()
  clock = setInterval(() => { now.value = Date.now() }, 1000)
  try {
    retentionMode.value = (await getMe()).retention_mode
  } catch {
    // Non-critical — the status line just stays blank if this fails.
  }
})
onBeforeUnmount(() => {
  revokeThumbnails()
  clearInterval(clock)
})

async function deleteSingle(draftId) {
  swipeOpenId.value = null
  deleting.value = true
  error.value = ''
  try {
    await deleteHistoryItems({ draftIds: [draftId] })
    await load()
  } catch (err) {
    error.value = err.message || 'Could not delete this post.'
  } finally {
    deleting.value = false
  }
}

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
  const ms = new Date(post.cooldown_expiry).getTime() - now.value
  if (ms <= 0) return '0:00 left'
  const m = Math.floor(ms / 60000)
  const s = Math.floor((ms % 60000) / 1000)
  return `${m}:${String(s).padStart(2, '0')} left`
}
</script>

<template>
  <!-- These sub-screens take over the whole view, same as the compose
       flow's own steps — so they need their own hamburger overlay too,
       since they don't fall through to this file's own header below. -->
  <HamburgerMenu
    v-if="subScreen"
    @history="$emit('history')"
    @settings="$emit('settings')"
    @mosaic="$emit('mosaic')"
    @logout="$emit('logout')"
  />

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
  <PostDetailView
    v-else-if="subScreen === 'detail'"
    :post="activePost"
    :photo-url="thumbnails[activePost.draft_id]"
    :detections="activeDetections"
    :teachable-moment="activeTeachableMoment"
    @restart="closeSubScreen"
  />

  <div v-else class="app-screen">
    <div class="app-header">
      <HamburgerMenu @history="$emit('history')" @settings="$emit('settings')" @mosaic="$emit('mosaic')" @logout="$emit('logout')" />
      <button
        v-if="posts.length"
        class="header-select-btn"
        @click="selectionMode ? cancelSelection() : enterSelection()"
      >
        {{ selectionMode ? 'Done' : 'Select' }}
      </button>
      <h1 class="app-title">History</h1>
      <p class="app-subtitle">Review past scans and cleanups.</p>
    </div>

    <div class="history-tabs">
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

    <div class="app-content">
      <p v-if="retentionMode" class="text-center soft-note mb-3">
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

      <div v-if="loading" class="empty-state">{{ retryStatus || 'Loading…' }}</div>
      <p v-else-if="error" class="text-danger small d-flex align-items-center gap-2">
        {{ error }}
        <button class="btn btn-link btn-sm p-0 text-danger" title="Retry" @click="load">🔄</button>
      </p>
      <div v-else-if="posts.length === 0" class="empty-state trace-card">Nothing here yet.</div>

      <div
        v-for="post in posts"
        :key="post.draft_id"
        class="post-swipe-wrap mb-3"
      >
        <!-- Revealed behind the card when it's swiped left -->
        <button
          v-if="!selectionMode"
          class="swipe-delete"
          :disabled="deleting"
          aria-label="Delete post"
          @click.stop="deleteSingle(post.draft_id)"
        >
          Delete
        </button>
        <div
          class="post-card"
          :class="{ selected: selectedIds.has(post.draft_id), tappable: !selectionMode }"
          :style="cardStyle(post.draft_id)"
          @pointerdown="onCardPointerDown(post, $event)"
          @pointermove="onCardPointerMove($event)"
          @pointerup="onCardPointerUp(post)"
          @pointercancel="onCardPointerCancel()"
        >
          <div class="d-flex justify-content-between align-items-start">
            <div>
              <div class="soft-note">{{ formatDateTime(post.captured_at) }}</div>
              <div class="fw-semibold" :class="`status-${post.status}`">
                {{ STATUS_LABELS[post.status] }}
                <span v-if="post.status === 'quarantined'" class="text-muted small fw-normal">
                  {{ cooldownRemaining(post) }}
                </span>
              </div>
              <div class="small text-muted mt-1">{{ post.summary }}</div>
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
    </div>

    <div class="app-action-bar">
      <button class="btn btn-outline-secondary w-100" @click="$emit('back')">Back</button>
    </div>
  </div>
</template>

<style scoped>
.tab-btn {
  border: none;
  background: transparent;
  padding: 10px 6px;
  font-size: 0.8rem;
  color: var(--trace-muted);
  border-bottom: 2px solid transparent;
}
.tab-btn.active {
  color: var(--trace-primary);
  border-bottom-color: var(--trace-primary);
  font-weight: 800;
}
.history-tabs {
  display: flex;
  border-bottom: 1px solid var(--trace-line);
  background: #fff;
}
.header-select-btn {
  position: absolute;
  top: 16px;
  right: 14px;
  z-index: 2;
  background: transparent;
  border: none;
  padding: 4px 6px;
  font-size: 0.85rem;
  font-weight: 700;
  color: var(--trace-primary, #2f6fed);
}
.post-swipe-wrap {
  position: relative;
  border-radius: 14px;
  overflow: hidden;
}
.swipe-delete {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  width: 76px;
  border: none;
  background: var(--trace-danger, #d94841);
  color: #fff;
  font-size: 0.85rem;
  font-weight: 700;
}
.post-card {
  position: relative;
  z-index: 1;
  border: 1px solid var(--trace-line);
  border-radius: 14px;
  padding: 14px;
  background: #fff;
  user-select: none;
  /* pan-y lets the list scroll vertically while we own horizontal swipes */
  touch-action: pan-y;
}
.post-card.selected {
  border-color: var(--trace-primary);
  background: #f3f7ff;
}
.post-card.tappable {
  cursor: pointer;
  border-color: rgba(47, 111, 237, 0.45);
}
.status-accepted { color: var(--trace-success); }
.status-rejected { color: var(--trace-danger); }
.status-quarantined { color: #936509; }
.status-pending { color: var(--trace-primary-dark); }
.thumb {
  width: 56px;
  height: 56px;
  border-radius: 12px;
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
