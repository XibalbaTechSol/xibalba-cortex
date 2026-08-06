#!/usr/bin/env node

/**
 * User-local plugin to route Claude Code's pre_tool_call into graph-memory.
 * Configure this in ~/.claude.json or load it via Claude Code's extension mechanism.
 */

const http = require('http');

async function onPreToolCall(event) {
  const payload = JSON.stringify({
    jsonrpc: "2.0",
    id: Date.now(),
    method: "pre_tool_call",
    params: {
      session_id: event.session_id || process.env.CLAUDE_SESSION_ID,
      tool_name: event.tool_name,
      tool_input_hash: event.tool_input_hash,
      intent_rationale: event.intent_rationale,
      traceparent: event.traceparent,
      agent_id: event.agent_id,
    }
  });

  const options = {
    hostname: '127.0.0.1',
    port: 8420,
    path: '/api/mcp', // or whichever endpoint handles it
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Content-Length': Buffer.byteLength(payload)
    }
  };

  return new Promise((resolve, reject) => {
    const req = http.request(options, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        try {
          resolve(JSON.parse(data));
        } catch (e) {
          resolve(data);
        }
      });
    });

    req.on('error', (e) => reject(e));
    req.write(payload);
    req.end();
  });
}

module.exports = {
  hooks: {
    pre_tool_call: onPreToolCall
  }
};
