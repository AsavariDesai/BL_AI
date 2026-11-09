// Run the backend's Python from the repo's virtualenv, from any OS, with cwd=backend/.
//   node scripts/py.mjs -m uvicorn app.api:app --reload --port 8000
//   node scripts/py.mjs -m pytest
import { spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = dirname(dirname(fileURLToPath(import.meta.url)))
const backend = join(root, 'backend')
const win = process.platform === 'win32'

const venvPython = win
  ? join(backend, '.venv', 'Scripts', 'python.exe')
  : join(backend, '.venv', 'bin', 'python')
const python = existsSync(venvPython) ? venvPython : win ? 'python' : 'python3'

if (python !== venvPython) {
  console.warn('[py] backend/.venv not found — using system Python. Run `npm run setup` first.')
}

const child = spawn(python, process.argv.slice(2), { cwd: backend, stdio: 'inherit' })
child.on('exit', (code) => process.exit(code ?? 0))
child.on('error', (err) => {
  console.error('[py] failed to start Python:', err.message)
  process.exit(1)
})
