<script setup>
import { ref, computed, onMounted } from 'vue'
import { getMe, getExposureProfile, rebuildExposureProfile } from '../api'
import HamburgerMenu from '../components/HamburgerMenu.vue'

// Window-level cache — survives screen navigation AND Vite HMR module re-evaluation.
// Cleared on browser refresh (same semantics as a module-level variable in production).
const _key = '__mosaicCache'
const _getCache = () => (window[_key] ?? null)
const _setCache = (v) => { window[_key] = v }

defineEmits(['back', 'history', 'settings', 'mosaic', 'logout'])

// Pre-populate from cache synchronously so repeated visits never show the spinner.
const trajectory = ref(_getCache()?.trajectory || [])
const finalK = ref(_getCache()?.final_k || null)
const postCount = ref(_getCache()?.post_count || 0)
const typeSummary = ref(_getCache()?.type_summary || {})
const saves = ref(_getCache()?.saves || [])
const savedBits = ref(_getCache()?.saved_bits || 0)
const strangerInferences = ref(_getCache()?.stranger?.inferences || [])
const strangerConfidence = ref(_getCache()?.stranger?.overall_confidence || 0)
const loading = ref(!_getCache())
const error = ref(null)
const expandedDraftId = ref(null)

const TYPE_TIPS = {
  location: {
    label: 'Location details',
    tip: 'Try cropping out street signs, landmarks, and recognisable buildings before posting.',
  },
  temporal: {
    label: 'Routines & timing',
    tip: 'Avoid mentioning when you regularly go places — time patterns combined with location are powerful identifiers.',
  },
  affiliation: {
    label: 'Documents & affiliations',
    tip: 'Blur or crop IDs, school/work badges, and logos — they narrow your identity quickly.',
  },
  physical: {
    label: 'Physical appearance',
    tip: 'Describing your own appearance adds to your unique profile — be mindful of what you share about yourself.',
  },
  relation: {
    label: 'Contact details',
    tip: 'Avoid showing phone screens, business cards, or messages that reveal who you know.',
  },
  possession: {
    label: 'Financial & personal items',
    tip: 'Check for receipts, bank cards, or login screens before sharing photos.',
  },
}

const K_MAX = 6_000_000
const CIRCUMFERENCE = 2 * Math.PI * 48 // radius 48 inside 120×120 viewBox

function calcScore(k) {
  if (!k || k <= 0) return 0
  return Math.round(Math.log2(Math.max(k, 1)) / Math.log2(K_MAX) * 100)
}

// Score band → colour, shared by the gauge and the per-post breakdown.
function bandColor(s) {
  if (s >= 70) return '#198c68'
  if (s >= 40) return '#f4b740'
  return '#d94841'
}

// Per-post score — no behaviour-factor scaling, so this always matches the
// headline gauge exactly (both are plain calcScore on the same k values).
function postScore(point) {
  return Math.round(calcScore(point.k_after))
}
// Points this single post cost (negative) or added (positive).
function postScoreDelta(point) {
  return postScore(point) - Math.round(calcScore(point.k_before))
}

const score = computed(() => calcScore(finalK.value))

const scoreColor = computed(() => bandColor(score.value))

const scoreLabel = computed(() => {
  if (score.value >= 70) return 'Low risk'
  if (score.value >= 40) return 'Medium risk'
  return 'High risk'
})

const strokeOffset = computed(() => CIRCUMFERENCE * (1 - score.value / 100))

function formatK(k) {
  if (!k) return ''
  if (k >= 1_000_000) return `~${(k / 1_000_000).toFixed(1)}M`
  if (k >= 1_000) return `~${Math.round(k / 1_000)}K`
  return `~${k}`
}

function togglePost(draftId) {
  expandedDraftId.value = expandedDraftId.value === draftId ? null : draftId
}

