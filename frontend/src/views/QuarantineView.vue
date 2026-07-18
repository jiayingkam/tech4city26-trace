<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { editQuarantine, deleteQuarantine, releaseQuarantine } from '../api'

const props = defineProps({
  photoUrl: { type: String, default: null },
  quarantine: { type: Object, required: true },
})
const emit = defineEmits(['restart', 'edit'])

const busy = ref(false)
const error = ref('')
const resultMessage = ref('')
const now = ref(Date.now())

let timer
onMounted(() => {
  timer = setInterval(() => {
    now.value = Date.now()
  }, 1000)
})
onBeforeUnmount(() => clearInterval(timer))

const secondsRemaining = computed(() => {
  const expiry = new Date(props.quarantine.cooldown_expiry).getTime()
  return Math.max(0, Math.round((expiry - now.value) / 1000))
})
const expired = computed(() => secondsRemaining.value <= 0)
const formattedCountdown = computed(() => {
  const m = Math.floor(secondsRemaining.value / 60)
  const s = secondsRemaining.value % 60
  return `${m}:${String(s).padStart(2, '0')}`
})

async function handleEdit() {
  busy.value = true
  error.value = ''
  try {
    const result = await editQuarantine(props.quarantine.quarantine_id)
    emit('edit', result.remediation)
  } catch (err) {
    error.value = err.message || 'Could not start editing.'
    busy.value = false
  }
}

async function handleDelete() {
  busy.value = true
  error.value = ''
  try {
    await deleteQuarantine(props.quarantine.quarantine_id)
    resultMessage.value = "This post was deleted — it won't be shared."
  } catch (err) {
    error.value = err.message || 'Could not delete this post.'
  } finally {
    busy.value = false
  }
}

async function handleRelease() {
  busy.value = true
  error.value = ''
  try {
    await releaseQuarantine(props.quarantine.quarantine_id)
    resultMessage.value = 'Posted as-is.'
  } catch (err) {
    error.value = err.message || 'Could not release this post yet.'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="app-screen">
    <div class="app-header">
      <h1 class="app-title">Pause and review</h1>
      <p class="app-subtitle">This post has something worth checking first.</p>
    </div>

    <div class="app-content text-center">
      <img v-if="photoUrl" :src="photoUrl" class="review-photo mb-3" alt="Your photo" />

      <div v-if="resultMessage" class="coach-card small">{{ resultMessage }}</div>
      <template v-else>
        <div class="pause-card trace-card">
          <p class="status-chip warn mb-2">Review pause</p>
          <p class="fw-bold mb-1">{{ quarantine.reason }}</p>
          <p class="soft-note mb-3">
            Take a breath and decide whether to edit, delete, or share it unchanged.
          </p>
          <p class="countdown mb-0">
            {{ expired ? 'Posting is unlocked.' : `Posting unlocks in ${formattedCountdown}` }}
          </p>
        </div>
      </template>

      <p v-if="error" class="text-danger small mt-2">{{ error }}</p>
    </div>

    <div v-if="!resultMessage" class="app-action-bar">
      <button class="btn btn-primary w-100" :disabled="busy" @click="handleEdit">Edit before sharing</button>
      <button class="btn btn-outline-danger w-100" :disabled="busy" @click="handleDelete">Delete this post</button>
      <button class="btn btn-outline-secondary w-100" :disabled="busy || !expired" @click="handleRelease">
        Post anyway
      </button>
    </div>
    <div v-else class="app-action-bar">
      <button class="btn btn-outline-secondary w-100" @click="$emit('restart')">Back</button>
    </div>
  </div>
</template>

<style scoped>
.review-photo {
  width: 100%;
  border: 1px solid var(--trace-line);
  border-radius: 18px;
}
.pause-card {
  padding: 18px;
}
.countdown {
  color: var(--trace-ink);
  font-size: 1.15rem;
  font-weight: 900;
}
</style>
