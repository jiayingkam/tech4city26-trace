<script setup>
import { ref } from 'vue'
import PhoneFrame from './components/PhoneFrame.vue'
import LoginView from './views/LoginView.vue' 

const step = ref(1)

function next() {
  step.value++
}
</script>

<template>
  <div class="d-flex justify-content-center align-items-center min-vh-100 bg-light">
    <PhoneFrame>

      <!-- Step 1: Login -->
      <LoginView v-if="step === 1" @success="next" />

      <!-- Step 2: Compose (your existing screen — just renumbered) -->
      <div v-else-if="step === 2" class="d-flex flex-column h-100">
        <div class="border-bottom p-3 text-center fw-bold">New post</div>

        <div class="p-3 flex-grow-1">
          <div class="mock-photo mb-3">
            <div class="mock-building"></div>
            <div class="mock-sign">BLK 123</div>
          </div>
          <p class="mb-1 fw-semibold">mia_xx</p>
          <p class="text-muted mb-0">Vacation mode on 🌴 away all week, see you soon!</p>
        </div>

        <div class="p-3 border-top">
          <button class="btn btn-primary w-100" @click="next">Share</button>
        </div>
      </div>

      <!-- Step 2: placeholder for the scan screen (next) -->
      <div v-else-if="step === 2" class="p-4 text-center">
        <p>Scan screen goes here next.</p>
        <button class="btn btn-outline-secondary" @click="step = 1">Back to start</button>
      </div>

    </PhoneFrame>
  </div>
</template>

<style scoped>
.mock-photo {
  position: relative;
  height: 260px;
  border-radius: 12px;
  background: linear-gradient(160deg, #ffd194 0%, #a1c4fd 100%);
  overflow: hidden;
}
.mock-building {
  position: absolute;
  bottom: 0;
  left: 20%;
  width: 60%;
  height: 45%;
  background: #6b7280;
  border-radius: 6px 6px 0 0;
}
.mock-sign {
  position: absolute;
  bottom: 12px;
  left: 50%;
  transform: translateX(-50%);
  background: #fff;
  color: #111;
  font-weight: 700;
  font-size: 0.8rem;
  padding: 2px 10px;
  border-radius: 4px;
}
</style>