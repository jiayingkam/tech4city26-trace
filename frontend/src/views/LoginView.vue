<script setup>
import { ref } from 'vue'
import { login, signup } from '../api'

const emit = defineEmits(['success'])  // a way to tell App.vue "login worked"

const email = ref('')
const password = ref('')
const error = ref('')
const loading = ref(false)
const mode = ref('login')              // toggles between 'login' and 'signup'

async function submit() {
  error.value = ''
  loading.value = true
  try {
    const user = mode.value === 'login'
      ? await login(email.value, password.value)
      : await signup(email.value, password.value)
    emit('success', user)    // success → App.vue advances past the login screen
  } catch (e) {
    error.value = e.message || 'Could not reach the server. Is Flask running?'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="p-4 d-flex flex-column h-100">
    <h4 class="fw-bold text-center mb-1">Trace</h4>
    <p class="text-muted text-center mb-4">Know your footprint before you leave it.</p>

    <input v-model="email" type="email" class="form-control mb-2" placeholder="Email" />
    <input v-model="password" type="password" class="form-control mb-3" placeholder="Password" />

    <p v-if="error" class="text-danger small mb-2">{{ error }}</p>

    <button class="btn btn-primary w-100 mb-2" :disabled="loading" @click="submit">
      {{ loading ? 'Please wait…' : (mode === 'login' ? 'Log in' : 'Sign up') }}
    </button>
    <button class="btn btn-link w-100" @click="mode = mode === 'login' ? 'signup' : 'login'">
      {{ mode === 'login' ? 'Need an account? Sign up' : 'Have an account? Log in' }}
    </button>
  </div>
</template>