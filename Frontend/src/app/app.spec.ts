import { TestBed } from '@angular/core/testing';

import { AgentApi, ApiError, UNREACHABLE } from './api/agent-api';
import { ConversationSummary, Health, StreamEvent } from './api/types';
import { App, EXAMPLE_QUESTIONS } from './app';
import { answerFixture, conversationFixture, summaryFixture } from './testing/fixtures';

const HEALTH: Health = {
  status: 'ok',
  database: true,
  tables: 18,
  model: 'claude-opus-5',
  as_of: '2026-08-16',
};

function fakeApi(
  stream: () => AsyncGenerator<StreamEvent>,
  health: () => Promise<Health> = async () => HEALTH,
) {
  return {
    token: { set: vi.fn() },
    health: vi.fn(health),
    askStream: vi.fn(stream),
    conversations: vi.fn(async (): Promise<ConversationSummary[]> => []),
    conversation: vi.fn(async (_id: string) => conversationFixture()),
    renameConversation: vi.fn(async (id: string, title: string) => summaryFixture({ id, title })),
    deleteConversation: vi.fn(async (_id: string) => undefined),
  };
}

async function render(api: ReturnType<typeof fakeApi>) {
  TestBed.configureTestingModule({
    imports: [App],
    providers: [{ provide: AgentApi, useValue: api }],
  });
  const fixture = TestBed.createComponent(App);
  await fixture.whenStable();
  return { fixture, element: fixture.nativeElement as HTMLElement };
}

async function* answers(overrides = {}): AsyncGenerator<StreamEvent> {
  yield { type: 'conversation', conversationId: 'c'.repeat(32), turn: 1 };
  yield { type: 'answer', answer: answerFixture(overrides) };
}

