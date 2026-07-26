<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { login, signup } from '../api'

const emit = defineEmits(['success'])  // a way to tell App.vue "login worked"

const email = ref('')
const password = ref('')
const error = ref('')
const loading = ref(false)
const mode = ref('login')              // toggles between 'login' and 'signup'
const authOpen = ref(false)

// drives the population-meter number in the preview card, in step with the
// CSS animation below (both keyed to the same 6s cycle)
const METER_STEPS = [
  { t: 0, label: '6.0M' },
  { t: 1700, label: '640K' },
  { t: 3400, label: '42K' },
  { t: 5100, label: '1' },
]
const METER_CYCLE_MS = 6000
const meterLabel = ref(METER_STEPS[0].label)
let meterTimer = null

onMounted(() => {
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    meterLabel.value = METER_STEPS[METER_STEPS.length - 1].label
    return
  }
  // anchor to mount time, not wall-clock time — the CSS animation's own
  // clock starts fresh at 0% when the element mounts, so the label has to
  // start from the same zero point or it can open on the wrong step (e.g.
  // showing "1" while the circle is still on its blue opening frame)
  const start = performance.now()
  const tick = () => {
    const t = (performance.now() - start) % METER_CYCLE_MS
    let current = METER_STEPS[0].label
    for (const step of METER_STEPS) {
      if (t >= step.t) current = step.label
    }
    meterLabel.value = current
  }
  tick()
  meterTimer = setInterval(tick, 110)
})

onUnmounted(() => {
  if (meterTimer) clearInterval(meterTimer)
})

function openAuth(nextMode) {
  mode.value = nextMode
  authOpen.value = true
  error.value = ''
}

