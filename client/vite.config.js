import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import { fictionalAuth } from './dev/fictionalAuth.js'

const apiTarget = process.env.API_TARGET || 'http://127.0.0.1:8000'

export default defineConfig(({ mode }) => ({
  plugins: [react(), ...(mode === 'fictional-auth' ? [fictionalAuth(apiTarget)] : [])],
  server: { proxy: { '/api': apiTarget, '/viewer': apiTarget } },
}))
