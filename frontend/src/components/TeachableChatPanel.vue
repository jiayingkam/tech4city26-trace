<script setup>
defineProps({
  messages: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  error: { type: String, default: null },
  discussionPrompt: { type: String, default: null },
  showSimSuggestion: { type: Boolean, default: false },
  modelValue: { type: String, default: '' },
  fullscreen: { type: Boolean, default: false },
})

defineEmits(['update:modelValue', 'send'])
</script>

<template>
  <div class="chat-panel" :class="{ 'chat-panel--fullscreen': fullscreen }">
    <button
      v-if="!messages.length && showSimSuggestion"
      type="button"
      class="chat-suggestion chat-suggestion--sim"
      @click="$emit('send', 'Show me what could happen if this gets shared.')"
    >
      ⚠️ Show me what could happen
    </button>
    <button
      v-if="!messages.length && discussionPrompt"
      type="button"
      class="chat-suggestion"
      @click="$emit('send', discussionPrompt)"
    >
      💬 {{ discussionPrompt }}
    </button>

    <div v-if="messages.length" class="chat-thread mb-2">
      <div
        v-for="(m, i) in messages"
        :key="i"
        class="chat-bubble"
        :class="m.role === 'user' ? 'chat-bubble--user' : 'chat-bubble--coach'"
      >{{ m.content }}</div>
      <div v-if="loading" class="chat-bubble chat-bubble--coach chat-bubble--typing">···</div>
    </div>

    <p v-if="error" class="chat-error small mb-2">{{ error }}</p>

    <form class="chat-input-row" @submit.prevent="$emit('send')">
      <input
        :value="modelValue"
        @input="$emit('update:modelValue', $event.target.value)"
        type="text"
        class="chat-input"
        placeholder="Ask a question…"
        :disabled="loading"
      />
      <button type="submit" class="chat-send" :disabled="loading || !modelValue.trim()">Send</button>
    </form>
  </div>
</template>

<style scoped>
.chat-panel {
  display: flex;
  flex-direction: column;
}
.chat-suggestion {
  display: block;
  width: 100%;
  text-align: left;
  background: #f5f7fb;
  border: 1px solid var(--trace-line);
  border-radius: 12px;
  padding: 8px 10px;
  font-size: 0.78rem;
  color: #344054;
  margin-bottom: 8px;
}
.chat-suggestion--sim {
  background: #fffaf0;
  border-color: #f3d48b;
  color: #7a4d00;
  font-weight: 600;
}
.chat-thread {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 220px;
  overflow-y: auto;
}
.chat-panel--fullscreen {
  flex: 1;
  min-height: 0;
}
.chat-panel--fullscreen .chat-thread {
  flex: 1 1 auto;
  max-height: none;
  min-height: 0;
}
.chat-bubble {
  font-size: 0.8rem;
  padding: 7px 10px;
  border-radius: 12px;
  max-width: 85%;
  line-height: 1.35;
  white-space: pre-wrap;
}
.chat-bubble--user {
  align-self: flex-end;
  background: var(--trace-coral);
  color: #fff;
}
.chat-bubble--coach {
  align-self: flex-start;
  background: #f0f2f6;
  color: #172235;
}
.chat-bubble--typing {
  font-weight: 700;
  letter-spacing: 2px;
}
.chat-error {
  color: #d94841;
}
.chat-input-row {
  display: flex;
  gap: 6px;
}
.chat-input {
  flex: 1;
  border: 1px solid var(--trace-line);
  border-radius: 999px;
  padding: 6px 12px;
  font-size: 0.8rem;
}
.chat-send {
  border: none;
  border-radius: 999px;
  padding: 6px 14px;
  font-size: 0.8rem;
  font-weight: 600;
  background: var(--trace-coral);
  color: #fff;
}
.chat-send:disabled {
  opacity: 0.5;
}
</style>
