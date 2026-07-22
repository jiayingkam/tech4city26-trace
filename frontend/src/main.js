import 'bootstrap/dist/css/bootstrap.min.css'
// Self-hosted Inter — bundled by Vite so every machine (Windows/macOS/Linux)
// renders the identical font instead of falling back to a different system
// font per OS. Weights match those used across the app (400–800).
import '@fontsource/inter/400.css'
import '@fontsource/inter/500.css'
import '@fontsource/inter/600.css'
import '@fontsource/inter/700.css'
import '@fontsource/inter/800.css'
import { createApp } from 'vue'
import App from './App.vue'
import './assets/main.css'
import './styles/scanMascot.css'

createApp(App).mount('#app')
