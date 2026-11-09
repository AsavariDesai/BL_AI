import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  // `open` is driven by the root scripts (VITE_OPEN=1) so `npm run dev` from the
  // repo root launches the browser, while `vitest` / CI runs stay headless.
  server: { port: 5173, open: process.env.VITE_OPEN === '1' },
})
