import { chmodSync, existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { resolve } from 'node:path'
import { execFileSync } from 'node:child_process'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const cortexHome = process.env.CORTEX_HOME ?? resolve(homedir(), '.hermes/xibalba-cortex')
const devTokenFile = process.env.CORTEX_DEV_TOKEN_FILE ?? resolve(cortexHome, '.viewer-dev.token')

function localDevToken(): string {
  if (existsSync(devTokenFile)) return readFileSync(devTokenFile, 'utf8').trim()
  mkdirSync(cortexHome, { recursive: true })
  const output = execFileSync(
    'uv',
    ['run', 'xibalba-cortex-ingest-tokens', '--home', cortexHome, 'issue', '--label', 'viewer-local-dev', '--role', 'operator'],
    { cwd: resolve(import.meta.dirname, '..'), encoding: 'utf8', stdio: ['ignore', 'pipe', 'inherit'] },
  )
  const token = output.trim().split(/\r?\n/).at(-1)?.trim() ?? ''
  if (!token) throw new Error('Cortex development token issuance returned no token')
  writeFileSync(devTokenFile, `${token}\n`, { mode: 0o600 })
  chmodSync(devTokenFile, 0o600)
  return token
}

// Explicit, non-default port -- avoids any ambiguity with the Dockerized integrity-dashboard
// instances already mapped to 5173/5174 (see docker-compose.yml in integrity-core).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5190,
    host: '127.0.0.1',
    proxy: {
      '/cortex-api': {
        target: process.env.CORTEX_LOCAL_API_URL ?? 'http://127.0.0.1:8420',
        changeOrigin: false,
        rewrite: (path) => path.replace(/^\/cortex-api/, ''),
        configure: (proxy) => {
          const token = localDevToken()
          proxy.on('proxyReq', (request) => request.setHeader('Authorization', `Bearer ${token}`))
        },
      },
    },
  },
  build: {
    chunkSizeWarningLimit: 1500,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules')) {
            return 'vendor';
          }
        }
      }
    }
  }
})
