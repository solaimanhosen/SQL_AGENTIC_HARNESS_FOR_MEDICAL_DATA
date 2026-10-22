import { Injectable, InjectionToken, inject, signal } from '@angular/core';

import { SseParser } from './sse';
import {
  AccountChanges,
  Answer,
  AuthConfig,
  AuthUser,
  ConversationChanges,
  ConversationDetail,
  ConversationSummary,
  Draft,
  Health,
  ModelCatalog,
  ModelChoice,
  MyUsage,
  SessionInfo,
  StreamEvent,
} from './types';

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
  'The service could not be reached. Check that it is running, then try again.';

@Injectable({ providedIn: 'root' })
export class AgentApi {
  private readonly fetch = inject(FETCH);
  private readonly base = inject(API_BASE);

  /**
   * Counts the times the service said the session is missing or has ended. The sign-in state
   * watches it, so any request that finds itself signed out sends the person to sign in.
   */
  readonly signedOut = signal(0);

  async authConfig(): Promise<AuthConfig> {
    const response = await this.request('/auth/config', { method: 'GET' });
    return (await response.json()) as AuthConfig;
  }

  /** The signed-in person. A missing session is an ApiError with status 401. */
  async me(): Promise<AuthUser> {
    const response = await this.request('/auth/me', { method: 'GET' }, { quiet: true });
    return (await response.json()) as AuthUser;
  }

  async login(email: string, password: string): Promise<AuthUser> {
    return this.postAuth('/auth/login', { email, password });
  }

  async register(email: string, password: string, name: string): Promise<AuthUser> {
    return this.postAuth('/auth/register', { email, password, name });
  }

  async logout(): Promise<void> {
    await this.request('/auth/logout', { method: 'POST' }, { quiet: true });
  }

  async updateAccount(changes: AccountChanges): Promise<AuthUser> {
    return this.json('/account', 'PATCH', changes);
  }

  /** `current` is needed when the account already has a password. */
  async changePassword(current: string | null, next: string): Promise<void> {
    await this.request('/account/password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ current, new: next }),
    });
  }

  async sessions(): Promise<SessionInfo[]> {
    const response = await this.request('/account/sessions', { method: 'GET' });
    return (await response.json()) as SessionInfo[];
  }

  async revokeSession(id: string): Promise<void> {
    await this.request(`/account/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' });
  }

  /** Sign out every other browser and device. Returns how many were signed out. */
  async revokeOtherSessions(): Promise<number> {
    const body = await this.json<{ revoked: number }>('/account/sessions/revoke-others', 'POST');
    return body.revoked;
  }

  async disconnectGoogle(): Promise<AuthUser> {
    return this.json('/account/google/disconnect', 'POST');
  }

  async myUsage(): Promise<MyUsage> {
    const response = await this.request('/account/usage', { method: 'GET' });
    return (await response.json()) as MyUsage;
  }

  /** Send JSON, or nothing, and read JSON back. Used by the admin client too. */
  async json<T>(path: string, method: string, body?: object): Promise<T> {
    const response = await this.request(path, {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
    return (await response.json()) as T;
  }

  private async postAuth(path: string, body: object): Promise<AuthUser> {
    // A refusal here is a wrong password or a taken email, not an ended session.
    const response = await this.request(
      path,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      },
      { quiet: true },
    );
    return (await response.json()) as AuthUser;
  }

  async health(): Promise<Health> {
    const response = await this.request('/health', { method: 'GET' });
    return (await response.json()) as Health;
  }

  /**
   * Stored conversations, most recently used first. With search text, only those whose title
   * or any question contains it.
   */
  async conversations(search?: string): Promise<ConversationSummary[]> {
    const query = search?.trim() ? `?q=${encodeURIComponent(search.trim())}` : '';
    const response = await this.request(`/conversations${query}`, { method: 'GET' });
    return (await response.json()) as ConversationSummary[];
  }

  /** The models a question may run on, and the default. */
  async models(): Promise<ModelCatalog> {
    const response = await this.request('/models', { method: 'GET' });
    return (await response.json()) as ModelCatalog;
  }

  /** One stored conversation with every answer in it. */
  async conversation(id: string): Promise<ConversationDetail> {
    const response = await this.request(`/conversations/${id}`, { method: 'GET' });
    return (await response.json()) as ConversationDetail;
  }

  /** Rename, pin or unpin. Fields left out are not changed. */
  async updateConversation(id: string, changes: ConversationChanges): Promise<ConversationSummary> {
    const response = await this.request(`/conversations/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(changes),
    });
    return (await response.json()) as ConversationSummary;
  }

  async deleteConversation(id: string): Promise<void> {
    await this.request(`/conversations/${id}`, { method: 'DELETE' });
  }

  /** One stored answer as a self-contained HTML report, made by the service. */
  async report(id: string, turn: number): Promise<string> {
    const response = await this.request(`/conversations/${id}/turns/${turn}/report`, {
      method: 'GET',
    });
    return response.text();
  }

  /**
   * Ask a question and yield each event as it arrives: the conversation first, then each
   * step, then the answer as a draft while it is written, then the complete answer. A failure, whether before or during the stream, throws ApiError.
   */
  async *askStream(
    question: string,
    conversationId: string | null,
    abort?: AbortSignal,
    choice?: ModelChoice | null,
  ): AsyncGenerator<StreamEvent> {
    const body = JSON.stringify({
      question,
      ...(conversationId ? { conversation_id: conversationId } : {}),
      ...(choice ? { model: choice.model, effort: choice.effort } : {}),
    });
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
            case 'answer_delta':
              yield { type: 'draft', draft: data as Draft };
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

  /**
   * Every request carries the header that tells the service it came from this application,
   * and the session cookie, which the browser adds itself. A 401 means the session is gone,
   * unless `quiet` says the caller handles it.
   */
  async request(
    path: string,
    init: RequestInit,
    { quiet = false }: { quiet?: boolean } = {},
  ): Promise<Response> {
    const headers = new Headers(init.headers);
    headers.set('X-Requested-With', 'sql-agent');
    let response: Response;
    try {
      response = await this.fetch(`${this.base}${path}`, {
        ...init,
        headers,
        credentials: 'same-origin',
      });
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') {
        throw error;
      }
      throw new ApiError(0, 'unreachable', UNREACHABLE);
    }
    if (!response.ok) {
      if (response.status === 401 && !quiet) {
        this.signedOut.update((count) => count + 1);
      }
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
