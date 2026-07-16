<template>
  <div class="phone">
    <slot />
  </div>
</template>

<style scoped>
.phone {
  position: relative; /* anchors absolutely-positioned children (e.g. the hamburger menu) to the phone itself, not the browser viewport */
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