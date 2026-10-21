import { Injectable, computed, inject, signal } from '@angular/core';

import { AgentApi, ApiError } from '../api/agent-api';
import {
  Answer,
  ConversationChanges,
  ConversationSummary,
  Draft,
  ModelCatalog,
  ModelChoice,
  Step,
} from '../api/types';

export const MAX_QUESTION_CHARS = 2000;

/** How often, and how many times, a run whose stream was lost is looked for on the service. */
export const RECOVER_EVERY_MS = 2000;
export const RECOVER_ATTEMPTS = 60;

/** One question and what became of it. */
export interface Exchange {
  id: number;
  question: string;
  status: 'working' | 'answered' | 'failed';
  steps: Step[];
  /** The answer so far, while it is still being written. Gone once the answer arrives. */
  draft?: Draft;
  answer?: Answer;
  error?: ApiError;
}

/**
 * The conversation on screen and the list of stored ones. Each question after the first
 * carries the conversation id, so the service can read it as a follow-up. The service keeps
 * every conversation, so one can be opened again and continued.
 */
@Injectable({ providedIn: 'root' })
export class ChatStore {
  private readonly api = inject(AgentApi);
  private nextId = 1;

  readonly exchanges = signal<Exchange[]>([]);
  readonly conversationId = signal<string | null>(null);
  /** Stored conversations, most recently used first. */
  readonly conversations = signal<ConversationSummary[]>([]);
  /** Conversations matching the search text, or null when nothing is being searched. */
  readonly searchResults = signal<ConversationSummary[] | null>(null);
  /** Counts searches, so an answer to an older one never replaces a newer one's. */
  private searchCount = 0;
  /** Replaceable in tests, so recovering a lost stream does not wait on a real clock. */
  wait = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));
  readonly busy = computed(() =>
    this.exchanges().some((exchange) => exchange.status === 'working'),
  );
  /** True after the service refused a question for want of the access token. */
  readonly needsToken = signal(false);
  /** The models on offer. Null until the service has said, when its default applies. */
  readonly catalog = signal<ModelCatalog | null>(null);
  /** The model and effort the next question runs on. It may change between questions. */
  readonly choice = signal<ModelChoice | null>(null);

  /** Fetch the models on offer, and start with the default if nothing is chosen yet. */
  async loadModels(): Promise<void> {
    try {
      const catalog = await this.api.models();
      this.catalog.set(catalog);
      if (!this.choice()) {
        this.choice.set({ model: catalog.default_model, effort: catalog.default_effort });
      }
    } catch (error) {
      if (error instanceof ApiError && error.kind === 'unauthorized') {
        this.needsToken.set(true);
      }
    }
  }

  /** Change the model or effort. Only a combination the service offers is accepted. */
  choose(choice: ModelChoice): void {
    if (offers(this.catalog(), choice)) {
      this.choice.set(choice);
    }
  }

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
    this.patch(id, { status: 'working', steps: [], draft: undefined, error: undefined });
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

  /** Fetch the list of stored conversations. A failure leaves the list as it was. */
  async refreshConversations(): Promise<void> {
    try {
      this.conversations.set(await this.api.conversations());
    } catch (error) {
      if (error instanceof ApiError && error.kind === 'unauthorized') {
        this.needsToken.set(true);
      }
    }
  }

  /** Show a stored conversation, so it can be read and continued. False if it could not be. */
  async open(id: string): Promise<boolean> {
    if (this.busy()) {
      return false;
    }
    try {
      const stored = await this.api.conversation(id);
      this.exchanges.set(
        stored.history.map((turn) => ({
          id: this.nextId++,
          question: turn.question,
          status: 'answered',
          steps: turn.steps,
          answer: turn.answer,
        })),
      );
      this.conversationId.set(id);
      // Continue on the model and effort its latest answer used, if they are still offered.
      if (stored.last_model && stored.last_effort) {
        this.choose({ model: stored.last_model, effort: stored.last_effort });
      }
      return true;
    } catch (error) {
      if (error instanceof ApiError && error.kind === 'unauthorized') {
        this.needsToken.set(true);
      } else if (error instanceof ApiError && error.kind === 'unknown_conversation') {
        this.conversations.update((list) => list.filter((item) => item.id !== id));
      }
      return false;
    }
  }

  async rename(id: string, title: string): Promise<void> {
    await this.update(id, { title });
  }

  /** Pin a conversation to the top of the list, or unpin it. */
  async pin(id: string, pinned: boolean): Promise<void> {
    await this.update(id, { pinned });
  }

  private async update(id: string, changes: ConversationChanges): Promise<void> {
    try {
      this.replace(await this.api.updateConversation(id, changes));
    } catch {
      await this.refreshConversations();
    }
  }

  /** Put a changed conversation into the list, and into the search results if it is there. */
  private replace(summary: ConversationSummary): void {
    const swap = (list: ConversationSummary[]) =>
      list.map((item) => (item.id === summary.id ? summary : item));
    this.conversations.update(swap);
    this.searchResults.update((found) => found && swap(found));
  }

  /**
   * Search titles and questions on the service. Empty text ends the search. A failed search
   * shows no results rather than an error, since the full list is still there.
   */
  async search(text: string): Promise<void> {
    const count = ++this.searchCount;
    if (!text.trim()) {
      this.searchResults.set(null);
      return;
    }
    try {
      const found = await this.api.conversations(text);
      if (count === this.searchCount) {
        this.searchResults.set(found);
      }
    } catch (error) {
      if (count === this.searchCount) {
        this.searchResults.set([]);
      }
      if (error instanceof ApiError && error.kind === 'unauthorized') {
        this.needsToken.set(true);
      }
    }
  }

  /** Delete a stored conversation. If it is the one on screen, the screen starts fresh. */
  async remove(id: string): Promise<void> {
    if (this.busy() && id === this.conversationId()) {
      return;
    }
    try {
      await this.api.deleteConversation(id);
    } catch (error) {
      if (!(error instanceof ApiError) || error.kind !== 'unknown_conversation') {
        await this.refreshConversations();
        return;
      }
    }
    this.conversations.update((list) => list.filter((item) => item.id !== id));
    this.searchResults.update((found) => found && found.filter((item) => item.id !== id));
    if (id === this.conversationId()) {
      this.exchanges.set([]);
      this.conversationId.set(null);
    }
  }

  lastFailed(): Exchange | undefined {
    return [...this.exchanges()].reverse().find((exchange) => exchange.status === 'failed');
  }

  private async run(id: number, question: string): Promise<void> {
    let turn: number | null = null;
    try {
      const stream = this.api.askStream(question, this.conversationId(), undefined, this.choice());
      for await (const event of stream) {
        if (event.type === 'conversation') {
          this.conversationId.set(event.conversationId);
          turn = event.turn;
        } else if (event.type === 'step') {
          this.patch(id, (exchange) => ({ steps: [...exchange.steps, event.step] }));
        } else if (event.type === 'draft') {
          this.patch(id, { draft: event.draft });
        } else {
          this.patch(id, { status: 'answered', answer: event.answer, draft: undefined });
        }
      }
      this.needsToken.set(false);
      void this.refreshConversations();
    } catch (error) {
      const failure =
        error instanceof ApiError
          ? error
          : new ApiError(0, 'error', 'Something went wrong in the page.');
      if (failure.kind === 'stream_ended' && turn !== null) {
        // Only the connection was lost. The service finishes the run and stores it.
        const answer = await this.recover(this.conversationId()!, turn);
        if (answer) {
          this.patch(id, { status: 'answered', answer, draft: undefined });
          void this.refreshConversations();
          return;
        }
      }
      if (failure.kind === 'unauthorized') {
        this.needsToken.set(true);
      }
      if (failure.kind === 'unknown_conversation') {
        // The service restarted or forgot the conversation. The next question starts anew.
        this.conversationId.set(null);
      }
      this.patch(id, { status: 'failed', error: failure, draft: undefined });
    }
  }

  /** Wait for a run whose stream was lost to finish on the service, and fetch its answer. */
  private async recover(conversationId: string, turn: number): Promise<Answer | null> {
    try {
      for (let attempt = 0; attempt < RECOVER_ATTEMPTS; attempt++) {
        const stored = await this.api.conversation(conversationId);
        const found = stored.history.find((item) => item.turn === turn);
        if (found || !stored.busy) {
          return found?.answer ?? null;
        }
        await this.wait(RECOVER_EVERY_MS);
      }
    } catch {
      // The service cannot be reached either, so the failure is shown as it is.
    }
    return null;
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

/** Whether the catalog offers this model at this effort. */
function offers(catalog: ModelCatalog | null, choice: ModelChoice): boolean {
  const model = catalog?.models.find((item) => item.id === choice.model);
  return !!model && model.efforts.includes(choice.effort);
}
