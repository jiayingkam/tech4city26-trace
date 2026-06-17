<script setup>
import { ref } from 'vue'

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
    const res = await fetch(`http://localhost:5000/api/${mode.value}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: email.value, password: password.value })
    })
    const data = await res.json()
    if (res.ok) {
      emit('success')          // success → App.vue advances the step
    } else {
      error.value = data.error // show the message Flask sent back
    }
  } catch (e) {
    error.value = 'Could not reach the server. Is Flask running?'
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