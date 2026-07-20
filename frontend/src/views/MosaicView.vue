<script setup>
import { ref, onMounted, onUnmounted, nextTick } from 'vue'
import { getMe, getMosaicTrajectory } from '../api'

defineEmits(['back', 'history', 'settings', 'logout'])

const loading = ref(true)
const error = ref(null)
const trajectory = ref([])
const finalK = ref(null)
const postCount = ref(0)
const canvasRef = ref(null)
let chartInstance = null

function formatK(k) {
  if (k >= 1_000_000) return `~${(k / 1_000_000).toFixed(1)}M people`
  if (k >= 1_000) return `~${Math.round(k / 1_000)}K people`
  return `~${k} people`
}

function riskBadgeClass(level) {
  if (level === 'high') return 'badge bg-danger'
  if (level === 'medium') return 'badge bg-warning text-dark'
  return 'badge bg-success'
}

function shortCaption(text) {
  if (!text) return '(image only)'
  return text.length > 28 ? text.slice(0, 25) + '…' : text
}

async function buildChart() {
  await nextTick()
  if (!canvasRef.value || trajectory.value.length === 0) return

  const { Chart, LineController, LineElement, PointElement, LogarithmicScale,
          CategoryScale, Tooltip } = await import('chart.js')
  Chart.register(LineController, LineElement, PointElement, LogarithmicScale,
                 CategoryScale, Tooltip)

  const points = trajectory.value
  const colors = points.map(p =>
    p.risk_level === 'high' ? '#dc3545' :
    p.risk_level === 'medium' ? '#fd7e14' : '#198754'
  )

  chartInstance = new Chart(canvasRef.value, {
    type: 'line',
    data: {
      labels: points.map(p => shortCaption(p.text_content)),
      datasets: [{
        data: points.map(p => p.k_after),
        borderColor: '#2f6fed',
        backgroundColor: 'rgba(47,111,237,0.08)',
        pointBackgroundColor: colors,
        pointBorderColor: colors,
        pointRadius: 7,
        pointHoverRadius: 9,
        tension: 0.3,
        fill: true,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        y: {
          type: 'logarithmic',
          title: { display: true, text: 'People who could be you (log scale)', font: { size: 11 } },
          ticks: {
            callback(v) {
              if (v === 6000000) return '6M'
              if (v === 1000000) return '1M'
              if (v === 100000) return '100K'
              if (v === 10000) return '10K'
              if (v === 1000) return '1K'
              if (v === 100) return '100'
              if (v === 10) return '10'
              if (v === 1) return '1'
              return null
            },
          },
        },
        x: {
          ticks: { maxRotation: 35, font: { size: 10 } },
        },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: (items) => trajectory.value[items[0].dataIndex]?.text_content || '(image only)',
            label: (item) => {
              const p = trajectory.value[item.dataIndex]
              return [
                `Roughly ${formatK(p.k_after)} could be you`,
                `This post added ~${p.delta_bits} bits`,
                `Risk level: ${p.risk_level}`,
              ]
            },
          },
        },
      },
    },
  })
}

async function load() {
  try {
    const user = await getMe()
    const data = await getMosaicTrajectory(user.user_id)
    trajectory.value = data.trajectory || []
    finalK.value = data.final_k
    postCount.value = data.post_count || 0
    await buildChart()
  } catch (err) {
    error.value = err.message || 'Could not load privacy data.'
  } finally {
    loading.value = false
  }
}

onMounted(load)
onUnmounted(() => chartInstance?.destroy())
</script>

<template>
  <div class="mosaic-screen app-screen d-flex flex-column">

    <div class="mosaic-header d-flex align-items-center px-3 pt-3 pb-2">
      <button class="btn btn-sm btn-link p-0 me-2 text-secondary" @click="$emit('back')">← Back</button>
      <h6 class="mb-0 fw-bold">Privacy risk</h6>
    </div>

    <div v-if="loading" class="flex-grow-1 d-flex flex-column align-items-center justify-content-center gap-2">
      <div class="spinner-border text-primary" role="status"></div>
      <p class="text-secondary small mb-0">Analysing your posts…</p>
    </div>

    <div v-else-if="error" class="flex-grow-1 d-flex align-items-center justify-content-center px-4 text-center">
      <p class="text-danger small">{{ error }}</p>
    </div>

    <div v-else-if="trajectory.length === 0" class="flex-grow-1 d-flex align-items-center justify-content-center px-4 text-center">
      <p class="text-secondary small">No posts yet to analyse.</p>
    </div>

    <div v-else class="flex-grow-1 d-flex flex-column overflow-auto px-3 pb-3 gap-3">

      <div class="mosaic-summary-card p-3 rounded-3">
        <p class="mb-1 small text-secondary">After {{ postCount }} post{{ postCount === 1 ? '' : 's' }}</p>
        <p class="mb-0 fw-bold fs-6">
          Roughly <span class="text-primary">{{ formatK(finalK) }}</span>
          could be identified as you from your posts combined.
        </p>
      </div>

      <div class="chart-wrap">
        <canvas ref="canvasRef"></canvas>
      </div>

      <div class="d-flex flex-column gap-2">
        <p class="small text-secondary mb-1 fw-semibold">Post breakdown</p>
        <div
          v-for="(point, i) in trajectory"
          :key="point.draft_id"
          class="post-row d-flex align-items-start gap-2 p-2 rounded-3"
        >
          <span class="post-num text-secondary small">{{ i + 1 }}</span>
          <div class="flex-grow-1 min-w-0">
            <p class="mb-0 small text-truncate">{{ point.text_content || '(image only)' }}</p>
            <p class="mb-0 x-small text-secondary">{{ formatK(point.k_after) }} could be you after this post</p>
          </div>
          <span :class="riskBadgeClass(point.risk_level)" style="font-size:0.7rem;white-space:nowrap">
            {{ point.risk_level }}
          </span>
        </div>
      </div>

    </div>
  </div>
</template>

<style scoped>
.mosaic-screen {
  height: 100%;
}
.mosaic-header {
  border-bottom: 1px solid var(--trace-line, #e8edf5);
}
.mosaic-summary-card {
  background: #f0f5ff;
  border: 1px solid #d0e0ff;
}
.chart-wrap {
  height: 200px;
  position: relative;
}
.post-row {
  background: #fafbfc;
  border: 1px solid var(--trace-line, #e8edf5);
}
.post-num {
  min-width: 18px;
  text-align: right;
}
.x-small {
  font-size: 0.72rem;
}
</style>
