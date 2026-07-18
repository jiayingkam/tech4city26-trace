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
  <div class="app-screen">
    <div class="app-header">
      <h1 class="app-title">New post</h1>
      <p class="app-subtitle">Add a photo and Trace will check it first.</p>
    </div>

    <div class="app-content">
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
          <div class="camera-dot">+</div>
          <p class="fw-bold mb-1">Add a photo</p>
          <p class="small mb-0">Trace can spot faces, places, text, and hidden data.</p>
        </div>
      </div>

      <textarea
        v-model="caption"
        class="form-control"
        rows="4"
        placeholder="Write a caption (optional)"
      ></textarea>

      <p v-if="error" class="text-danger small mt-2 mb-0">{{ error }}</p>
    </div>

    <div class="app-action-bar">
      <button class="btn btn-primary w-100" @click="share">Check before sharing</button>
    </div>
  </div>
</template>

<style scoped>
.photo-picker {
  min-height: 300px;
  border-radius: 18px;
  border: 2px dashed #b9c8dd;
  overflow: hidden;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  background:
    linear-gradient(135deg, rgba(47, 111, 237, 0.08), transparent),
    #f7faff;
}
.photo-preview {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.photo-placeholder {
  max-width: 240px;
  padding: 18px;
  text-align: center;
}
.camera-dot {
  display: grid;
  place-items: center;
  width: 58px;
  height: 58px;
  margin: 0 auto 12px;
  border-radius: 18px;
  background: #e7f0ff;
  color: var(--trace-primary);
  font-size: 2rem;
  font-weight: 800;
}
</style>
