// Runs before `npm run dev` (npm "predev" hook). If the backend venv or the
// Node deps are missing, it runs the full setup once; otherwise it's a no-op.
import { spawnSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = dirname(dirname(fileURLToPath(import.meta.url)))
const win = process.platform === 'win32'

const venvBin = join(root, 'backend', '.venv', win ? 'Scripts' : 'bin')
const nodeDepsOk = existsSync(join(root, 'node_modules', 'concurrently'))

if (!existsSync(venvBin) || !nodeDepsOk) {
  console.log('[dev] first run — installing dependencies…')
  const r = spawnSync('node', [join(root, 'scripts', 'setup.mjs')], { stdio: 'inherit' })
  process.exit(r.status ?? 1)
}
