<script setup>
import { ref, computed } from 'vue'
import HamburgerMenu from '../components/HamburgerMenu.vue'
import { traceQuiz } from '../content/traceQuiz'

defineEmits(['back', 'history', 'settings', 'mosaic', 'logout', 'quiz'])

// 'topics' (pick a round) -> 'question' (answering) -> 'summary' (round score)
const stage = ref('topics')
const topicIndex = ref(null)
const questionIndex = ref(0)
const selectedOption = ref(null)
const answers = ref([])
// Session-only best score per topic, keyed by index — resets on reload,
// same as the rest of the app's in-memory view state.
const bestScores = ref({})

const topic = computed(() => (topicIndex.value === null ? null : traceQuiz[topicIndex.value]))
const question = computed(() => topic.value?.questions[questionIndex.value] ?? null)
const isLastQuestion = computed(() => topic.value && questionIndex.value === topic.value.questions.length - 1)
const score = computed(() => answers.value.filter((a) => a.correct).length)
const hasAnswered = computed(() => selectedOption.value !== null)

function startTopic(i) {
  topicIndex.value = i
  questionIndex.value = 0
  selectedOption.value = null
  answers.value = []
  stage.value = 'question'
}

function selectOption(i) {
  if (hasAnswered.value) return
  selectedOption.value = i
  answers.value.push({ selected: i, correct: i === question.value.correctIndex })
}

function nextQuestion() {
  if (isLastQuestion.value) {
    const prevBest = bestScores.value[topicIndex.value] || 0
    bestScores.value = { ...bestScores.value, [topicIndex.value]: Math.max(prevBest, score.value) }
    stage.value = 'summary'
    return
  }
  questionIndex.value += 1
  selectedOption.value = null
}

function retakeTopic() {
  startTopic(topicIndex.value)
}

function backToTopics() {
  stage.value = 'topics'
  topicIndex.value = null
}

function optionClass(i) {
  if (!hasAnswered.value) return ''
  if (i === question.value.correctIndex) return 'quiz-option--correct'
  if (i === selectedOption.value) return 'quiz-option--wrong'
  return 'quiz-option--muted'
}
</script>

<template>
  <div class="app-screen">
    <div class="app-header">
      <HamburgerMenu @history="$emit('history')" @settings="$emit('settings')" @mosaic="$emit('mosaic')" @logout="$emit('logout')" @quiz="$emit('quiz')" />
      <h1 class="app-title">Privacy IQ quiz</h1>
      <p class="app-subtitle">
        {{ stage === 'topics' ? 'Short rounds on how leaks actually happen.' : topic.topic }}
      </p>
    </div>

    <div class="app-content">
      <!-- Round picker -->
      <div v-if="stage === 'topics'" class="d-flex flex-column gap-2">
        <button
          v-for="(t, i) in traceQuiz"
          :key="t.topic"
          type="button"
          class="quiz-topic-card"
          @click="startTopic(i)"
        >
          <div class="flex-grow-1">
            <span class="d-block fw-semibold">{{ t.topic }}</span>
            <span class="d-block text-muted small">{{ t.subtitle }}</span>
          </div>
          <span v-if="bestScores[i] !== undefined" class="quiz-score-badge">
            {{ bestScores[i] }}/{{ t.questions.length }}
          </span>
          <span v-else class="quiz-count-badge">{{ t.questions.length }} Qs</span>
        </button>
      </div>

      <!-- Question -->
      <div v-else-if="stage === 'question'" class="d-flex flex-column gap-3">
        <div class="quiz-progress">
          <div
            class="quiz-progress-fill"
            :style="{ width: `${((questionIndex + 1) / topic.questions.length) * 100}%` }"
          ></div>
        </div>
        <p class="small text-muted mb-0">Question {{ questionIndex + 1 }} of {{ topic.questions.length }}</p>

        <p class="fw-semibold mb-0">{{ question.question }}</p>

        <div class="d-flex flex-column gap-2">
          <button
            v-for="(opt, i) in question.options"
            :key="i"
            type="button"
            class="quiz-option"
            :class="optionClass(i)"
            :disabled="hasAnswered"
            @click="selectOption(i)"
          >
            {{ opt }}
          </button>
        </div>

        <div v-if="hasAnswered" class="quiz-explanation">
          <p class="mb-0 small fw-semibold" :class="answers[answers.length - 1].correct ? 'text-success' : 'text-danger'">
            {{ answers[answers.length - 1].correct ? 'Correct.' : 'Not quite.' }}
          </p>
          <p class="mb-0 small text-muted mt-1">{{ question.explanation }}</p>
        </div>
      </div>

      <!-- Round summary -->
      <div v-else-if="stage === 'summary'" class="d-flex flex-column gap-3 text-center">
        <p class="quiz-summary-score mb-0">{{ score }}/{{ topic.questions.length }}</p>
        <p class="small text-muted mb-0">on {{ topic.topic }}</p>
        <div class="quiz-takeaway">
          <p class="mb-0 small">{{ topic.takeaway }}</p>
        </div>
      </div>
    </div>

    <div class="app-action-bar">
      <button
        v-if="stage === 'question'"
        class="btn btn-primary w-100"
        :disabled="!hasAnswered"
        @click="nextQuestion"
      >
        {{ isLastQuestion ? 'See results' : 'Next question' }}
      </button>
      <button v-if="stage === 'summary'" class="btn btn-primary w-100" @click="retakeTopic">Retake round</button>
      <button v-if="stage === 'summary'" class="btn btn-outline-secondary w-100" @click="backToTopics">More rounds</button>
      <button v-if="stage === 'question'" class="btn btn-outline-secondary w-100" @click="backToTopics">Exit round</button>
      <button v-if="stage === 'topics'" class="btn btn-outline-secondary w-100" @click="$emit('back')">Back</button>
    </div>
  </div>
