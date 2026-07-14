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
  <div class="d-flex flex-column h-100">
    <div class="border-bottom p-3 text-center fw-bold">Held for review</div>

    <div class="p-3 flex-grow-1 overflow-auto text-center">
      <img v-if="photoUrl" :src="photoUrl" class="w-100 rounded mb-3" alt="Your photo" />

      <div v-if="resultMessage" class="alert alert-secondary small">{{ resultMessage }}</div>
      <template v-else>
        <p class="text-danger fw-semibold mb-1">⏸ {{ quarantine.reason }}</p>
        <p class="text-muted small mb-3">
          Trace is holding this post for a moment before it can go out as-is.
        </p>
        <p class="small mb-0">
          {{ expired ? 'You can post now.' : `Posting unlocks in ${formattedCountdown}` }}
        </p>
      </template>

      <p v-if="error" class="text-danger small mt-2">{{ error }}</p>
    </div>

    <div v-if="!resultMessage" class="p-3 border-top d-flex flex-column gap-2">
      <button class="btn btn-primary w-100" :disabled="busy" @click="handleEdit">Edit before sharing</button>
      <button class="btn btn-outline-danger w-100" :disabled="busy" @click="handleDelete">Delete this post</button>
      <button class="btn btn-outline-secondary w-100" :disabled="busy || !expired" @click="handleRelease">
        Post anyway
      </button>
    </div>
    <div v-else class="p-3 border-top">
      <button class="btn btn-outline-secondary w-100" @click="$emit('restart')">Back to start</button>
    </div>
  </div>
</template>
