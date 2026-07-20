<script setup>
import { ref, computed } from 'vue'

const props = defineProps({
  photoUrl: { type: String, default: null },
  detections: { type: Array, default: () => [] },
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

function formatK(k) {
  if (!k) return '?'
  if (k >= 1_000_000) return `~${(k / 1_000_000).toFixed(1)}M`
  if (k >= 1_000) return `~${Math.round(k / 1_000)}K`
  return `~${k}`
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
</script>

<template>
  <div class="app-screen">
    <div class="app-header">
      <h1 class="app-title">Scan results</h1>
      <p class="app-subtitle">{{ hasFindings ? 'A few details could use a second look.' : 'No personal details stood out.' }}</p>
    </div>

    <div class="app-content">
      <div v-if="photoUrl" class="photo-wrap mb-3">
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

        <div v-if="textFindings.length" class="finding-panel mb-3">
          <p class="fw-bold small mb-2">In your caption</p>
          <ul class="list-unstyled small mb-0">
            <li v-for="(d, i) in textFindings" :key="i" class="mb-1">
              <strong>{{ d.category }}:</strong> {{ d.detail }}
            </li>
          </ul>
        </div>

        <div v-if="teachableMoment" class="coach-card mt-3">
          <p class="eyebrow mb-1">Why this matters</p>
          <p class="fw-semibold mb-1">{{ teachableMoment.title }}</p>
          <p class="small mb-2">{{ teachableMoment.explanation }}</p>
          <p class="small mb-0"><strong>Safer move:</strong> {{ teachableMoment.safer_action }}</p>
        </div>
      </template>

      <div v-if="mosaicRisk" class="mosaic-impact-card mt-3">
        <p class="eyebrow-mosaic mb-1">Cumulative privacy impact</p>
        <div class="d-flex align-items-center gap-2 flex-wrap">
          <span class="impact-crowd">
            {{ formatK(mosaicRisk.k_before) }} → {{ formatK(mosaicRisk.k_after) }} people share your profile
          </span>
          <span
            class="impact-badge"
            :class="`impact-badge--${mosaicRisk.risk_level}`"
          >{{ mosaicRisk.risk_level }}</span>
        </div>
        <p v-if="mosaicRisk.delta_bits === 0" class="impact-note mb-0 mt-1">
          This post adds nothing new to your long-term privacy exposure.
        </p>
        <p v-else class="impact-note mb-0 mt-1">
          Posting this shrinks the crowd of people who share your profile by {{ formatK(mosaicRisk.k_before - mosaicRisk.k_after) }}.
        </p>
      </div>
    </div>

    <div class="app-action-bar">
      <button v-if="hasFindings" class="btn btn-primary w-100" @click="$emit('continue')">Fix the risky parts</button>
      <button class="btn btn-outline-secondary w-100" @click="$emit('restart')">Back</button>
    </div>
  </div>
</template>

<style scoped>
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
.mosaic-impact-card {
  padding: 11px 14px;
  border: 1px solid #d0e0ff;
  border-radius: 14px;
  background: #f0f5ff;
}
.eyebrow-mosaic {
  font-size: 0.68rem;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: #2f6fed;
  margin: 0;
}
.impact-crowd {
  font-size: 0.82rem;
  font-weight: 600;
  color: #172235;
}
.impact-badge {
  font-size: 0.68rem;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 999px;
  text-transform: capitalize;
}
.impact-badge--low    { background: #e9f8f2; color: #198c68; }
.impact-badge--medium { background: #fff5df; color: #936509; }
.impact-badge--high   { background: #fde8e7; color: #d94841; }
.impact-note {
  font-size: 0.75rem;
  color: #667085;
}
</style>