</template>

<style scoped>
.quiz-topic-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px;
  border: 1px solid var(--trace-line);
  border-radius: 14px;
  background: #fff;
  text-align: left;
}
.quiz-topic-card:hover {
  border-color: var(--trace-primary);
}
.quiz-count-badge {
  flex: 0 0 auto;
  font-size: 0.68rem;
  font-weight: 700;
  color: var(--trace-muted);
  background: var(--trace-soft);
  padding: 3px 8px;
  border-radius: 999px;
  white-space: nowrap;
}
.quiz-score-badge {
  flex: 0 0 auto;
  font-size: 0.68rem;
  font-weight: 700;
  color: var(--trace-success);
  background: #e9f8f2;
  padding: 3px 8px;
  border-radius: 999px;
  white-space: nowrap;
}
.quiz-progress {
  height: 6px;
  border-radius: 999px;
  background: var(--trace-soft);
  overflow: hidden;
}
.quiz-progress-fill {
  height: 100%;
  background: var(--trace-primary);
  border-radius: 999px;
  transition: width 0.2s ease;
}
.quiz-option {
  padding: 12px 14px;
  border: 1px solid var(--trace-line);
  border-radius: 12px;
  background: #fff;
  text-align: left;
  font-size: 0.88rem;
  font-weight: 600;
}
.quiz-option:hover:not(:disabled) {
  border-color: var(--trace-primary);
}
.quiz-option:disabled {
  opacity: 1;
}
.quiz-option--correct {
  border-color: var(--trace-success);
  background: #e9f8f2;
  color: var(--trace-success);
}
.quiz-option--wrong {
  border-color: var(--trace-danger);
  background: #fde8e7;
  color: var(--trace-danger);
}
.quiz-option--muted {
  opacity: 0.55;
}
.quiz-explanation {
  padding: 12px 14px;
  border-radius: 12px;
  background: var(--trace-soft);
}
.quiz-summary-score {
  font-size: 2.6rem;
  font-weight: 800;
  color: var(--trace-primary);
}
.quiz-takeaway {
  padding: 14px;
  border-radius: 14px;
  background: linear-gradient(135deg, #effaf6 0%, #f8fbff 100%);
  border: 1px solid #cce8df;
}
</style>
