<script setup>
import { ref, computed } from 'vue'

const props = defineProps({
  photoUrl: { type: String, default: null },
  detections: { type: Array, default: () => [] },
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
  <div class="d-flex flex-column h-100">
    <div class="border-bottom p-3 text-center fw-bold">Scan results</div>

    <div class="p-3 flex-grow-1 overflow-auto">
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

      <div v-if="!hasFindings" class="text-center text-success py-4">
        <div class="fs-1 mb-2">✅</div>
        <p class="fw-semibold mb-0">Looks safe to share</p>
        <p class="text-muted small">Trace didn't find any personal details in this post.</p>
      </div>

      <template v-else>
        <div v-if="metadataFindings.length" class="alert alert-warning py-2 px-3 small mb-2">
          <div v-for="(d, i) in metadataFindings" :key="i">📍 {{ d.detail }}</div>
        </div>

        <div v-if="imageFindings.length" class="mb-2">
          <p class="fw-semibold small mb-1">Flagged in your photo</p>
          <ul class="list-unstyled small mb-0">
            <li v-for="(d, i) in imageFindings" :key="i" class="mb-1">
              <strong>{{ CATEGORY_LABELS[d.category] || d.category }}:</strong> {{ d.detail }}
            </li>
          </ul>
        </div>

        <div v-if="textFindings.length" class="mb-2">
          <p class="fw-semibold small mb-1">Flagged in your caption</p>
          <ul class="list-unstyled small mb-0">
            <li v-for="(d, i) in textFindings" :key="i" class="mb-1">
              <strong>{{ d.category }}:</strong> {{ d.detail }}
            </li>
          </ul>
        </div>
      </template>
    </div>

    <div class="p-3 border-top d-flex flex-column gap-2">
      <button v-if="hasFindings" class="btn btn-primary w-100" @click="$emit('continue')">Continue</button>
      <button class="btn btn-outline-secondary w-100" @click="$emit('restart')">Back to start</button>
    </div>
  </div>
</template>

<style scoped>
.photo-wrap {
  position: relative;
  border-radius: 12px;
  overflow: hidden;
  line-height: 0;
}
.finding-box {
  position: absolute;
  border: 2px solid #dc3545;
  border-radius: 4px;
  pointer-events: none;
}
.finding-label {
  position: absolute;
  top: -1.4rem;
  left: 0;
  background: #dc3545;
  color: #fff;
  font-size: 0.65rem;
  padding: 1px 6px;
  border-radius: 4px 4px 0 0;
  white-space: nowrap;
}
</style>
