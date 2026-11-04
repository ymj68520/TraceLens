#!/usr/bin/env node
/**
 * Serve the built frontend and proxy API prefixes to the live services.
 *
 * Vite's dev proxy rewrites `/tasks` (a client route) as well, which breaks
 * deep links. This server keeps the SPA fallback for navigation requests and
 * forwards only the API prefixes, mirroring the production same-origin layout:
 *   /python/*  -> Python service
 *   /api/*     -> Python service (except the C++ task routes below)
 *   /tasks, /api/tasks* -> C++ service
 *
 * Usage: node web/scripts/e2e-static-server.mjs [--port 4173]
 */

import http from 'node:http'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const DIST = process.env.E2E_DIST || path.resolve(here, '..', 'dist')
const PYTHON = process.env.E2E_PYTHON || 'http://127.0.0.1:8090'
const CPP = process.env.E2E_CPP || 'http://127.0.0.1:8666'

const args = new Map()
for (let i = 2; i < process.argv.length; i += 1) {
  if (process.argv[i].startsWith('--')) args.set(process.argv[i].slice(2), process.argv[i + 1])
}
const PORT = Number(args.get('port') || process.env.E2E_PORT || 4173)

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.woff2': 'font/woff2',
  '.map': 'application/json; charset=utf-8',
  '.ico': 'image/x-icon',
}

/** Paths that belong to the C++ task API rather than the SPA router. */
function isCppApi(pathname) {
  return pathname === '/api/tasks' || pathname.startsWith('/api/tasks/')
    || pathname.startsWith('/api/forensics/') || pathname.startsWith('/api/reports')
      && false
}

function targetFor(pathname) {
  if (pathname.startsWith('/python/')) return { base: PYTHON, strip: '/python' }
  if (isCppApi(pathname)) return { base: CPP, strip: '' }
  if (pathname.startsWith('/api/')) return { base: PYTHON, strip: '' }
  return null
}

async function proxy(request, response, pathname, target) {
  const suffix = pathname.slice(target.strip.length) || '/'
  const url = new URL(target.base)
  const headers = { ...request.headers, host: url.host }
  // The production entry injects this header at the trusted proxy. The test
  // server stands in for that entry, so it supplies the token the Python
  // service requires for row-content APIs.
  if (process.env.E2E_FIELD_TOKEN) {
    headers['x-tracelens-field-token'] = process.env.E2E_FIELD_TOKEN
  }
  const options = {
    hostname: url.hostname,
    port: url.port,
    path: suffix + (request.url.includes('?') ? request.url.slice(request.url.indexOf('?')) : ''),
    method: request.method,
    headers,
  }
  const upstream = http.request(options, (upstreamResponse) => {
    response.writeHead(upstreamResponse.statusCode || 502, upstreamResponse.headers)
    upstreamResponse.pipe(response)
  })
  upstream.on('error', (error) => {
    response.writeHead(502, { 'content-type': 'application/json' })
    response.end(JSON.stringify({ detail: `upstream unavailable: ${error.message}` }))
  })
  request.pipe(upstream)
}

function serveStatic(request, response, pathname) {
  const relative = pathname === '/' ? 'index.html' : pathname.replace(/^\/+/, '')
  const candidate = path.resolve(DIST, relative)
  if (!candidate.startsWith(DIST)) {
    response.writeHead(403).end('forbidden')
    return
  }
  // Missing extension or unknown path: SPA fallback.
  const useIndex = !fs.existsSync(candidate) || fs.statSync(candidate).isDirectory()
  const file = useIndex ? path.join(DIST, 'index.html') : candidate
  if (!fs.existsSync(file)) {
    response.writeHead(404).end('not found')
    return
  }
  response.writeHead(200, { 'content-type': MIME[path.extname(file)] || 'application/octet-stream' })
  fs.createReadStream(file).pipe(response)
}

const server = http.createServer((request, response) => {
  const pathname = new URL(request.url, `http://127.0.0.1:${PORT}`).pathname
  const target = targetFor(pathname)
  if (target) {
    proxy(request, response, pathname, target)
    return
  }
  serveStatic(request, response, pathname)
})

server.listen(PORT, '127.0.0.1', () => {
  console.log(`serving ${DIST} on http://127.0.0.1:${PORT} (python=${PYTHON} cpp=${CPP})`)
})
