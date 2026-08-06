<script setup>
import { parseCoachMessage } from '../chatFormat.js'
import ChatRichText from './ChatRichText.vue'

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
      >
        <template v-if="m.role === 'user'">{{ m.content }}</template>
        <template v-else>
          <template v-for="(block, bi) in parseCoachMessage(m.content)" :key="bi">
            <div v-if="block.type === 'sim'" class="sim-message">
              <p class="sim-label">⚠️ Simulated — not a real message</p>
              <p v-for="(p, pi) in block.paragraphs" :key="pi" class="sim-text">
                <ChatRichText :segments="p" />
              </p>
            </div>
            <p v-else-if="block.type === 'option'" class="chat-option">
              <span class="chat-option-letter">{{ block.letter }}</span>
              <ChatRichText :segments="block.segments" />
            </p>
            <p v-else class="chat-para"><ChatRichText :segments="block.segments" /></p>
          </template>
        </template>
      </div>
      <div
        v-if="loading"
        class="chat-bubble chat-bubble--coach chat-bubble--typing"
        role="status"
        aria-label="Coach is typing"
      >
        <span class="typing-dot"></span>
        <span class="typing-dot"></span>
        <span class="typing-dot"></span>
      </div>
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
  line-height: 1.5;
}
.chat-bubble--user {
  align-self: flex-end;
  max-width: 85%;
  white-space: pre-wrap;
  background: var(--trace-coral);
  color: #fff;
}
.chat-bubble--coach {
  align-self: flex-start;
  max-width: 92%;
  background: #f0f2f6;
  color: #172235;
}
.chat-panel--fullscreen .chat-bubble--coach {
  max-width: 100%;
}
.chat-para {
  margin: 0 0 6px;
  white-space: pre-wrap;
}
.chat-para:last-child {
  margin-bottom: 0;
}
.chat-option {
  display: flex;
  gap: 8px;
  margin: 0 0 4px;
}
.chat-option:last-child {
  margin-bottom: 0;
}
.chat-option-letter {
  flex: 0 0 auto;
  width: 1.1em;
  font-weight: 700;
}
.sim-message {
  background: #fffaf0;
  border: 1px solid #f3d48b;
  border-radius: 10px;
  padding: 8px 10px;
  margin: 6px 0;
}
.sim-label {
  margin: 0 0 4px;
  font-size: 0.7rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  color: #7a4d00;
}
.sim-text {
  margin: 0;
  white-space: pre-wrap;
  color: #7a4d00;
}
.sim-text:not(:last-child) {
  margin-bottom: 4px;
}
.chat-bubble--typing {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 10px 12px;
}
.typing-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #98a2b3;
  animation: typing-bounce 1.2s infinite ease-in-out;
}
.typing-dot:nth-child(2) { animation-delay: 0.15s; }
.typing-dot:nth-child(3) { animation-delay: 0.3s; }
@keyframes typing-bounce {
  0%, 70%, 100% { transform: translateY(0); opacity: 0.35; }
  35% { transform: translateY(-4px); opacity: 1; }
}
/* Respect users who prefer no motion — show steady dots instead */
@media (prefers-reduced-motion: reduce) {
  .typing-dot { animation: none; opacity: 0.6; }
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
