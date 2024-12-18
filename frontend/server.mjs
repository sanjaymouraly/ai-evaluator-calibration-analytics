/**
 * Tiny static file server + /api reverse proxy for the container build.
 *
 * The browser only ever talks to this origin; API calls are forwarded to
 * the backend service. This mirrors the Vite dev-server proxy so behaviour
 * is identical in development and in Docker.
 */
import http from 'node:http'
import { readFile, stat } from 'node:fs/promises'
import { extname, join, normalize } from 'node:path'

const PORT = Number(process.env.PORT ?? 5173)
const DIST = join(process.cwd(), 'dist')
const API_PROXY = process.env.API_PROXY ?? 'http://backend:8000'

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.ico': 'image/x-icon',
  '.json': 'application/json; charset=utf-8',
  '.map': 'application/json; charset=utf-8',
  '.woff2': 'font/woff2',
}

async function proxyApi(req, res, target) {
  const url = new URL(req.url, API_PROXY)
  const headers = { ...req.headers, host: url.host }
  delete headers.connection
  const upstream = await fetch(url, {
    method: req.method,
    headers,
    body: ['GET', 'HEAD'].includes(req.method) ? undefined : req,
    duplex: 'half',
  })
  res.writeHead(upstream.status, Object.fromEntries(upstream.headers.entries()))
  if (upstream.body) {
    for await (const chunk of upstream.body) res.write(chunk)
  }
  res.end()
}

const server = http.createServer(async (req, res) => {
  try {
    if (req.url.startsWith('/api/')) {
      await proxyApi(req, res, API_PROXY)
      return
    }
    // Static file with SPA fallback
    let rel = normalize(decodeURIComponent(new URL(req.url, 'http://x').pathname)).replace(/^(\.\.[/\\])+/, '')
    if (rel === '/' || rel === '\\') rel = '/index.html'
    let file = join(DIST, rel)
    try {
      const st = await stat(file)
      if (st.isDirectory()) file = join(file, 'index.html')
    } catch {
      file = join(DIST, 'index.html') // SPA fallback for client-side routes
    }
    const body = await readFile(file)
    res.writeHead(200, {
      'content-type': MIME[extname(file)] ?? 'application/octet-stream',
      'cache-control': file.endsWith('index.html') ? 'no-cache' : 'public, max-age=31536000, immutable',
    })
    res.end(body)
  } catch (err) {
    res.writeHead(500, { 'content-type': 'text/plain' })
    res.end('Internal server error')
    console.error(err)
  }
})

server.listen(PORT, '0.0.0.0', () => {
  console.log(`frontend serving ${DIST} on :${PORT}, proxying /api -> ${API_PROXY}`)
})
