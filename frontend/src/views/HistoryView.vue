<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { getHistory, getHistoryQuarantine, deleteHistoryItems } from '../api'

defineEmits(['back'])

const CATEGORY_LABELS = {
  face: 'Face',
  location: 'Location detail',
  document: 'Identifying document',
  financial: 'Financial detail',
  contact: 'Contact detail',
  credentials: 'Password or access code',
  metadata: 'Hidden location metadata',
}

const TABS = [
  { key: 'all', label: 'All' },
  { key: 'accepted', label: 'Accepted' },
  { key: 'rejected', label: 'Rejected' },
  { key: 'quarantine', label: 'Quarantined' },
]

const activeTab = ref('all')
const items = ref([])
const selectedIds = ref(new Set())
const loading = ref(false)
const error = ref('')
const deleting = ref(false)

const isQuarantineTab = computed(() => activeTab.value === 'quarantine')
const itemKey = (item) => (isQuarantineTab.value ? item.quarantine_id : item.detection_id)
const allSelected = computed(() => items.value.length > 0 && selectedIds.value.size === items.value.length)

async function load() {
  loading.value = true
  error.value = ''
  selectedIds.value = new Set()
  try {
    items.value = isQuarantineTab.value
      ? await getHistoryQuarantine()
      : await getHistory(activeTab.value)
  } catch (err) {
    error.value = err.message || 'Could not load your history.'
  } finally {
    loading.value = false
  }
}

watch(activeTab, load)
onMounted(load)

function toggleSelected(id) {
  const next = new Set(selectedIds.value)
  next.has(id) ? next.delete(id) : next.add(id)
  selectedIds.value = next
}

function toggleSelectAll() {
  selectedIds.value = allSelected.value ? new Set() : new Set(items.value.map(itemKey))
}

async function deleteSelected() {
  if (selectedIds.value.size === 0) return
  deleting.value = true
  error.value = ''
  try {
    const ids = [...selectedIds.value]
    await deleteHistoryItems(
      isQuarantineTab.value ? { quarantineIds: ids } : { detectionIds: ids }
    )
    await load()
  } catch (err) {
    error.value = err.message || 'Could not delete the selected items.'
  } finally {
    deleting.value = false
  }
}
</script>

<template>
  <div class="d-flex flex-column h-100">
    <div class="border-bottom p-3 text-center fw-bold">History</div>

    <div class="d-flex border-bottom">
      <button
        v-for="tab in TABS"
        :key="tab.key"
        class="tab-btn flex-fill"
        :class="{ active: activeTab === tab.key }"
        @click="activeTab = tab.key"
      >
        {{ tab.label }}
      </button>
    </div>

    <div class="p-3 flex-grow-1 overflow-auto">
      <div v-if="loading" class="text-center text-muted small py-4">Loading…</div>
      <p v-else-if="error" class="text-danger small">{{ error }}</p>
      <div v-else-if="items.length === 0" class="text-center text-muted small py-4">
        Nothing here yet.
      </div>

      <template v-else>
        <div class="form-check mb-2">
          <input
            id="select-all"
            class="form-check-input"
            type="checkbox"
            :checked="allSelected"
            @change="toggleSelectAll"
          />
          <label class="form-check-label small" for="select-all">Select all</label>
        </div>

        <div v-for="item in items" :key="itemKey(item)" class="form-check mb-2">
          <input
            :id="itemKey(item)"
            class="form-check-input"
            type="checkbox"
            :checked="selectedIds.has(itemKey(item))"
            @change="toggleSelected(itemKey(item))"
          />
          <label class="form-check-label small" :for="itemKey(item)">
            <template v-if="isQuarantineTab">
              <span class="d-block">⏸ {{ item.reason }}</span>
              <span class="d-block text-muted">{{ item.state }} · {{ new Date(item.created_at).toLocaleDateString() }}</span>
            </template>
            <template v-else>
              <span class="d-block">{{ CATEGORY_LABELS[item.category] || item.category }}{{ item.detail ? `: ${item.detail}` : '' }}</span>
              <span class="d-block text-muted">
                {{ item.resolution || 'pending' }} · {{ new Date(item.created_at).toLocaleDateString() }}
              </span>
            </template>
          </label>
        </div>
      </template>
    </div>

    <div class="p-3 border-top d-flex flex-column gap-2">
      <button
        class="btn btn-outline-danger w-100"
        :disabled="deleting || selectedIds.size === 0"
        @click="deleteSelected"
      >
        {{ deleting ? 'Deleting…' : `Delete selected (${selectedIds.size})` }}
      </button>
      <button class="btn btn-outline-secondary w-100" @click="$emit('back')">Back</button>
    </div>
  </div>
</template>

<style scoped>
.tab-btn {
  border: none;
  background: none;
  padding: 8px 4px;
  font-size: 0.8rem;
  color: #6c757d;
  border-bottom: 2px solid transparent;
}
.tab-btn.active {
  color: #0d6efd;
  border-bottom-color: #0d6efd;
  font-weight: 600;
}
</style>
