/**
 * Parse SSE events from a ReadableStream.
 * Yields parsed JSON objects from `data:` lines.
 */
export async function* parseSSEStream(response) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // Split on double newlines (SSE event boundary)
      const parts = buffer.split('\n\n');
      // Keep the last (possibly incomplete) part in the buffer
      buffer = parts.pop() || '';

      for (const part of parts) {
        const trimmed = part.trim();
        if (!trimmed) continue;

        for (const line of trimmed.split('\n')) {
          if (line.startsWith('data: ')) {
            const data = line.slice(6);
            try {
              yield JSON.parse(data);
            } catch {
              // Non-JSON data line, skip
            }
          }
        }
      }
    }

    // Process any remaining buffer
    if (buffer.trim()) {
      for (const line of buffer.trim().split('\n')) {
        if (line.startsWith('data: ')) {
          try {
            yield JSON.parse(line.slice(6));
          } catch {
            // skip
          }
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}
