<script setup>
import { ref } from 'vue'
import { login, signup } from '../api'

const emit = defineEmits(['success'])  // a way to tell App.vue "login worked"

const email = ref('')
const password = ref('')
const error = ref('')
const loading = ref(false)
const mode = ref('login')              // toggles between 'login' and 'signup'
const authOpen = ref(false)

function openAuth(nextMode) {
  mode.value = nextMode
  authOpen.value = true
  error.value = ''
}

function switchMode() {
  mode.value = mode.value === 'login' ? 'signup' : 'login'
  error.value = ''
}

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
    <div class="preview-layer" aria-hidden="true">
      <div class="scan-card">
        <div class="scan-header">
          <span class="scan-dot"></span>
          <div class="scan-lines">
            <span></span>
            <span></span>
          </div>
          <strong>Ready</strong>
        </div>
        <div class="scan-preview">
          <span class="scan-line"></span>
          <span class="photo-block block-sky"></span>
          <span class="photo-block block-person"></span>
          <span class="photo-block block-sign"></span>
          <span class="target target-face"></span>
          <span class="target target-place"></span>
        </div>
        <div class="finding-list">
          <span>Face</span>
          <span>Location</span>
          <span>Metadata</span>
        </div>
      </div>
    </div>

    <section class="welcome-copy">
      <p class="status-chip safe">Private by default</p>
      <h1 class="brand-mark">Trace</h1>
      <p class="brand-line">Check your post for faces, places, text, and hidden photo data before you share it.</p>
    </section>

    <div class="login-card trace-card" :class="{ expanded: authOpen }">
      <div v-if="!authOpen" class="cta-stack">
        <button class="btn btn-primary w-100" @click="openAuth('signup')">Try Trace</button>
        <button class="btn btn-outline-secondary w-100" @click="openAuth('login')">Log in</button>
      </div>

      <form v-else class="auth-form" @submit.prevent="submit">
        <div class="form-heading">
          <p class="mb-1">{{ mode === 'login' ? 'Welcome back' : 'Start checking posts' }}</p>
          <span>{{ mode === 'login' ? 'Log in to continue.' : 'Create an account to try Trace.' }}</span>
        </div>

        <input v-model="email" type="email" class="form-control" placeholder="Email" autocomplete="email" />
        <input
          v-model="password"
          type="password"
          class="form-control"
          placeholder="Password"
          :autocomplete="mode === 'login' ? 'current-password' : 'new-password'"
        />

        <p v-if="error" class="text-danger small mb-0">{{ error }}</p>

        <button class="btn btn-primary w-100" :disabled="loading">
          {{ loading ? 'Please wait...' : (mode === 'login' ? 'Log in' : 'Sign up') }}
        </button>
        <button
          type="button"
          class="btn btn-outline-secondary w-100"
          @click="switchMode"
        >
          {{ mode === 'login' ? 'Create an account instead' : 'Log in instead' }}
        </button>
      </form>
    </div>
  </div>
</template>

