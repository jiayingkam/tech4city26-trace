<script setup>
import { onMounted, ref } from 'vue'
import { checkBreachExposure, getBreachExposureStatus } from '../api'

const props = defineProps({
  user: { type: Object, required: true },
})

const result = ref(null)
const checking = ref(false)
const error = ref('')
// The backend no longer caches /check (an explicit "Check" click always runs
// a real, fresh check — see routes.py), so there's no server-provided signal
// left to distinguish "this came from an active check" from "this is just
// whatever was last stored, shown on page load." Tracked locally instead:
// true only right after a successful runCheck(), reset whenever a stored
// result is loaded instead — otherwise a days-old result loaded on mount
// would misleadingly read "Just checked."
const justChecked = ref(false)

onMounted(async () => {
  try {
    const stored = await getBreachExposureStatus()
    if (stored) {
      result.value = stored
      justChecked.value = false
    }
  } catch {
    // No stored result yet, or the status endpoint is unreachable — the
    // "Check my exposure" button still works either way, so this is silent.
  }
})

async function runCheck() {
  checking.value = true
  error.value = ''
  try {
    result.value = await checkBreachExposure()
    justChecked.value = true
  } catch (err) {
    error.value = err.message || 'Could not run the exposure check.'
  } finally {
    checking.value = false
  }
}
</script>

<template>
  <div>
    <p class="fw-bold small mb-3">Credential exposure</p>
    <div class="breach-report">
      <div>
        <span class="d-block fw-semibold">Check {{ user.email }}</span>
        <span class="d-block text-muted small">
          Looks for this email in known data breaches, and checks which sites it's
          registered on.
        </span>
      </div>
      <button class="btn btn-outline-primary btn-sm" :disabled="checking" @click="runCheck">
        {{ checking ? 'Checking…' : 'Check' }}
      </button>
    </div>
    <p v-if="error" class="text-danger small mb-2">{{ error }}</p>

    <div v-if="result" class="breach-results">
      <div class="breach-block">
        <span class="d-block fw-semibold small">Breach sources</span>
        <template v-if="result.leakcheck?.status === 'ok'">
          <p v-if="result.leakcheck.found" class="small mb-1">
            Found in {{ result.leakcheck.sources.length }} breach(es):
            {{ result.leakcheck.sources.map(s => s.name).join(', ') }}.
            Exposed data included: {{ result.leakcheck.fields.join(', ') || 'unspecified' }}.
          </p>
          <p v-else class="text-success small mb-1">Not found in any known breach.</p>
        </template>
        <p v-else class="text-muted small mb-1">
          Couldn't check breach sources right now — try again.
        </p>
      </div>

      <div class="breach-block">
        <span class="d-block fw-semibold small">Registered accounts</span>
        <template v-if="result.holehe?.status === 'ok'">
          <p class="small mb-1">
            Checked {{ result.holehe.platforms_attempted }} platforms — got a clear answer on
            {{ result.holehe.platforms_conclusive }} (others were rate-limited by the site itself).
          </p>
          <template v-if="result.holehe.registered.length">
            <p class="small mb-1">Registered on:</p>
            <ul class="breach-platform-list small mb-1">
              <li v-for="p in result.holehe.registered" :key="p.name">{{ p.name }}</li>
            </ul>
          </template>
          <p v-else class="text-success small mb-1">Not registered on any of those.</p>
        </template>
        <p v-else class="text-muted small mb-1">
          Couldn't run the platform scan right now — try again.
        </p>
      </div>

      <p class="text-muted small mb-0">
        {{ justChecked ? 'Just checked.' : 'From your last check.' }}
        Checked {{ new Date(result.checked_at).toLocaleString() }}.
      </p>
    </div>
  </div>
</template>

<style scoped>
.breach-report {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px;
  margin-bottom: 12px;
  border: 1px solid var(--trace-line);
  border-radius: 14px;
  background: #fff;
}
.breach-report .btn {
  flex: 0 0 auto;
  min-width: 92px;
}
.breach-results {
  padding: 14px;
  margin-bottom: 12px;
  border: 1px solid var(--trace-line);
  border-radius: 14px;
  background: #fff;
}
.breach-block + .breach-block {
  margin-top: 12px;
}
.breach-platform-list {
  margin: 0 0 4px;
  padding-left: 18px;
}
.breach-platform-list li {
  line-height: 1.5;
}
</style>
