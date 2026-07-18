<script setup>
import { ref, computed } from 'vue'

const props = defineProps({
  photoUrl: { type: String, default: null },
  detections: { type: Array, default: () => [] },
  teachableMoment: { type: Object, default: null },
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
</style>