function switchMode() {
  mode.value = mode.value === 'login' ? 'signup' : 'login'
  password.value = ''
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
    <div class="hero-group">
      <section class="welcome-copy">
        <p class="status-chip safe">Private by default</p>
        <h1 class="brand-mark">Trace</h1>
        <p class="brand-line">One photo's harmless. String a few together, and someone could find exactly who you are. <strong>Trace catches it first.</strong></p>
      </section>

      <div class="preview-frame" aria-hidden="true">
        <div class="preview-stage">
          <div class="mini-stack">
            <div class="mini-card c1">
              <div class="mini-fill"></div>
              <span class="mini-line"></span>
              <span class="mini-check">
                <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M5 13l4 4 10-11" />
                </svg>
              </span>
            </div>
            <div class="mini-card c2">
              <div class="mini-fill"></div>
              <span class="mini-line"></span>
              <span class="mini-check">
                <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M12 3.5 21.5 20h-19z" />
                  <line x1="12" y1="9.5" x2="12" y2="14" />
                  <circle cx="12" cy="17" r="0.6" fill="currentColor" stroke="none" />
                </svg>
              </span>
            </div>
            <div class="mini-card c3">
              <div class="mini-fill"></div>
              <span class="mini-line"></span>
              <span class="mini-check">
                <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M12 3.5 21.5 20h-19z" />
                  <line x1="12" y1="9.5" x2="12" y2="14" />
                  <circle cx="12" cy="17" r="0.6" fill="currentColor" stroke="none" />
                </svg>
              </span>
            </div>
          </div>
          <div class="meter-side">
            <div class="pop-circle">{{ meterLabel }}</div>
            <div class="risk-wash"></div>
          </div>
        </div>
      </div>
    </div>

    <div class="login-card trace-card" :class="{ expanded: authOpen }">
      <div v-if="!authOpen" class="cta-stack">
        <button class="btn btn-primary w-100" @click="openAuth('signup')">Try Trace</button>
        <button class="btn btn-outline-secondary w-100" @click="openAuth('login')">Log in</button>
      </div>

      <form v-else class="auth-form" @submit.prevent="submit">
        <button type="button" class="btn-back" @click="authOpen = false">← Back</button>
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
  justify-content: center;
  gap: 52px;
  padding: 24px 22px 20px;
  overflow-x: hidden;
  overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: rgba(0, 0, 0, 0.18) transparent;
  background:
    linear-gradient(160deg, rgba(21, 165, 139, 0.2), transparent 34%),
    linear-gradient(24deg, rgba(244, 183, 64, 0.16), transparent 45%),
    linear-gradient(180deg, #f8fbff 0%, #ffffff 54%, #f5fbf8 100%);
}
.hero-group,
.login-card {
  position: relative;
  z-index: 1;
}
.hero-group {
  display: flex;
  flex-direction: column;
  gap: 36px;
}
.preview-frame {
  width: min(360px, 100%);
  margin: 0 auto;
}
.preview-stage {
  position: relative;
  display: flex;
  height: 190px;
  padding: 12px;
  gap: 12px;
  overflow: hidden;
  border: 1px solid #dce6f2;
  border-radius: 18px;
  background:
    linear-gradient(145deg, #eef5ff 0%, #f9fbff 55%, #eaf7f1 100%);
}
.mini-stack {
  flex: 1.15;
  display: grid;
  grid-template-rows: repeat(3, 1fr);
  gap: 8px;
}
.mini-card {
  position: relative;
  border-radius: 11px;
  background: #ffffff;
  border: 1px solid #dfe8f3;
  overflow: hidden;
}
.mini-card .mini-fill {
  position: absolute;
  inset: 0;
  background: linear-gradient(135deg, #e7f0ff, #eefaf4);
}
.mini-card .mini-line {
  position: absolute;
  left: 6%;
  width: 88%;
  height: 3px;
  background: rgba(47, 111, 237, 0.75);
  box-shadow: 0 0 10px rgba(47, 111, 237, 0.4);
  opacity: 0;
}
.mini-card .mini-check {
  position: absolute;
  right: 7px;
  top: 7px;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  color: #fff;
  display: grid;
  place-items: center;
  opacity: 0;
}
.mini-card.c1 .mini-line {
  animation: mini-sweep-1 6s linear infinite;
}
.mini-card.c1 .mini-check {
  background: var(--trace-mint);
  animation: mini-check-1 6s linear infinite;
}
.mini-card.c2 .mini-line {
  animation: mini-sweep-2 6s linear infinite;
}
.mini-card.c2 .mini-check {
  background: var(--trace-sun);
  color: #6b4a06;
  animation: mini-check-2 6s linear infinite;
}
.mini-card.c3 .mini-line {
  animation: mini-sweep-3 6s linear infinite;
}
.mini-card.c3 .mini-check {
  background: var(--trace-danger);
  animation:
    mini-check-3 6s linear infinite,
    badge-alert-ring 6s linear infinite;
}
@keyframes mini-sweep-1 {
  0%, 2% { top: 10%; opacity: 0; }
  6% { opacity: 1; }
  22% { top: 80%; opacity: 1; }
  26%, 100% { opacity: 0; }
}
@keyframes mini-check-1 {
  0%, 24% { opacity: 0; }
  28%, 100% { opacity: 1; }
}
@keyframes mini-sweep-2 {
  0%, 30% { opacity: 0; }
  32% { top: 10%; opacity: 1; }
  50% { top: 80%; opacity: 1; }
  54%, 100% { opacity: 0; }
}
@keyframes mini-check-2 {
  0%, 52% { opacity: 0; }
  56%, 100% { opacity: 1; }
}
@keyframes mini-sweep-3 {
  0%, 58% { opacity: 0; }
  60% { top: 10%; opacity: 1; }
  78% { top: 80%; opacity: 1; }
  82%, 100% { opacity: 0; }
}
@keyframes mini-check-3 {
  0%, 80% { opacity: 0; }
  84%, 100% { opacity: 1; }
}
@keyframes badge-alert-ring {
  0%, 83% { box-shadow: 0 0 0 0 rgba(217, 72, 65, 0); }
  90% { box-shadow: 0 0 0 4px rgba(217, 72, 65, 0.4); }
  97%, 100% { box-shadow: 0 0 0 0 rgba(217, 72, 65, 0); }
}
.meter-side {
  position: relative;
  flex: 1;
  display: grid;
  place-items: center;
}
.pop-circle {
  display: grid;
  place-items: center;
  border-radius: 50%;
  font-weight: 800;
  font-size: 0.86rem;
  color: var(--trace-primary-dark);
  font-variant-numeric: tabular-nums;
  background: radial-gradient(circle at 35% 30%, #eaf3ff, #bcd4f7 60%, #8fb4ea 100%);
  animation:
    circle-steps 6s linear infinite,
    circle-alert-ring 6s linear infinite;
}
@keyframes circle-steps {
  0%, 24% {
    width: 98px;
    height: 98px;
    background: radial-gradient(circle at 35% 30%, #eaf3ff, #bcd4f7 60%, #8fb4ea 100%);
    color: var(--trace-primary-dark);
    font-size: 0.86rem;
  }
  28%, 52% {
    width: 76px;
    height: 76px;
    background: radial-gradient(circle at 35% 30%, #fff3d9, var(--trace-sun) 78%);
    color: #6b4a06;
  }
  56%, 100% {
    width: 50px;
    height: 50px;
    background: radial-gradient(circle at 35% 30%, #ffd9d5, var(--trace-danger) 78%);
    color: #fff;
    font-size: 0.68rem;
  }
}
@keyframes circle-alert-ring {
  0%, 55% { box-shadow: 0 0 0 0 rgba(217, 72, 65, 0); }
  64% { box-shadow: 0 0 0 7px rgba(217, 72, 65, 0.32); }
  73%, 78% { box-shadow: 0 0 0 0 rgba(217, 72, 65, 0); }
  86% { box-shadow: 0 0 0 7px rgba(217, 72, 65, 0.32); }
  95%, 100% { box-shadow: 0 0 0 0 rgba(217, 72, 65, 0); }
}
.risk-wash {
  position: absolute;
  inset: 0;
  pointer-events: none;
  background: radial-gradient(circle at 78% 82%, rgba(217, 72, 65, 0.32), transparent 68%);
  opacity: 0;
  animation: risk-wash-in 6s linear infinite;
}
@keyframes risk-wash-in {
  0%, 54% { opacity: 0; }
  64%, 100% { opacity: 1; }
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
  border: 1px solid rgba(207, 216, 229, 0.9);
  border-radius: 18px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.97), rgba(247, 251, 255, 0.95));
  box-shadow: 0 18px 38px rgba(23, 34, 53, 0.1);
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
.login-screen::-webkit-scrollbar {
  width: 3px;
}
.login-screen::-webkit-scrollbar-track {
  background: transparent;
}
.login-screen::-webkit-scrollbar-thumb {
  background: rgba(0, 0, 0, 0.18);
  border-radius: 99px;
}
.btn-back {
  align-self: flex-start;
  border: none;
  background: none;
  padding: 0;
  color: var(--trace-muted);
  font-size: 0.82rem;
}

@media (max-height: 740px) {
  .login-screen {
    gap: 26px;
    padding: 18px 20px 16px;
  }
  .hero-group {
    gap: 22px;
  }
  .preview-frame {
    width: 320px;
  }
  .preview-stage {
    height: 158px;
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

@media (prefers-reduced-motion: reduce) {
  .mini-line,
  .mini-check,
  .pop-circle,
  .risk-wash {
    animation: none !important;
  }
  .mini-line {
    opacity: 0;
  }
  .mini-check {
    opacity: 1;
  }
  .pop-circle {
    width: 50px;
    height: 50px;
    background: radial-gradient(circle at 35% 30%, #ffd9d5, var(--trace-danger) 78%);
    color: #fff;
    font-size: 0.68rem;
  }
  .risk-wash {
    opacity: 1;
  }
}
</style>
