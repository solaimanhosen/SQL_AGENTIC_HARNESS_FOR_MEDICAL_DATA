import { TestBed } from '@angular/core/testing';

import { AgentApi, ApiError } from '../api/agent-api';
import { StreamEvent } from '../api/types';
import { answerFixture } from '../testing/fixtures';
import { ChatStore, MAX_QUESTION_CHARS } from './chat-store';

type Script = (question: string, conversationId: string | null) => AsyncGenerator<StreamEvent>;

function setup(script: Script) {
  const calls: { question: string; conversationId: string | null }[] = [];
  const api = {
    askStream: (question: string, conversationId: string | null) => {
      calls.push({ question, conversationId });
      return script(question, conversationId);
    },
  };
  TestBed.configureTestingModule({ providers: [{ provide: AgentApi, useValue: api }] });
  return { store: TestBed.inject(ChatStore), calls };
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
});