function formatCapturedAt(value) {
  if (!value) return 'Unknown time'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'Unknown time'
  return date.toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

// Repeated posts cite the same phrase once per post — collapse duplicates and
// wrap each in quotes so it reads as a citation: based on "near the school".
function formatCitations(list) {
  return [...new Set(list || [])].map((c) => `“${c}”`).join(', ')
}

function applyCache(data) {
  trajectory.value = data.trajectory || []
  finalK.value = data.final_k
  postCount.value = data.post_count || 0
  typeSummary.value = data.type_summary || {}
  saves.value = data.saves || []
  savedBits.value = data.saved_bits || 0
  strangerInferences.value = data.stranger?.inferences || []
  strangerConfidence.value = data.stranger?.overall_confidence || 0
}

async function load(force = false) {
  if (_getCache() && !force) return  // refs already populated at init time
  loading.value = true
  error.value = null
  try {
    const user = await getMe()
    // One call to the materialized profile — trajectory, score, and stranger-view
    // all in a single stored blob (recomputed server-side only on a cache miss).
    const data = (await getExposureProfile(user.user_id)) || {}
    _setCache(data)
    applyCache(data)
  } catch (err) {
    error.value = err.message || 'Could not load privacy data.'
  } finally {
    loading.value = false
  }
}

// Unlike load(), this forces a server-side recompute so new posts / prompt
// changes show up — the stored profile is replaced, not just re-read.
async function refresh() {
  _setCache(null)
  loading.value = true
  error.value = null
  try {
    const user = await getMe()
    const data = (await rebuildExposureProfile(user.user_id)) || {}
    _setCache(data)
    applyCache(data)
  } catch (err) {
    error.value = err.message || 'Could not refresh privacy data.'
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="app-screen mosaic-screen">

    <div class="app-header">
      <HamburgerMenu @history="$emit('history')" @settings="$emit('settings')" @mosaic="$emit('mosaic')" @logout="$emit('logout')" />
      <h1 class="app-title">Privacy risk</h1>
      <p class="app-subtitle">How your posts add up over time.</p>
    </div>

    <div class="app-content">

      <div v-if="loading" class="d-flex flex-column align-items-center justify-content-center gap-2 py-5">
        <div class="spinner-border text-primary" role="status"></div>
        <p class="text-secondary small mb-0">Analysing your posts…</p>
      </div>

      <div v-else-if="error" class="text-center py-5">
        <p class="text-danger small">{{ error }}</p>
      </div>

      <div v-else-if="trajectory.length === 0" class="text-center py-5">
        <p class="text-secondary small">No published posts to analyse yet.</p>
      </div>

      <div v-else class="d-flex flex-column gap-3 mosaic-stack">

        <!-- Score gauge -->
        <div class="d-flex flex-column align-items-center gap-1 pt-2 pb-1 score-panel">
          <div class="score-wrap">
            <svg viewBox="0 0 120 120" class="score-svg">
              <circle cx="60" cy="60" r="48" fill="none" stroke="#e8edf5" stroke-width="10" stroke-linecap="round" />
              <circle
                cx="60" cy="60" r="48" fill="none"
                :stroke="scoreColor"
                stroke-width="10"
                stroke-linecap="round"
                :stroke-dasharray="CIRCUMFERENCE"
                :stroke-dashoffset="strokeOffset"
                transform="rotate(-90 60 60)"
              />
            </svg>
            <div class="score-overlay">
              <span class="score-num" :style="{ color: scoreColor }">{{ score }}</span>
              <span class="score-denom">/ 100</span>
            </div>
          </div>
          <p class="fw-bold small mb-0">Privacy Score
            <span class="score-risk-label" :style="{ color: scoreColor }">· {{ scoreLabel }}</span>
          </p>
        </div>

        <!-- What a stranger learns -->
        <div v-if="strangerInferences.length" class="stranger-card p-3 rounded-3">
          <div class="d-flex align-items-center justify-content-between mb-1 stranger-head">
            <p class="mb-0 small fw-bold stranger-title">🕵️ What a stranger could learn</p>
            <span class="stranger-conf">{{ strangerConfidence }}% confident</span>
          </div>
          <p class="mb-2 x-small stranger-sub">By combining your posts, someone could infer:</p>
          <div v-for="(inf, i) in strangerInferences" :key="i" class="stranger-row">
            <span class="stranger-dot" :class="`conf--${inf.confidence}`"></span>
            <div class="flex-grow-1">
              <p class="mb-0 small stranger-statement">{{ inf.statement }}</p>
              <p class="mb-0 stranger-cite">based on {{ formatCitations(inf.based_on) }}</p>
            </div>
            <span class="stranger-conf-tag" :class="`conf--${inf.confidence}`">{{ inf.confidence }}</span>
          </div>
        </div>

        <!-- Tips -->
        <div v-if="Object.keys(typeSummary).length" class="d-flex flex-column gap-2">
          <p class="small text-secondary mb-1 fw-semibold">What to watch out for</p>
          <div
            v-for="(count, kind) in typeSummary"
            :key="kind"
            class="tip-card p-2 rounded-3"
          >
            <p class="mb-0 small fw-semibold">
              {{ TYPE_TIPS[kind]?.label || kind }}
              <span class="tip-count">{{ count }} post{{ count === 1 ? '' : 's' }}</span>
            </p>
            <p class="mb-0 x-small text-secondary mt-1">{{ TYPE_TIPS[kind]?.tip }}</p>
          </div>
        </div>

        <!-- Privacy saves -->
        <div v-if="saves.length" class="saves-card p-3 rounded-3">
          <p class="mb-1 small fw-semibold saves-title">Privacy saves</p>
          <p class="mb-2 x-small text-secondary">
            You held back {{ saves.length }} high-risk post{{ saves.length === 1 ? '' : 's' }} before sharing.
            That protected roughly {{ formatK(Math.round(savedBits * 3.32)) }} people worth of anonymity.
          </p>
          <div v-for="s in saves" :key="s.draft_id" class="save-row x-small text-secondary mb-1">
            <span class="save-dot">●</span>
            {{ s.text_content || '(image only)' }}
          </div>
        </div>

        <!-- Post breakdown -->
        <div class="d-flex flex-column gap-2">
          <p class="small text-secondary mb-1 fw-semibold">Post breakdown</p>
          <div
            v-for="(point, i) in trajectory"
            :key="point.draft_id"
            class="post-card rounded-3"
          >
            <button
              type="button"
              class="post-toggle"
              :aria-expanded="expandedDraftId === point.draft_id"
              @click="togglePost(point.draft_id)"
            >
              <span class="post-num">{{ i + 1 }}</span>
              <span class="post-toggle-caption">{{ point.text_content || '(image only)' }}</span>
              <svg
                class="post-chevron"
                :class="{ 'is-open': expandedDraftId === point.draft_id }"
                width="16" height="16" viewBox="0 0 24 24" fill="none"
                aria-hidden="true"
              >
                <path d="M6 9l6 6 6-6" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" />
              </svg>
            </button>

            <div v-if="expandedDraftId === point.draft_id" class="post-details">
              <div class="post-detail-row">
                <span class="x-small text-secondary">Score impact</span>
                <span class="post-delta" :class="postScoreDelta(point) < 0 ? 'post-delta--down' : 'post-delta--flat'">
                  {{ postScoreDelta(point) === 0 ? '±0' : (postScoreDelta(point) > 0 ? '+' : '') + postScoreDelta(point) }} pts
                </span>
                <span v-if="point.cleaned" class="cleaned-badge">cleaned</span>
                <span class="x-small text-secondary post-date">{{ formatCapturedAt(point.captured_at) }}</span>
              </div>
            </div>
          </div>
        </div>

      </div>
    </div>

    <div class="app-action-bar">
      <button class="btn btn-primary w-100" @click="refresh">Refresh</button>
      <button class="btn btn-outline-secondary w-100" @click="$emit('back')">Back</button>
    </div>

  </div>
</template>

<style scoped>
.mosaic-screen {
  background:
    radial-gradient(circle at 18% 0%, rgba(47, 111, 237, 0.08), transparent 38%),
    linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(248, 251, 255, 0.98));
}

.mosaic-screen .app-content {
  padding: 14px;
}

.mosaic-stack {
  padding-bottom: 4px;
}

.score-panel {
  border: 1px solid var(--trace-line, #e8edf5);
  border-radius: var(--trace-radius, 14px);
  background: linear-gradient(180deg, #ffffff, #f8fbff);
  padding: 10px 12px 12px;
}

.score-wrap {
  position: relative;
  width: 140px;
  height: 140px;
}
.score-svg {
  width: 100%;
  height: 100%;
}
.score-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 1px;
}
.score-num {
  font-size: 2.6rem;
  font-weight: 800;
  line-height: 1;
}
.score-denom {
  font-size: 0.68rem;
  color: var(--trace-muted);
  font-weight: 600;
}
.score-risk-label {
  font-weight: 700;
  font-size: 0.82rem;
}
.tip-card {
  background: #fffbf0;
  border: 1px solid #f3d48b;
  border-radius: var(--trace-radius, 14px);
}
.tip-count {
  font-size: 0.68rem;
  font-weight: 700;
  color: #936509;
  background: #fff5df;
  padding: 1px 7px;
  border-radius: 999px;
  margin-left: 6px;
}
.post-row {
  background: #fafbfc;
  border: 1px solid var(--trace-line, #e8edf5);
}
.post-card {
  background: #fafbfc;
  border: 1px solid var(--trace-line, #e8edf5);
  border-radius: var(--trace-radius, 14px);
  overflow: hidden;
}
.post-toggle {
  width: 100%;
  border: 0;
  background: transparent;
  padding: 0;
  display: flex;
  align-items: center;
  gap: 0;
  text-align: left;
}
.post-toggle:hover {
  background: #f2f6fc;
}
.post-toggle-caption {
  flex: 1;
  min-width: 0;
  padding: 10px 10px 10px 11px;
  font-size: 0.85rem;
  line-height: 1.3;
  color: var(--trace-ink);
  font-weight: 600;
  display: -webkit-box;
  line-clamp: 2;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.post-delta {
  font-size: 0.62rem;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  padding: 1px 6px;
  border-radius: 999px;
}
.post-delta--down {
  color: var(--trace-danger);
  background: #fde8e7;
  border: 1px solid #f5b8b5;
}
.post-delta--flat {
  color: var(--trace-success);
  background: #e6f7ef;
  border: 1px solid #a8dfc3;
}
.post-date {
  margin-left: auto;
  white-space: nowrap;
}
.post-chevron {
  margin-right: 12px;
  color: #9aa4b2;
  flex-shrink: 0;
  transition: transform 0.2s ease;
}
.post-chevron.is-open {
  transform: rotate(180deg);
  color: #6b7280;
}
.post-details {
  border-top: 1px solid var(--trace-line, #e8edf5);
  padding: 9px 10px 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.post-detail-row {
  display: flex;
  align-items: center;
  gap: 7px;
  flex-wrap: wrap;
}
.post-num {
  flex-shrink: 0;
  padding-left: 13px;
  min-width: 26px;
  text-align: center;
  font-size: 0.78rem;
  font-weight: 600;
  color: #9aa4b2;
}
.x-small {
  font-size: 0.72rem;
}
.saves-card {
  background: #f0faf5;
  border: 1px solid #a8dfc3;
  border-radius: var(--trace-radius, 14px);
}
.saves-title {
  color: #198c68;
}
.save-row {
  display: flex;
  gap: 6px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.save-dot {
  color: #198c68;
  font-size: 0.5rem;
  flex-shrink: 0;
  margin-top: 2px;
}
.cleaned-badge {
  font-size: 0.62rem;
  font-weight: 700;
  color: #198c68;
  background: #e6f7ef;
  border: 1px solid #a8dfc3;
  padding: 1px 6px;
  border-radius: 999px;
  white-space: nowrap;
}
.stranger-card {
  background: #1a1d2b;
  color: #f2f4f8;
  border: 1px solid #2c3145;
  border-radius: var(--trace-radius, 14px);
}
.stranger-title {
  color: #fff;
}
.stranger-sub {
  color: #aeb4c6;
}
.stranger-head {
  gap: 8px;
}
.stranger-conf {
  font-size: 0.68rem;
  font-weight: 700;
  color: #ffd479;
  background: rgba(255, 212, 121, 0.12);
  padding: 2px 8px;
  border-radius: 999px;
  white-space: nowrap;
}
.stranger-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 7px 0;
  border-top: 1px solid #2c3145;
}
.stranger-statement {
  line-height: 1.35;
}
.stranger-row .small {
  color: #f2f4f8;
}
.stranger-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-top: 5px;
  flex-shrink: 0;
}
.stranger-cite {
  font-size: 0.64rem;
  color: #8b91a6;
  margin-top: 1px;
}
.stranger-conf-tag {
  font-size: 0.6rem;
  font-weight: 700;
  text-transform: uppercase;
  padding: 1px 6px;
  border-radius: 999px;
  white-space: nowrap;
  align-self: flex-start;
  margin-top: 1px;
}
.conf--high  { background: #d94841; color: #fff; }
.conf--medium { background: #f4b740; color: #3a2c00; }
.conf--low   { background: #4a5169; color: #d3d8e6; }
.stranger-dot.conf--high  { background: #ff6b63; }
.stranger-dot.conf--medium { background: #f4b740; }
.stranger-dot.conf--low   { background: #7a8199; }

.post-caption {
  display: -webkit-box;
  line-clamp: 2;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  line-height: 1.3;
}

@media (max-width: 520px) {
  .stranger-head {
    align-items: flex-start;
    flex-direction: column;
  }

  .score-num {
    font-size: 2.4rem;
  }
}
</style>
