import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Explicit, non-default port -- avoids any ambiguity with the Dockerized integrity-dashboard
// instances already mapped to 5173/5174 (see docker-compose.yml in INTEGRITY-LATEST).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5190,
  },
})
