import { TestBed } from '@angular/core/testing';

import { AgentApi, ApiError } from '../api/agent-api';
import { ConversationDetail, ConversationSummary, StreamEvent } from '../api/types';
import { answerFixture, conversationFixture, summaryFixture } from '../testing/fixtures';
import { ChatStore, MAX_QUESTION_CHARS } from './chat-store';

type Script = (question: string, conversationId: string | null) => AsyncGenerator<StreamEvent>;

function setup(script: Script) {
  const calls: { question: string; conversationId: string | null }[] = [];
  const api = {
    askStream: (question: string, conversationId: string | null) => {
      calls.push({ question, conversationId });
      return script(question, conversationId);
    },
    conversations: vi.fn(async (): Promise<ConversationSummary[]> => [summaryFixture()]),
    conversation: vi.fn(async (_id: string): Promise<ConversationDetail> => conversationFixture()),
    renameConversation: vi.fn(async (id: string, title: string) => summaryFixture({ id, title })),
    deleteConversation: vi.fn(async (_id: string) => undefined),
  };
  TestBed.configureTestingModule({ providers: [{ provide: AgentApi, useValue: api }] });
  const store = TestBed.inject(ChatStore);
  store.wait = async () => undefined;
  return { store, calls, api };
}

const answered: Script = async function* (question, conversationId) {
  yield {
    type: 'conversation',
    conversationId: conversationId ?? 'c'.repeat(32),
    turn: conversationId ? 2 : 1,
  };
  yield { type: 'step', step: { kind: 'sql', detail: 'SELECT 1' } };
  yield { type: 'answer', answer: answerFixture({ question }) };
};

function failing(error: ApiError): Script {
  return async function* () {
    throw error;
  };
}

