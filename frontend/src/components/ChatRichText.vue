<script setup>
defineProps({
  segments: { type: Array, default: () => [] },
})
</script>

<template>
  <template v-for="(seg, i) in segments" :key="i">
    <strong v-if="seg.bold">{{ seg.text }}</strong>
    <template v-else>{{ seg.text }}</template>
  </template>
</template>
