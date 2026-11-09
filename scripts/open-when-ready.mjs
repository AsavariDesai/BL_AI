// Polls the web dev server and opens the app in the default browser once it's up.
// Runs as a concurrently child of `npm run dev`; always exits 0 so it never
// tears the dev servers down.
import { spawn } from 'node:child_process'

const url = process.env.APP_URL || 'http://localhost:5173'
const deadlineMs = Date.now() + 30_000

async function isReady() {
  try {
    const res = await fetch(url, { method: 'HEAD' })
    return res.status < 500
  } catch {
    return false
  }
}

function openBrowser(target) {
  const p = process.platform
  const [cmd, args] =
    p === 'win32'
      ? ['cmd', ['/c', 'start', '""', target]]
      : p === 'darwin'
        ? ['open', [target]]
        : ['xdg-open', [target]]
  try {
    spawn(cmd, args, { stdio: 'ignore', detached: true }).unref()
  } catch {
    /* headless / no browser — ignore */
  }
}

while (Date.now() < deadlineMs) {
  if (await isReady()) {
    console.log(`[open] launching ${url}`)
    openBrowser(url)
    process.exit(0)
  }
  await new Promise((r) => setTimeout(r, 400))
}

console.log(`[open] web server not up after 30s — open ${url} manually`)
process.exit(0)
