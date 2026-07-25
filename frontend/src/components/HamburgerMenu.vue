<script setup>
import { ref } from 'vue'

defineEmits(['history', 'settings', 'logout', 'mosaic'])

const open = ref(false)

function toggle() {
  open.value = !open.value
}

function close() {
  open.value = false
}
</script>

<template>
  <div class="hamburger-wrap">
    <button
      type="button"
      class="hamburger-btn"
      aria-label="Menu"
      @click="toggle"
    >
      <span></span>
      <span></span>
      <span></span>
    </button>

    <div v-if="open" class="hamburger-backdrop" @click="close"></div>

    <div v-if="open" class="hamburger-dropdown shadow-sm">
      <button class="dropdown-item-btn" @click="close(); $emit('settings')">Settings</button>
      <button class="dropdown-item-btn" @click="close(); $emit('history')">History</button>
      <button class="dropdown-item-btn" @click="close(); $emit('mosaic')">Privacy risk</button>
      <button class="dropdown-item-btn text-danger" @click="close(); $emit('logout')">Log out</button>
    </div>
  </div>
</template>

<style scoped>
/* Positioned top-left, on top of whichever view's own header row is
   showing — anchored to PhoneFrame's .phone (position: relative there),
   so it always stays within the phone mockup instead of the browser
   viewport. */
.hamburger-wrap {
  position: absolute;
  top: 12px;
  left: 12px;
  z-index: 20;
}
.hamburger-btn {
  display: inline-flex;
  flex-direction: column;
  justify-content: center;
  gap: 4px;
  width: 38px;
  height: 38px;
  border: 1px solid rgba(47, 111, 237, 0.14);
  border-radius: 12px;
  background: #fff;
  box-shadow: 0 8px 18px rgba(23, 34, 53, 0.08);
}
.hamburger-btn span {
  display: block;
  width: 16px;
  height: 2px;
  margin: 0 auto;
  border-radius: 99px;
  background: var(--trace-ink);
}
.hamburger-backdrop {
  position: absolute;
  top: -14px;
  left: -14px;
  width: 100vw;
  height: 100vh;
  z-index: 19;
}
.hamburger-dropdown {
  position: absolute;
  top: 44px;
  left: 0;
  background: white;
  border: 1px solid var(--trace-line);
  border-radius: 12px;
  min-width: 160px;
  overflow: hidden;
  z-index: 21;
}
.dropdown-item-btn {
  display: block;
  width: 100%;
  text-align: left;
  border: none;
  background: none;
  padding: 12px 14px;
  font-size: 0.9rem;
  font-weight: 700;
}
.dropdown-item-btn:hover {
  background: #f3f7ff;
}
</style>
