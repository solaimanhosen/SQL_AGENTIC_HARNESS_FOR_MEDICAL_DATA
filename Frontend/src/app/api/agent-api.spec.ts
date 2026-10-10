import { TestBed } from '@angular/core/testing';

import { AgentApi, ApiError, FETCH, UNREACHABLE } from './agent-api';
import { StreamEvent } from './types';
import { answerFixture } from '../testing/fixtures';

function streamResponse(chunks: string[], status = 200): Response {
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      const encoder = new TextEncoder();
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk));
      }
      controller.close();
    },
  });
  return new Response(body, { status, headers: { 'Content-Type': 'text/event-stream' } });
}

function jsonResponse(body: unknown, status: number): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function setup(fetchImpl: (url: string, init: RequestInit) => Promise<Response>) {
  const fetchSpy = vi.fn(fetchImpl);
  TestBed.configureTestingModule({ providers: [{ provide: FETCH, useValue: fetchSpy }] });
  return { api: TestBed.inject(AgentApi), fetchSpy };
}

async function collect(stream: AsyncGenerator<StreamEvent>): Promise<StreamEvent[]> {
  const events: StreamEvent[] = [];
  for await (const event of stream) {
    events.push(event);
  }
  return events;
}

const answer = answerFixture();
const sse = (event: string, data: unknown) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;

describe('AgentApi', () => {
  it('streams the conversation, each step and the answer, split across chunks', async () => {
    const text =
      sse('conversation', { conversation_id: 'c'.repeat(32), turn: 1 }) +
      sse('step', { kind: 'sql', detail: 'SELECT 1' }) +
      sse('answer', answer);
    const { api, fetchSpy } = setup(async () =>
      streamResponse([text.slice(0, 30), text.slice(30, 95), text.slice(95)]),
    );

    const events = await collect(api.askStream('How many?', null));

    expect(events).toEqual([
      { type: 'conversation', conversationId: 'c'.repeat(32), turn: 1 },
      { type: 'step', step: { kind: 'sql', detail: 'SELECT 1' } },
      { type: 'answer', answer },
    ]);
    const [url, init] = fetchSpy.mock.calls[0];
    expect(url).toBe('/api/ask/stream');
    expect(JSON.parse(init.body as string)).toEqual({ question: 'How many?' });
  });

  it('sends the conversation id with a follow-up, and the token once one is set', async () => {
    const { api, fetchSpy } = setup(async () => streamResponse([sse('answer', answer)]));
    api.token.set('secret-token');

    await collect(api.askStream('And heart disease?', 'a'.repeat(32)));

    const init = fetchSpy.mock.calls[0][1];
    expect(JSON.parse(init.body as string)).toEqual({
      question: 'And heart disease?',
      conversation_id: 'a'.repeat(32),
    });
    expect(new Headers(init.headers).get('Authorization')).toBe('Bearer secret-token');
  });

  it('sends no Authorization header without a token', async () => {
    const { api, fetchSpy } = setup(async () => streamResponse([sse('answer', answer)]));
    await collect(api.askStream('q', null));
    expect(new Headers(fetchSpy.mock.calls[0][1].headers).has('Authorization')).toBe(false);
  });

  it('turns an error event in the stream into an ApiError', async () => {
    const { api } = setup(async () =>
      streamResponse([
        sse('error', {
          error: 'connection',
          message: 'Could not reach the Anthropic API.',
          status: 503,
        }),
      ]),
    );
    await expect(collect(api.askStream('q', null))).rejects.toEqual(
      new ApiError(503, 'connection', 'Could not reach the Anthropic API.'),
    );
  });

  it('reads the service error shape from a refused request', async () => {
    const { api } = setup(async () =>
      jsonResponse({ error: 'daily_budget', message: 'Budget used.' }, 429),
    );
    const failure = await collect(api.askStream('q', null)).catch((error) => error);
    expect(failure).toBeInstanceOf(ApiError);
    expect([failure.status, failure.kind, failure.message]).toEqual([
      429,
      'daily_budget',
      'Budget used.',
    ]);
  });

  it('says the service is unreachable when the network or the dev proxy fails', async () => {
    const offline = setup(async () => {
      throw new TypeError('Failed to fetch');
    });
    await expect(offline.api.health()).rejects.toMatchObject({
      kind: 'unreachable',
      message: UNREACHABLE,
    });

    TestBed.resetTestingModule();
    const proxyDown = setup(async () => new Response('Bad gateway', { status: 502 }));
    await expect(proxyDown.api.health()).rejects.toMatchObject({ kind: 'unreachable' });
  });

  it('reports a stream that ends without an answer', async () => {
    const { api } = setup(async () =>
      streamResponse([sse('step', { kind: 'sql', detail: 'SELECT 1' })]),
    );
    await expect(collect(api.askStream('q', null))).rejects.toMatchObject({ kind: 'stream_ended' });
  });
});
