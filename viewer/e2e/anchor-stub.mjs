// A stand-in for the anchor service the fixture API is configured with (XIBALBA_ANCHOR_URL), so the
// "Anchor this root" action can be exercised end to end without any outside network. It records each
// POST it receives and reports them at GET /received; GET /healthz is for Playwright's readiness check.
//
//   node e2e/anchor-stub.mjs [port]      (default 8431)
import { createServer } from 'node:http'

const port = Number(process.argv[2] ?? 8431)
const received = []

createServer((req, res) => {
  const reply = (status, body) => { res.writeHead(status, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(body)) }
  if (req.method === 'GET' && req.url === '/healthz') return reply(200, { status: 'ok' })
  if (req.method === 'GET' && req.url === '/received') return reply(200, { received })
  if (req.method === 'POST') {
    const chunks = []
    req.on('data', (c) => chunks.push(c))
    req.on('end', () => {
      try { received.push(JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}')) } catch { received.push({ unparseable: true }) }
      reply(200, { ok: true })
    })
    return
  }
  reply(404, { error: 'not found' })
}).listen(port, '127.0.0.1', () => console.log(`anchor stub on :${port}`))