<style scoped>
.login-screen {
  position: relative;
  justify-content: space-between;
  gap: 14px;
  padding: 24px 22px 20px;
  overflow: hidden;
  background:
    linear-gradient(160deg, rgba(21, 165, 139, 0.2), transparent 34%),
    linear-gradient(24deg, rgba(244, 183, 64, 0.16), transparent 45%),
    linear-gradient(180deg, #f8fbff 0%, #ffffff 54%, #f5fbf8 100%);
}
.preview-layer,
.welcome-copy,
.login-card {
  position: relative;
  z-index: 1;
}
.preview-layer {
  flex: 0 0 250px;
  min-height: 0;
}
.scan-card {
  position: absolute;
  top: 0;
  left: 50%;
  width: min(300px, 100%);
  padding: 14px;
  border: 1px solid rgba(207, 216, 229, 0.9);
  border-radius: 20px;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.96), rgba(247, 251, 255, 0.94));
  box-shadow: 0 22px 44px rgba(23, 34, 53, 0.14);
  transform: translateX(-50%);
}
.scan-card::before {
  position: absolute;
  inset: -22px -18px auto auto;
  width: 86px;
  height: 86px;
  border-radius: 30px;
  background: rgba(244, 183, 64, 0.2);
  content: '';
}
.scan-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}
.scan-dot {
  width: 32px;
  height: 32px;
  border-radius: 11px;
  background: linear-gradient(135deg, var(--trace-primary), var(--trace-mint));
}
.scan-lines {
  display: grid;
  flex: 1;
  gap: 6px;
}
.scan-lines span {
  display: block;
  height: 7px;
  border-radius: 999px;
  background: #d9e3f1;
}
.scan-lines span:last-child {
  width: 58%;
}
.scan-header strong {
  color: var(--trace-success);
  font-size: 0.72rem;
}
.scan-preview {
  position: relative;
  height: 148px;
  overflow: hidden;
  border: 1px solid #dce6f2;
  border-radius: 16px;
  background:
    linear-gradient(145deg, #edf6ff 0%, #f9fbff 48%, #e8f7f0 100%);
}
.photo-block {
  position: absolute;
}
.block-sky {
  top: 18px;
  right: 24px;
  width: 52px;
  height: 52px;
  border-radius: 18px;
  background: #ffd36d;
}
.block-person {
  left: 44px;
  bottom: 24px;
  width: 58px;
  height: 84px;
  border-radius: 22px 22px 16px 16px;
  background: linear-gradient(180deg, #8ab6f6 0 42%, #245c9e 42% 100%);
}
.block-sign {
  right: 42px;
  bottom: 30px;
  width: 74px;
  height: 44px;
  border-radius: 9px;
  background: #fff;
  box-shadow: inset 0 0 0 2px #bcd0e7;
}
.scan-line {
  position: absolute;
  left: 0;
  top: 50%;
  width: 100%;
  height: 3px;
  background: rgba(47, 111, 237, 0.75);
  box-shadow: 0 0 18px rgba(47, 111, 237, 0.42);
}
.target {
  position: absolute;
  border: 2px solid var(--trace-coral);
  border-radius: 12px;
}
.target-face {
  left: 48px;
  top: 44px;
  width: 48px;
  height: 42px;
}
.target-place {
  right: 36px;
  bottom: 28px;
  width: 84px;
  height: 50px;
  border-color: var(--trace-primary);
}
.finding-list {
  display: flex;
  gap: 7px;
  margin-top: 12px;
}
.finding-list span {
  flex: 1;
  padding: 7px 0;
  border-radius: 10px;
  background: #edf5ff;
  color: var(--trace-primary-dark);
  font-size: 0.68rem;
  font-weight: 900;
  text-align: center;
}
.finding-list span:nth-child(3) {
  background: #fff5df;
  color: #936509;
}
.welcome-copy {
  text-align: center;
}
.welcome-copy .status-chip {
  margin-bottom: 10px;
}
.brand-mark {
  color: var(--trace-ink);
  font-size: 2.7rem;
  font-weight: 900;
  line-height: 1;
}
.brand-line {
  max-width: 315px;
  margin: 10px auto 0;
  color: var(--trace-muted);
  font-size: 0.93rem;
}
.login-card {
  padding: 14px;
  border-radius: 18px;
  transition:
    padding 0.22s ease,
    transform 0.22s ease;
}
.login-card.expanded {
  padding: 16px;
  transform: translateY(-2px);
}
.cta-stack,
.auth-form {
  display: grid;
  gap: 10px;
}
.form-heading {
  text-align: center;
}
.form-heading p {
  color: var(--trace-ink);
  font-weight: 900;
}
.form-heading span {
  color: var(--trace-muted);
  font-size: 0.82rem;
}
.auth-form .form-control {
  min-height: 42px;
}

@media (max-height: 740px) {
  .login-screen {
    gap: 10px;
    padding: 18px 20px 16px;
  }
  .preview-layer {
    flex-basis: 220px;
  }
  .scan-card {
    width: 278px;
    padding: 12px;
  }
  .scan-preview {
    height: 122px;
  }
  .brand-mark {
    font-size: 2.35rem;
  }
  .brand-line {
    font-size: 0.85rem;
    line-height: 1.45;
  }
  .login-card.expanded {
    padding: 13px;
  }
  .auth-form {
    gap: 8px;
  }
}
</style>