describe('App', () => {
  // A question puts its conversation in the address, which must not leak into the next test.
  afterEach(() => history.replaceState(null, '', location.pathname));

  it('shows the service status and the example questions', async () => {
    const { element } = await render(fakeApi(answers));
    expect(element.querySelector('.status')?.textContent).toContain(
      'claude-opus-5 · synthetic data as of 2026-08-16',
    );
    const examples = [...element.querySelectorAll('.example')].map((button) =>
      button.textContent?.trim(),
    );
    expect(examples).toEqual(EXAMPLE_QUESTIONS);
  });

  it('says how to start the service when it cannot be reached', async () => {
    const { element } = await render(
      fakeApi(answers, async () => {
        throw new ApiError(0, 'unreachable', UNREACHABLE);
      }),
    );
    expect(element.querySelector('.status')?.textContent).toContain('sql_agent.serve');
  });

  it('asks an example question and shows the answer with its citations', async () => {
    const api = fakeApi(answers);
    const { fixture, element } = await render(api);

    (element.querySelector('.example') as HTMLButtonElement).click();
    await fixture.whenStable();

    expect(api.askStream).toHaveBeenCalledWith(EXAMPLE_QUESTIONS[0], null);
    expect(element.querySelector('.question')?.textContent).toBe(EXAMPLE_QUESTIONS[0]);
    expect(element.querySelector('.headline')?.textContent).toBe('Eight patients have diabetes.');
    expect(element.querySelector('.findings li')?.textContent).toContain('Query 1');
    expect(element.querySelector('.caveats')?.textContent).toContain('Small cohort.');
    expect(element.querySelector('.meta')?.textContent).toContain('1 query');
  });

  it('renders text from the data as text, never as HTML', async () => {
    const injected = '<img src=x onerror="alert(1)"> <b>bold</b>';
    const { fixture, element } = await render(
      fakeApi(() =>
        answers({ headline: injected, findings: [{ statement: injected, query_numbers: [1] }] }),
      ),
    );
    (element.querySelector('.example') as HTMLButtonElement).click();
    await fixture.whenStable();

    expect(element.querySelector('.headline')?.textContent).toBe(injected);
    expect(element.querySelector('.exchange img')).toBeNull();
    expect(element.querySelector('.exchange b')).toBeNull();
  });

  it('shows the draft as plain text while the answer is written', async () => {
    const injected = '<img src=x onerror="alert(1)">Eight pat';
    let release!: () => void;
    const api = fakeApi(async function* () {
      yield { type: 'conversation', conversationId: 'c'.repeat(32), turn: 1 };
      yield { type: 'draft', draft: { headline: injected, findings: ['8 match'] } };
      await new Promise<void>((resolve) => (release = resolve));
      yield { type: 'answer', answer: answerFixture() };
    });
    const { fixture, element } = await render(api);

    (element.querySelector('.example') as HTMLButtonElement).click();
    await vi.waitFor(async () => {
      await fixture.whenStable();
      expect(element.querySelector('.draft-headline')?.textContent).toBe(injected);
    });
    expect(element.querySelector('.draft-findings li')?.textContent).toBe('8 match');
    expect(element.querySelector('.now')?.textContent).toContain('Writing the answer');
    expect(element.querySelector('.exchange img')).toBeNull();
    expect(element.querySelector('.headline')).toBeNull();

    release();
    await vi.waitFor(async () => {
      await fixture.whenStable();
      expect(element.querySelector('.headline')?.textContent).toBe('Eight patients have diabetes.');
    });
    expect(element.querySelector('.draft')).toBeNull();
  });

  it('asks for the access token after a refusal and retries with it', async () => {
    let attempts = 0;
    const api = fakeApi(async function* () {
      attempts += 1;
      if (attempts === 1) {
        throw new ApiError(
          401,
          'unauthorized',
          'Send the service token as: Authorization: Bearer <token>.',
        );
      }
      yield* answers();
    });
    const { fixture, element } = await render(api);

    (element.querySelector('.example') as HTMLButtonElement).click();
    await fixture.whenStable();
    const input = element.querySelector('#token') as HTMLInputElement;
    expect(input).not.toBeNull();

    input.value = 'the-shared-token';
    input.dispatchEvent(new Event('input'));
    await fixture.whenStable();
    (element.querySelector('app-token-prompt form') as HTMLFormElement).dispatchEvent(
      new Event('submit'),
    );
    await fixture.whenStable();

    expect(api.token.set).toHaveBeenCalledWith('the-shared-token');
    expect(element.querySelector('#token')).toBeNull();
    expect(element.querySelector('.headline')?.textContent).toBe('Eight patients have diabetes.');
  });

  it('sends a typed question with Enter and clears the box', async () => {
    const api = fakeApi(answers);
    const { fixture, element } = await render(api);
    const box = element.querySelector('textarea') as HTMLTextAreaElement;

    box.value = 'How many patients are there?';
    box.dispatchEvent(new Event('input'));
    await fixture.whenStable();
    box.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));
    await fixture.whenStable();

    expect(api.askStream).toHaveBeenCalledWith('How many patients are there?', null);
    expect(box.value).toBe('');
  });

  describe('with stored conversations', () => {
    const other = summaryFixture({ id: 'd'.repeat(32), title: '<b>Heart</b> disease by age' });

    async function withList() {
      const api = fakeApi(answers);
      api.conversations.mockResolvedValue([summaryFixture(), other]);
      const rendered = await render(api);
      const titles = () => [
        ...rendered.element.querySelectorAll<HTMLButtonElement>('.side .title'),
      ];
      return { api, titles, ...rendered };
    }

    it('lists them as plain text and opens the one that is clicked', async () => {
      const { api, titles, fixture, element } = await withList();
      expect(titles().map((button) => button.textContent?.trim())).toEqual([
        'How many patients have diabetes?',
        '<b>Heart</b> disease by age',
      ]);
      expect(element.querySelector('.side b')).toBeNull();

      titles()[0].click();
      await fixture.whenStable();

      expect(api.conversation).toHaveBeenCalledWith('c'.repeat(32));
      expect(element.querySelector('.question')?.textContent).toBe(
        'How many patients have diabetes?',
      );
      expect(element.querySelector('.headline')?.textContent).toBe('Eight patients have diabetes.');
      expect(titles()[0].getAttribute('aria-current')).toBe('true');
      expect(location.hash).toBe('#' + 'c'.repeat(32));
    });

    it('returns to the conversation named in the address after a reload', async () => {
      history.replaceState(null, '', '#' + 'c'.repeat(32));
      const { api, fixture, element } = await withList();
      await vi.waitFor(async () => {
        await fixture.whenStable();
        expect(element.querySelector('.headline')?.textContent).toBe(
          'Eight patients have diabetes.',
        );
      });
      expect(api.conversation).toHaveBeenCalledWith('c'.repeat(32));
    });

    it('starts a new chat, clearing the screen and the address', async () => {
      history.replaceState(null, '', '#' + 'c'.repeat(32));
      const { fixture, element } = await withList();

      (element.querySelector('.side .new') as HTMLButtonElement).click();
      await fixture.whenStable();

      expect(element.querySelector('.question')).toBeNull();
      expect(element.querySelector('.intro')).not.toBeNull();
      expect(location.hash).toBe('');
    });

    it('renames a conversation from the list', async () => {
      const { api, titles, fixture, element } = await withList();
      const row = element.querySelectorAll('.side li')[1];

      (row.querySelector('.tools button') as HTMLButtonElement).click();
      await fixture.whenStable();
      const input = row.querySelector('input') as HTMLInputElement;
      expect(input.value).toBe(other.title);
      input.value = 'Heart disease';
      input.dispatchEvent(new Event('input'));
      (row.querySelector('form') as HTMLFormElement).dispatchEvent(new Event('submit'));
      await fixture.whenStable();

      expect(api.renameConversation).toHaveBeenCalledWith(other.id, 'Heart disease');
      expect(titles()[1].textContent?.trim()).toBe('Heart disease');
    });

    it('deletes a conversation only after it is confirmed', async () => {
      const { api, titles, fixture, element } = await withList();
      const row = element.querySelectorAll('.side li')[1];

      (row.querySelectorAll('.tools button')[1] as HTMLButtonElement).click();
      await fixture.whenStable();
      expect(api.deleteConversation).not.toHaveBeenCalled();
      expect(row.querySelector('.ask')?.textContent).toBe('Delete this conversation?');

      (row.querySelector('.danger') as HTMLButtonElement).click();
      await fixture.whenStable();

      expect(api.deleteConversation).toHaveBeenCalledWith(other.id);
      expect(titles().length).toBe(1);
    });
  });
});
