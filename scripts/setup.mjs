// One-shot setup for the whole repo: backend venv + deps, then Node workspaces.
//   npm run setup
import { spawnSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = dirname(dirname(fileURLToPath(import.meta.url)))
const backend = join(root, 'backend')
const win = process.platform === 'win32'

function run(cmd, args, opts = {}) {
  console.log(`\n$ ${cmd} ${args.join(' ')}`)
  const r = spawnSync(cmd, args, { stdio: 'inherit', ...opts })
  if (r.status !== 0) {
    console.error(`\n[setup] "${cmd}" exited ${r.status}`)
    process.exit(r.status ?? 1)
  }
}

const venv = join(backend, '.venv')
const python = win ? join(venv, 'Scripts', 'python.exe') : join(venv, 'bin', 'python')

if (!existsSync(venv)) {
  run(win ? 'python' : 'python3', ['-m', 'venv', venv])
}
run(python, ['-m', 'pip', 'install', '-q', '--upgrade', 'pip'])
run(python, [
  '-m', 'pip', 'install', '-q',
  '-r', join(backend, 'requirements.txt'),
  '-r', join(backend, 'requirements-dev.txt'),
])

run('npm', ['install'], { cwd: root, shell: win })

console.log('\n[setup] done. Next: `npm run dev` (both) or `npm test`.')
