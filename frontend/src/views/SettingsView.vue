<script setup>
import { ref } from 'vue'
import HamburgerMenu from '../components/HamburgerMenu.vue'
import { updateRetentionMode } from '../api'

const props = defineProps({
  user: { type: Object, required: true },
})
const emit = defineEmits(['back', 'updated', 'history', 'settings', 'mosaic', 'logout'])

const retentionMode = ref(props.user.retention_mode)
const saving = ref(false)
const error = ref('')
const saved = ref(false)

async function save() {
  saving.value = true
  error.value = ''
  saved.value = false
  try {
    const updated = await updateRetentionMode(props.user.user_id, retentionMode.value)
    emit('updated', updated)
    saved.value = true
  } catch (err) {
    error.value = err.message || 'Could not save your settings.'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="app-screen">
    <div class="app-header">
      <HamburgerMenu @history="$emit('history')" @settings="$emit('settings')" @mosaic="$emit('mosaic')" @logout="$emit('logout')" />
      <h1 class="app-title">Settings</h1>
      <p class="app-subtitle">Choose how long Trace remembers scans.</p>
    </div>

    <div class="app-content">
      <p class="fw-bold small mb-3">History retention</p>

      <div class="settings-option">
        <input
          id="mode-auto"
          v-model="retentionMode"
          class="form-check-input"
          type="radio"
          value="auto_expire"
        />
        <label class="form-check-label" for="mode-auto">
          <span class="d-block fw-semibold">Auto-expire after 3 months</span>
          <span class="d-block text-muted small">
            Each post's flags and quarantine records disappear on their own, 3 months
            after that post was scanned. Older posts age out first. You can still open
            History and delete anything sooner yourself, any time.
          </span>
        </label>
      </div>

      <div class="settings-option">
        <input
          id="mode-manual"
          v-model="retentionMode"
          class="form-check-input"
          type="radio"
          value="manual"
        />
        <label class="form-check-label" for="mode-manual">
          <span class="d-block fw-semibold">Keep until I delete it myself</span>
          <span class="d-block text-muted small">
            Nothing is removed automatically — use the History menu to select and delete
            specific posts whenever you want.
          </span>
        </label>
      </div>

      <p v-if="saved" class="text-success small mb-2">Saved.</p>
      <p v-if="error" class="text-danger small mb-2">{{ error }}</p>
    </div>

    <div class="app-action-bar">
      <button class="btn btn-primary w-100" :disabled="saving" @click="save">
        {{ saving ? 'Saving…' : 'Save' }}
      </button>
      <button class="btn btn-outline-secondary w-100" @click="$emit('back')">Back</button>
    </div>
  </div>
</template>

<style scoped>
.settings-option {
  display: flex;
  gap: 10px;
  padding: 14px;
  margin-bottom: 12px;
  border: 1px solid var(--trace-line);
  border-radius: 14px;
  background: #fff;
}
.settings-option .form-check-input {
  margin-left: 0;
}
</style>
