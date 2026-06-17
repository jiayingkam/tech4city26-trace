<template>
  <div class="phone">
    <slot />
  </div>
</template>

<style scoped>
.phone {
  width: 390px;
  height: 800px;
  max-height: 90vh;
  background: white;
  border-radius: 36px;
  border: 10px solid #1a1a1a;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.25);
  overflow-y: auto;
}
</style>