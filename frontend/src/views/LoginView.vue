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
  <div class="login-screen app-screen">
    <div class="brand-mark">Trace</div>
    <p class="brand-line">Check the details in a post before they follow you around.</p>

    <div class="login-card trace-card">
      <p class="status-chip safe mb-3">Private by default</p>
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
  </div>
</template>

<style scoped>
.login-screen {
  justify-content: center;
  padding: 28px;
  background:
    linear-gradient(160deg, rgba(47, 111, 237, 0.11), transparent 44%),
    linear-gradient(0deg, #ffffff, #f8fbff);
}
.brand-mark {
  color: var(--trace-ink);
  font-size: 2.8rem;
  font-weight: 900;
  line-height: 1;
  text-align: center;
}
.brand-line {
  max-width: 280px;
  margin: 12px auto 24px;
  color: var(--trace-muted);
  font-size: 0.98rem;
  text-align: center;
}
.login-card {
  padding: 18px;
}
</style>
