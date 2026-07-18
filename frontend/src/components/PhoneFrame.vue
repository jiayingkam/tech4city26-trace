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
  max-width: 100%;
  max-height: calc(100vh - 40px);
  background: #fff;
  border: 10px solid #172235;
  border-radius: 34px;
  box-shadow: var(--trace-shadow);
  overflow: hidden;
}

@media (max-width: 520px) {
  .phone {
    width: 100%;
    height: 100vh;
    max-height: none;
    border: 0;
    border-radius: 0;
    box-shadow: none;
  }
}
</style>