describe('ChatStore', () => {
  it('records the steps and the answer, then remembers the conversation', async () => {
    const { store, calls } = setup(answered);

    await store.ask('  How many have diabetes?  ');
    await store.ask('What about heart disease?');

    const [first, second] = store.exchanges();
    expect(first.question).toBe('How many have diabetes?');
    expect(first.status).toBe('answered');
    expect(first.steps).toEqual([{ kind: 'sql', detail: 'SELECT 1' }]);
    expect(first.answer?.headline).toBe('Eight patients have diabetes.');
    expect(calls.map((call) => call.conversationId)).toEqual([null, 'c'.repeat(32)]);
    expect(second.status).toBe('answered');
  });

  it('shows the answer as a draft while it is written, then replaces it', async () => {
    let release!: () => void;
    const { store } = setup(async function* (question) {
      yield { type: 'conversation', conversationId: 'c'.repeat(32), turn: 1 };
      yield { type: 'draft', draft: { headline: 'Eight pat', findings: [] } };
      yield { type: 'draft', draft: { headline: 'Eight patients.', findings: ['8 match'] } };
      await new Promise<void>((resolve) => (release = resolve));
      yield { type: 'answer', answer: answerFixture({ question }) };
    });

    const pending = store.ask('How many?');
    await vi.waitFor(() => expect(store.exchanges()[0].draft?.findings).toEqual(['8 match']));
    expect(store.exchanges()[0].status).toBe('working');
    release();
    await pending;
    expect(store.exchanges()[0].status).toBe('answered');
    expect(store.exchanges()[0].draft).toBeUndefined();
  });

  it('drops the draft when the question fails midway', async () => {
    const { store } = setup(async function* () {
      yield { type: 'draft', draft: { headline: 'Eight pat', findings: [] } };
      throw new ApiError(503, 'connection', 'Could not reach the Anthropic API.');
    });
    await store.ask('How many?');
    expect(store.exchanges()[0].status).toBe('failed');
    expect(store.exchanges()[0].draft).toBeUndefined();
  });

  it('starts over after a new conversation', async () => {
    const { store, calls } = setup(answered);
    await store.ask('first');
    store.newConversation();
    await store.ask('second');
    expect(store.exchanges().map((exchange) => exchange.question)).toEqual(['second']);
    expect(calls[1].conversationId).toBeNull();
  });

  it('ignores empty and oversized questions', async () => {
    const { store, calls } = setup(answered);
    await store.ask('   ');
    await store.ask('x'.repeat(MAX_QUESTION_CHARS + 1));
    expect(calls).toEqual([]);
    expect(store.exchanges()).toEqual([]);
  });

  it('asks for the token when the service refuses without it, then retries', async () => {
    let attempts = 0;
    const { store } = setup(async function* (question, conversationId) {
      attempts += 1;
      if (attempts === 1) {
        throw new ApiError(401, 'unauthorized', 'Send the service token.');
      }
      yield* answered(question, conversationId);
    });

    await store.ask('How many?');
    expect(store.needsToken()).toBe(true);
    expect(store.exchanges()[0].status).toBe('failed');

    await store.retry(store.lastFailed()!.id);
    expect(store.needsToken()).toBe(false);
    expect(store.exchanges()[0].status).toBe('answered');
  });

  it('forgets a conversation the service no longer knows', async () => {
    const { store } = setup(answered);
    await store.ask('first');
    TestBed.inject(AgentApi).askStream = failing(
      new ApiError(404, 'unknown_conversation', 'Expired.'),
    );
    await store.ask('follow-up');
    expect(store.conversationId()).toBeNull();
    expect(store.exchanges()[1].error?.message).toBe('Expired.');
  });

  it('is busy while a question is being answered', async () => {
    let release!: () => void;
    const { store, calls } = setup(async function* (question, conversationId) {
      await new Promise<void>((resolve) => (release = resolve));
      yield* answered(question, conversationId);
    });

    const pending = store.ask('slow');
    expect(store.busy()).toBe(true);
    await store.ask('impatient');
    expect(calls.length).toBe(1);
    release();
    await pending;
    expect(store.busy()).toBe(false);
  });

  it('lists stored conversations, and again after each answer', async () => {
    const { store, api } = setup(answered);
    await store.refreshConversations();
    expect(store.conversations().map((item) => item.title)).toEqual([
      'How many patients have diabetes?',
    ]);
    await store.ask('first');
    await vi.waitFor(() => expect(api.conversations).toHaveBeenCalledTimes(2));
  });

  it('opens a stored conversation and continues it', async () => {
    const { store, calls, api } = setup(answered);
    const id = 'd'.repeat(32);

    expect(await store.open(id)).toBe(true);

    expect(api.conversation).toHaveBeenCalledWith(id);
    const [shown] = store.exchanges();
    expect(shown.status).toBe('answered');
    expect(shown.question).toBe('How many patients have diabetes?');
    expect(shown.steps).toEqual([{ kind: 'sql', detail: 'SELECT 1' }]);
    expect(shown.answer?.queries[0].rows).toEqual([[8]]);

    await store.ask('And heart disease?');
    expect(calls).toEqual([{ question: 'And heart disease?', conversationId: id }]);
    expect(store.exchanges().length).toBe(2);
    expect(new Set(store.exchanges().map((exchange) => exchange.id)).size).toBe(2);
  });

  it('keeps the screen as it is when a conversation cannot be opened', async () => {
    const { store, api } = setup(answered);
    await store.refreshConversations();
    await store.ask('first');
    api.conversation.mockRejectedValue(new ApiError(404, 'unknown_conversation', 'Deleted.'));

    expect(await store.open('c'.repeat(32))).toBe(false);

    expect(store.exchanges().length).toBe(1);
    expect(store.conversations()).toEqual([]);
  });

  it('renames a conversation in the list', async () => {
    const { store, api } = setup(answered);
    await store.refreshConversations();
    await store.rename('c'.repeat(32), 'Diabetes counts');
    expect(api.renameConversation).toHaveBeenCalledWith('c'.repeat(32), 'Diabetes counts');
    expect(store.conversations()[0].title).toBe('Diabetes counts');
  });

  it('deletes a conversation, and clears the screen when it is the one shown', async () => {
    const { store, api } = setup(answered);
    await store.refreshConversations();
    await store.open('c'.repeat(32));

    await store.remove('c'.repeat(32));

    expect(api.deleteConversation).toHaveBeenCalledWith('c'.repeat(32));
    expect(store.conversations()).toEqual([]);
    expect(store.exchanges()).toEqual([]);
    expect(store.conversationId()).toBeNull();
  });

  it('leaves the screen alone when another conversation is deleted', async () => {
    const { store } = setup(answered);
    await store.open('c'.repeat(32));
    await store.remove('d'.repeat(32));
    expect(store.exchanges().length).toBe(1);
    expect(store.conversationId()).toBe('c'.repeat(32));
  });

  it('fetches the answer from the service when only the stream was lost', async () => {
    const { store, api } = setup(async function* () {
      yield { type: 'conversation', conversationId: 'c'.repeat(32), turn: 1 };
      yield { type: 'draft', draft: { headline: 'Eight pat', findings: [] } };
      throw new ApiError(502, 'stream_ended', 'The service stopped before sending an answer.');
    });
    api.conversation
      .mockResolvedValueOnce(conversationFixture({ busy: true, history: [] }))
      .mockResolvedValueOnce(conversationFixture());

    await store.ask('How many?');

    expect(api.conversation).toHaveBeenCalledTimes(2);
    expect(store.exchanges()[0].status).toBe('answered');
    expect(store.exchanges()[0].answer?.headline).toBe('Eight patients have diabetes.');
  });

  it('reports the lost stream when the run did not finish on the service either', async () => {
    const { store, api } = setup(async function* () {
      yield { type: 'conversation', conversationId: 'c'.repeat(32), turn: 1 };
      throw new ApiError(502, 'stream_ended', 'The service stopped before sending an answer.');
    });
    api.conversation.mockResolvedValue(conversationFixture({ busy: false, history: [] }));

    await store.ask('How many?');

    expect(store.exchanges()[0].status).toBe('failed');
    expect(store.exchanges()[0].error?.kind).toBe('stream_ended');
  });
});
