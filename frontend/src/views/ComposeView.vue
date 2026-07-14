<script setup>
import { ref, onBeforeUnmount } from 'vue'

const emit = defineEmits(['share'])

const photoFile = ref(null)
const photoPreviewUrl = ref(null)
const caption = ref('')
const error = ref('')
const fileInput = ref(null)

function pickPhoto() {
  fileInput.value?.click()
}

function onFileChange(e) {
  const file = e.target.files[0]
  if (!file) return
  error.value = ''
  photoFile.value = file
  if (photoPreviewUrl.value) URL.revokeObjectURL(photoPreviewUrl.value)
  photoPreviewUrl.value = URL.createObjectURL(file)
}

function share() {
  if (!photoFile.value) {
    error.value = 'Add a photo before sharing.'
    return
  }
  emit('share', { photoFile: photoFile.value, caption: caption.value })
}

onBeforeUnmount(() => {
  if (photoPreviewUrl.value) URL.revokeObjectURL(photoPreviewUrl.value)
})
</script>

<template>
  <div class="d-flex flex-column h-100">
    <div class="border-bottom p-3 text-center fw-bold">New post</div>

    <div class="p-3 flex-grow-1 overflow-auto">
      <input
        ref="fileInput"
        type="file"
        accept="image/*"
        class="d-none"
        @change="onFileChange"
      />

      <div class="photo-picker mb-3" @click="pickPhoto">
        <img v-if="photoPreviewUrl" :src="photoPreviewUrl" class="photo-preview" alt="Selected photo" />
        <div v-else class="photo-placeholder text-muted">
          <div class="fs-1 mb-1">📷</div>
          <p class="small mb-0">Tap to add a photo</p>
        </div>
      </div>

      <textarea
        v-model="caption"
        class="form-control"
        rows="3"
        placeholder="Write a caption… (optional)"
      ></textarea>

      <p v-if="error" class="text-danger small mt-2 mb-0">{{ error }}</p>
    </div>

    <div class="p-3 border-top">
      <button class="btn btn-primary w-100" @click="share">Share</button>
    </div>
  </div>
</template>

<style scoped>
.photo-picker {
  height: 260px;
  border-radius: 12px;
  border: 2px dashed #ced4da;
  overflow: hidden;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f8f9fa;
}
.photo-preview {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
</style>
