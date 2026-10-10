import { Injectable, computed, inject, signal } from '@angular/core';

import { AgentApi, ApiError } from '../api/agent-api';
import { Answer, Step } from '../api/types';

export const MAX_QUESTION_CHARS = 2000;

/** One question and what became of it. */
export interface Exchange {
  id: number;
  question: string;
  status: 'working' | 'answered' | 'failed';
  steps: Step[];
  answer?: Answer;
  error?: ApiError;
}

/**
 * The conversation on screen. Each question after the first carries the conversation id, so
 * the service can read it as a follow-up.
 */
@Injectable({ providedIn: 'root' })
export class ChatStore {
  private readonly api = inject(AgentApi);
  private nextId = 1;

  readonly exchanges = signal<Exchange[]>([]);
  readonly conversationId = signal<string | null>(null);
  readonly busy = computed(() =>
    this.exchanges().some((exchange) => exchange.status === 'working'),
  );
  /** True after the service refused a question for want of the access token. */
  readonly needsToken = signal(false);

  async ask(question: string): Promise<void> {
    question = question.trim();
    if (!question || question.length > MAX_QUESTION_CHARS || this.busy()) {
      return;
    }
    const id = this.nextId++;
    this.exchanges.update((list) => [...list, { id, question, status: 'working', steps: [] }]);
    await this.run(id, question);
  }

  /** Ask a failed question again, for example after the access token was entered. */
  async retry(id: number): Promise<void> {
    const exchange = this.exchanges().find((item) => item.id === id);
    if (!exchange || exchange.status !== 'failed' || this.busy()) {
      return;
    }
    this.patch(id, { status: 'working', steps: [], error: undefined });
    await this.run(id, exchange.question);
  }

  /** Forget the conversation, so the next question starts fresh. */
  newConversation(): void {
    if (this.busy()) {
      return;
    }
    this.exchanges.set([]);
    this.conversationId.set(null);
  }

  lastFailed(): Exchange | undefined {
    return [...this.exchanges()].reverse().find((exchange) => exchange.status === 'failed');
  }

  private async run(id: number, question: string): Promise<void> {
    try {
      for await (const event of this.api.askStream(question, this.conversationId())) {
        if (event.type === 'conversation') {
          this.conversationId.set(event.conversationId);
        } else if (event.type === 'step') {
          this.patch(id, (exchange) => ({ steps: [...exchange.steps, event.step] }));
        } else {
          this.patch(id, { status: 'answered', answer: event.answer });
        }
      }
      this.needsToken.set(false);
    } catch (error) {
      const failure =
        error instanceof ApiError
          ? error
          : new ApiError(0, 'error', 'Something went wrong in the page.');
      if (failure.kind === 'unauthorized') {
        this.needsToken.set(true);
      }
      if (failure.kind === 'unknown_conversation') {
        // The service restarted or forgot the conversation. The next question starts anew.
        this.conversationId.set(null);
      }
      this.patch(id, { status: 'failed', error: failure });
    }
  }

  private patch(
    id: number,
    change: Partial<Exchange> | ((exchange: Exchange) => Partial<Exchange>),
  ): void {
    this.exchanges.update((list) =>
      list.map((exchange) =>
        exchange.id === id
          ? { ...exchange, ...(typeof change === 'function' ? change(exchange) : change) }
          : exchange,
      ),
    );
  }
}
