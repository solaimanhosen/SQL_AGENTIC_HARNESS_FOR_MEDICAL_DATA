import { Injectable, InjectionToken, inject, signal } from '@angular/core';

import { SseParser } from './sse';
import { Answer, Health, StreamEvent } from './types';

/** The fetch function the client uses, replaceable in tests. */
export const FETCH = new InjectionToken<typeof fetch>('fetch', {
  factory: () => globalThis.fetch.bind(globalThis),
});

/** Where the service lives. The dev server proxies /api to it, see proxy.conf.json. */
export const API_BASE = new InjectionToken<string>('api base', { factory: () => '/api' });

/** A failure the service explained, or one that stopped us reaching it at all. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly kind: string,
    message: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

export const UNREACHABLE =
  'The service could not be reached. Start it from the Backend folder with: .venv/bin/python -m sql_agent.serve';

@Injectable({ providedIn: 'root' })
export class AgentApi {
  private readonly fetch = inject(FETCH);
  private readonly base = inject(API_BASE);

  /**
   * The shared access token, when the service requires one. It is held in memory only, so it
   * is gone when the page reloads and is never written to browser storage.
   */
  readonly token = signal<string | null>(null);

  async health(): Promise<Health> {
    const response = await this.request('/health', { method: 'GET' });
    return (await response.json()) as Health;
  }

  /**
   * Ask a question and yield each event as it arrives: the conversation first, then each
   * step, then the answer. A failure, whether before or during the stream, throws ApiError.
   */
  async *askStream(
    question: string,
    conversationId: string | null,
    abort?: AbortSignal,
  ): AsyncGenerator<StreamEvent> {
    const body = JSON.stringify(
      conversationId ? { question, conversation_id: conversationId } : { question },
    );
    const response = await this.request('/ask/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body,
      signal: abort,
    });
    if (!response.body) {
      throw new ApiError(response.status, 'no_stream', 'The service returned no stream.');
    }

    const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
    const parser = new SseParser();
    try {
      while (true) {
        const { value, done } = await reader.read();
        if (done) {
          break;
        }
        for (const message of parser.push(value)) {
          const data = JSON.parse(message.data);
          switch (message.event) {
            case 'conversation':
              yield { type: 'conversation', conversationId: data.conversation_id, turn: data.turn };
              break;
            case 'step':
              yield { type: 'step', step: data };
              break;
            case 'answer':
              yield { type: 'answer', answer: data as Answer };
              return;
            case 'error':
              throw new ApiError(
                data.status ?? 500,
                data.error ?? 'error',
                data.message ?? 'The question failed.',
              );
          }
        }
      }
    } finally {
      reader.releaseLock();
    }
    throw new ApiError(502, 'stream_ended', 'The service stopped before sending an answer.');
  }

  private async request(path: string, init: RequestInit): Promise<Response> {
    const headers = new Headers(init.headers);
    const token = this.token();
    if (token) {
      headers.set('Authorization', `Bearer ${token}`);
    }
    let response: Response;
    try {
      response = await this.fetch(`${this.base}${path}`, { ...init, headers });
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') {
        throw error;
      }
      throw new ApiError(0, 'unreachable', UNREACHABLE);
    }
    if (!response.ok) {
      throw await errorFrom(response);
    }
    return response;
  }
}

async function errorFrom(response: Response): Promise<ApiError> {
  try {
    const body = await response.json();
    if (body && typeof body.message === 'string') {
      return new ApiError(response.status, body.error ?? 'error', body.message);
    }
  } catch {
    // Not our JSON error shape, for example a proxy's own error page.
  }
  if (response.status === 502 || response.status === 504) {
    return new ApiError(0, 'unreachable', UNREACHABLE);
  }
  return new ApiError(
    response.status,
    'error',
    `The service answered with status ${response.status}.`,
  );
}
