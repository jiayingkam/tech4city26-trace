<script setup>
import { ref } from 'vue'

defineEmits(['history', 'settings', 'logout'])

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
      ☰
    </button>

    <div v-if="open" class="hamburger-backdrop" @click="close"></div>

    <div v-if="open" class="hamburger-dropdown shadow-sm">
      <button class="dropdown-item-btn" @click="close(); $emit('settings')">Settings</button>
      <button class="dropdown-item-btn" @click="close(); $emit('history')">History</button>
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
  top: 14px;
  left: 14px;
  z-index: 20;
}
.hamburger-btn {
  border: none;
  background: none;
  font-size: 1.25rem;
  line-height: 1;
  padding: 4px 6px;
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
  top: 34px;
  left: 0;
  background: white;
  border: 1px solid rgba(0, 0, 0, 0.1);
  border-radius: 8px;
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
  padding: 10px 14px;
  font-size: 0.9rem;
}
.dropdown-item-btn:hover {
  background: rgba(0, 0, 0, 0.05);
}
</style>
