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
      sse('answer_delta', { headline: 'Eight pat', findings: [] }) +
      sse('answer', answer);
    const { api, fetchSpy } = setup(async () =>
      streamResponse([text.slice(0, 30), text.slice(30, 95), text.slice(95)]),
    );

    const events = await collect(api.askStream('How many?', null));

    expect(events).toEqual([
      { type: 'conversation', conversationId: 'c'.repeat(32), turn: 1 },
      { type: 'step', step: { kind: 'sql', detail: 'SELECT 1' } },
      { type: 'draft', draft: { headline: 'Eight pat', findings: [] } },
      { type: 'answer', answer },
    ]);
    const [url, init] = fetchSpy.mock.calls[0];
    expect(url).toBe('/api/ask/stream');
    expect(JSON.parse(init.body as string)).toEqual({ question: 'How many?' });
  });

  it('sends the conversation id with a follow-up, with the application header', async () => {
    const { api, fetchSpy } = setup(async () => streamResponse([sse('answer', answer)]));

    await collect(api.askStream('And heart disease?', 'a'.repeat(32)));

    const init = fetchSpy.mock.calls[0][1];
    expect(JSON.parse(init.body as string)).toEqual({
      question: 'And heart disease?',
      conversation_id: 'a'.repeat(32),
    });
    expect(new Headers(init.headers).get('X-Requested-With')).toBe('sql-agent');
    expect(init.credentials).toBe('same-origin');
  });

  it('sends the chosen model and effort with the question', async () => {
    const { api, fetchSpy } = setup(async () => streamResponse([sse('answer', answer)]));
    await collect(
      api.askStream('q', null, undefined, { model: 'claude-haiku-5-5', effort: 'low' }),
    );
    expect(JSON.parse(fetchSpy.mock.calls[0][1].body as string)).toEqual({
      question: 'q',
      model: 'claude-haiku-5-5',
      effort: 'low',
    });
  });

  it('reads the models on offer', async () => {
    const catalog = { default_model: 'claude-opus-5', default_effort: 'high', models: [] };
    const { api, fetchSpy } = setup(async () => jsonResponse(catalog, 200));
    expect(await api.models()).toEqual(catalog);
    expect(fetchSpy.mock.calls[0][0]).toBe('/api/models');
  });

  it('never sends a bearer token: the session is a cookie the page cannot read', async () => {
    const { api, fetchSpy } = setup(async () => streamResponse([sse('answer', answer)]));
    await collect(api.askStream('q', null));
    expect(new Headers(fetchSpy.mock.calls[0][1].headers).has('Authorization')).toBe(false);
  });

  it('counts an ended session, but not a wrong password', async () => {
    const { api } = setup(async () =>
      jsonResponse({ error: 'unauthenticated', message: 'Sign in to continue.' }, 401),
    );
    await expect(api.conversations()).rejects.toMatchObject({ status: 401 });
    expect(api.signedOut()).toBe(1);
    await expect(api.login('ann@example.org', 'wrong')).rejects.toMatchObject({ status: 401 });
    await expect(api.me()).rejects.toMatchObject({ status: 401 });
    expect(api.signedOut()).toBe(1);
  });

  it('signs in, registers and signs out', async () => {
    const user = { id: 'u1', email: 'ann@example.org' };
    const { api, fetchSpy } = setup(async (url) =>
      url.endsWith('/logout') ? new Response(null, { status: 204 }) : jsonResponse(user, 200),
    );
    expect(await api.login('ann@example.org', 'pw')).toEqual(user);
    expect(await api.register('ann@example.org', 'pw', 'Ann')).toEqual(user);
    await api.logout();
    const calls = fetchSpy.mock.calls.map(([url, init]) => [init.method, url, init.body]);
    expect(calls).toEqual([
      ['POST', '/api/auth/login', JSON.stringify({ email: 'ann@example.org', password: 'pw' })],
      [
        'POST',
        '/api/auth/register',
        JSON.stringify({ email: 'ann@example.org', password: 'pw', name: 'Ann' }),
      ],
      ['POST', '/api/auth/logout', undefined],
    ]);
  });

  it('asks for links, resets and confirms, without treating a refusal as signing out', async () => {
    const { api, fetchSpy } = setup(async (url) =>
      url.endsWith('/forgot') || url.endsWith('/verify-email')
        ? jsonResponse({ accepted: true }, 202)
        : new Response(null, { status: 204 }),
    );
    await api.forgotPassword('ann@example.org');
    await api.resetPassword('a-token', 'a new password');
    await api.verifyEmail('a-token');
    await api.sendVerification();
    const calls = fetchSpy.mock.calls.map(([url, init]) => [init.method, url, init.body]);
    expect(calls).toEqual([
      ['POST', '/api/auth/forgot', JSON.stringify({ email: 'ann@example.org' })],
      ['POST', '/api/auth/reset', JSON.stringify({ token: 'a-token', password: 'a new password' })],
      ['POST', '/api/auth/verify', JSON.stringify({ token: 'a-token' })],
      ['POST', '/api/account/verify-email', undefined],
    ]);
    for (const [, init] of fetchSpy.mock.calls) {
      expect(new Headers(init.headers).get('X-Requested-With')).toBe('sql-agent');
    }

    TestBed.resetTestingModule();
    const refused = setup(async () =>
      jsonResponse({ error: 'invalid_link', message: 'This link has expired.' }, 401),
    );
    await expect(refused.api.resetPassword('old', 'a new password')).rejects.toMatchObject({
      message: 'This link has expired.',
    });
    expect(refused.api.signedOut()).toBe(0);
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

  it('lists, searches, opens, renames, pins and deletes conversations', async () => {
    const id = 'c'.repeat(32);
    const { api, fetchSpy } = setup(async (url, init) =>
      init.method === 'DELETE'
        ? new Response(null, { status: 204 })
        : jsonResponse(url.endsWith('/conversations') ? [{ id }] : { id, title: 'Renamed' }, 200),
    );
    expect(await api.conversations()).toEqual([{ id }]);
    expect(await api.conversation(id)).toEqual({ id, title: 'Renamed' });
    expect((await api.updateConversation(id, { title: 'Renamed' })).title).toBe('Renamed');
    await api.deleteConversation(id);
    await api.updateConversation(id, { pinned: true });
    await api.conversations('  heart & lung? ');

    const calls = fetchSpy.mock.calls.map(([url, init]) => [init.method, url]);
    expect(calls).toEqual([
      ['GET', '/api/conversations'],
      ['GET', `/api/conversations/${id}`],
      ['PATCH', `/api/conversations/${id}`],
      ['DELETE', `/api/conversations/${id}`],
      ['PATCH', `/api/conversations/${id}`],
      ['GET', '/api/conversations?q=heart%20%26%20lung%3F'],
    ]);
    expect(fetchSpy.mock.calls[2][1].body).toBe(JSON.stringify({ title: 'Renamed' }));
    expect(fetchSpy.mock.calls[4][1].body).toBe(JSON.stringify({ pinned: true }));
    for (const [, init] of fetchSpy.mock.calls) {
      expect(new Headers(init.headers).get('X-Requested-With')).toBe('sql-agent');
    }
  });

  it('reports a conversation the service no longer has', async () => {
    const { api } = setup(async () =>
      jsonResponse({ error: 'unknown_conversation', message: 'Deleted.' }, 404),
    );
    await expect(api.conversation('c'.repeat(32))).rejects.toMatchObject({
      status: 404,
      kind: 'unknown_conversation',
    });
  });

  it('fetches a report as text', async () => {
    const id = 'c'.repeat(32);
    const { api, fetchSpy } = setup(
      async () =>
        new Response('<!doctype html><title>r</title>', {
          status: 200,
          headers: { 'Content-Type': 'text/html; charset=utf-8' },
        }),
    );
    expect(await api.report(id, 2)).toBe('<!doctype html><title>r</title>');
    const [url, init] = fetchSpy.mock.calls[0];
    expect([init.method, url]).toEqual(['GET', `/api/conversations/${id}/turns/2/report`]);
  });

  it('reports why a report was refused', async () => {
    const { api } = setup(async () =>
      jsonResponse({ error: 'unknown_turn', message: 'No such question.' }, 404),
    );
    await expect(api.report('c'.repeat(32), 9)).rejects.toMatchObject({
      status: 404,
      kind: 'unknown_turn',
      message: 'No such question.',
    });
  });
});
