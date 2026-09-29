/** One server-sent event: its name and its data, with multi-line data rejoined. */
export interface SseMessage {
  event: string;
  data: string;
}

/**
 * Turns a stream of text chunks into server-sent events.
 *
 * The browser's EventSource cannot send a POST or an Authorization header, so the stream is
 * read with fetch and parsed here. Chunks can split an event anywhere, even inside a line, so
 * text is buffered until a blank line ends the event.
 */
export class SseParser {
  private buffer = '';

  push(chunk: string): SseMessage[] {
    this.buffer += chunk.replace(/\r\n?/g, '\n');
    const blocks = this.buffer.split('\n\n');
    this.buffer = blocks.pop() ?? '';
    return blocks.map(parseBlock).filter((message): message is SseMessage => message !== null);
  }
}

function parseBlock(block: string): SseMessage | null {
  let event = 'message';
  const data: string[] = [];
  for (const line of block.split('\n')) {
    if (line === '' || line.startsWith(':')) {
      continue;
    }
    const colon = line.indexOf(':');
    const field = colon === -1 ? line : line.slice(0, colon);
    const value = colon === -1 ? '' : line.slice(colon + 1).replace(/^ /, '');
    if (field === 'event') {
      event = value;
    } else if (field === 'data') {
      data.push(value);
    }
  }
  return data.length ? { event, data: data.join('\n') } : null;
}
