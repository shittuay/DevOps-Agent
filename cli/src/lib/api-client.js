import { getApiKey, getServerUrl } from './config-manager.js';
import { parseSSEStream } from './sse-parser.js';

class APIError extends Error {
  constructor(message, status, body) {
    super(message);
    this.name = 'APIError';
    this.status = status;
    this.body = body;
  }
}

function getHeaders() {
  const key = getApiKey();
  if (!key) {
    throw new Error('Not logged in. Run `devopsagent login` first.');
  }
  return {
    'Authorization': `Bearer ${key}`,
    'Content-Type': 'application/json',
  };
}

function baseUrl() {
  return getServerUrl().replace(/\/+$/, '');
}

async function handleResponse(res) {
  if (!res.ok) {
    let body;
    try {
      body = await res.json();
    } catch {
      body = { error: res.statusText };
    }
    throw new APIError(
      body.message || body.error || `HTTP ${res.status}`,
      res.status,
      body
    );
  }
  return res.json();
}

export async function validateKey(apiKey, serverUrl) {
  const url = `${serverUrl.replace(/\/+$/, '')}/api/v1/auth/validate`;
  const res = await fetch(url, {
    headers: {
      'Authorization': `Bearer ${apiKey}`,
      'Content-Type': 'application/json',
    },
  });
  return handleResponse(res);
}

export async function getMe() {
  const res = await fetch(`${baseUrl()}/api/v1/auth/me`, {
    headers: getHeaders(),
  });
  return handleResponse(res);
}

export async function listConversations(limit = 20, offset = 0) {
  const res = await fetch(
    `${baseUrl()}/api/v1/conversations?limit=${limit}&offset=${offset}`,
    { headers: getHeaders() }
  );
  return handleResponse(res);
}

export async function createConversation(title) {
  const res = await fetch(`${baseUrl()}/api/v1/conversations`, {
    method: 'POST',
    headers: getHeaders(),
    body: JSON.stringify({ title: title || 'CLI Chat' }),
  });
  return handleResponse(res);
}

export async function* streamChat(message, conversationId) {
  const body = { message };
  if (conversationId) {
    body.conversation_id = conversationId;
  }

  const res = await fetch(`${baseUrl()}/api/v1/chat/stream`, {
    method: 'POST',
    headers: getHeaders(),
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    let errBody;
    try {
      errBody = await res.json();
    } catch {
      errBody = { error: res.statusText };
    }
    throw new APIError(
      errBody.message || errBody.error || `HTTP ${res.status}`,
      res.status,
      errBody
    );
  }

  yield* parseSSEStream(res);
}

export async function executeTool(toolName, params = {}) {
  const res = await fetch(`${baseUrl()}/api/v1/tools/execute`, {
    method: 'POST',
    headers: getHeaders(),
    body: JSON.stringify({ tool: toolName, params }),
  });
  return handleResponse(res);
}

export { APIError };
