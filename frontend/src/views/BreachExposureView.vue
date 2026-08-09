<script setup>
import { onMounted, ref } from 'vue'
import HamburgerMenu from '../components/HamburgerMenu.vue'
import BreachExposureCard from '../components/BreachExposureCard.vue'
import { getMe } from '../api'

defineEmits(['back', 'history', 'settings', 'mosaic', 'logout', 'quiz', 'breach-exposure'])

const user = ref(null)
const error = ref('')

onMounted(async () => {
  try {
    user.value = await getMe()
  } catch (err) {
    error.value = err.message || 'Could not load your account.'
  }
})
</script>

<template>
  <div class="app-screen">
    <div class="app-header">
      <HamburgerMenu @history="$emit('history')" @settings="$emit('settings')" @mosaic="$emit('mosaic')" @logout="$emit('logout')" @quiz="$emit('quiz')" @breach-exposure="$emit('breach-exposure')" />
      <h1 class="app-title">Credential exposure</h1>
      <p class="app-subtitle">Whether your email shows up where it shouldn't.</p>
    </div>

    <div class="app-content">
      <BreachExposureCard v-if="user" :user="user" />
      <div v-else-if="error" class="text-danger small">{{ error }}</div>
      <div v-else class="d-flex flex-column align-items-center justify-content-center gap-2 py-5">
        <div class="spinner-border text-primary" role="status"></div>
      </div>
    </div>

    <div class="app-action-bar">
      <button class="btn btn-outline-secondary w-100" @click="$emit('back')">Back</button>
    </div>
  </div>
</template>
