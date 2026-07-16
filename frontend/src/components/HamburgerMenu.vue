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
      class="btn btn-light btn-sm hamburger-btn"
      aria-label="Menu"
      @click="toggle"
    >
      ☰
    </button>

    <div v-if="open" class="hamburger-backdrop" @click="close"></div>

    <div v-if="open" class="hamburger-dropdown shadow-sm">
      <button class="dropdown-item-btn" @click="close(); $emit('history')">History</button>
      <button class="dropdown-item-btn" @click="close(); $emit('settings')">Settings</button>
      <button class="dropdown-item-btn text-danger" @click="close(); $emit('logout')">Log out</button>
    </div>
  </div>
</template>

<style scoped>
.hamburger-wrap {
  position: absolute;
  top: 10px;
  right: 10px;
  z-index: 20;
}
.hamburger-btn {
  border-radius: 50%;
  width: 36px;
  height: 36px;
  padding: 0;
  line-height: 1;
}
.hamburger-backdrop {
  position: fixed;
  inset: 0;
  z-index: 19;
}
.hamburger-dropdown {
  position: absolute;
  top: 42px;
  right: 0;
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
