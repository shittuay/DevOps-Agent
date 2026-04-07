#!/usr/bin/env node
'use strict';

const MCP_URL = process.env.DEVOPSAGENT_MCP_URL || 'https://devopsagent.io/mcp/';
const API_KEY  = process.env.DEVOPSAGENT_API_KEY  || '';

if (!API_KEY) {
  process.stderr.write(
    '[devops-agent] ERROR: DEVOPSAGENT_API_KEY is not set.\n' +
    '[devops-agent] Get your key at https://devopsagent.io/api-gateway/keys\n' +
    '[devops-agent] Add to Claude Desktop config: "env": { "DEVOPSAGENT_API_KEY": "doa_live_..." }\n'
  );
  process.exit(1);
}

let sessionId = null;

async function sendToRemote(message) {
  const headers = {
    'Content-Type':  'application/json',
    'Accept':        'application/json',
    'Authorization': `Bearer ${API_KEY}`,
  };
  if (sessionId) headers['Mcp-Session-Id'] = sessionId;

  const res = await fetch(MCP_URL, {
    method: 'POST',
    headers,
    body: JSON.stringify(message),
  });

  const newSid = res.headers.get('Mcp-Session-Id');
  if (newSid && !sessionId) sessionId = newSid;

  if (res.status === 202) return null;

  const text = await res.text();
  if (!text.trim()) return null;

  try {
    return JSON.parse(text);
  } catch {
    process.stderr.write(`[devops-agent] Non-JSON (${res.status}): ${text.slice(0, 200)}\n`);
    return null;
  }
}

let buffer = '';
process.stdin.setEncoding('utf8');

process.stdin.on('data', async (chunk) => {
  buffer += chunk;
  const lines = buffer.split('\n');
  buffer = lines.pop();

  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) continue;

    let message;
    try {
      message = JSON.parse(trimmed);
    } catch {
      process.stderr.write(`[devops-agent] JSON parse error: ${trimmed.slice(0, 100)}\n`);
      continue;
    }

    try {
      const response = await sendToRemote(message);
      if (response !== null) process.stdout.write(JSON.stringify(response) + '\n');
    } catch (err) {
      process.stderr.write(`[devops-agent] HTTP error: ${err.message}\n`);
      if (message.id !== undefined && message.id !== null) {
        process.stdout.write(JSON.stringify({
          jsonrpc: '2.0', id: message.id,
          error: { code: -32603, message: `Bridge error: ${err.message}` },
        }) + '\n');
      }
    }
  }
});

process.stdin.on('end', () => process.exit(0));
process.on('SIGINT',  () => process.exit(0));
process.on('SIGTERM', () => process.exit(0));
