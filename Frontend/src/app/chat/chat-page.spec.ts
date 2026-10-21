import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';

import { AgentApi, ApiError, UNREACHABLE } from '../api/agent-api';
import { ConversationSummary, Health, StreamEvent } from '../api/types';
import { provideAppRouter } from '../app.config';
import {
  answerFixture,
  catalogFixture,
  conversationFixture,
  summaryFixture,
} from '../testing/fixtures';
import { ChatPage, EXAMPLE_QUESTIONS } from './chat-page';

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
    conversations: vi.fn(async (_search?: string): Promise<ConversationSummary[]> => []),
    conversation: vi.fn(async (_id: string) => conversationFixture()),
    updateConversation: vi.fn(async (id: string, changes: { title?: string; pinned?: boolean }) =>
      summaryFixture({
        id,
        title:
          changes.title ??
          (id === 'c'.repeat(32)
            ? 'How many patients have diabetes?'
            : '<b>Heart</b> disease by age'),
        pinned_at: changes.pinned ? '2026-10-21T12:00:00Z' : null,
      }),
    ),
    deleteConversation: vi.fn(async (_id: string) => undefined),
    models: vi.fn(async () => catalogFixture()),
  };
}

/** Open the app at an address, as a page load would, and return the chat page. */
async function render(api: ReturnType<typeof fakeApi>, url = '/') {
  TestBed.configureTestingModule({
    providers: [{ provide: AgentApi, useValue: api }, provideAppRouter()],
  });
  const harness = await RouterTestingHarness.create();
  await harness.navigateByUrl(url, ChatPage);
  const fixture = harness.fixture;
  await fixture.whenStable();
  const element = harness.routeNativeElement as HTMLElement;
  return { fixture, element, harness };
}

/** The address the router is showing. */
function address(): string {
  return TestBed.inject(Router).url;
}

async function* answers(overrides = {}): AsyncGenerator<StreamEvent> {
  yield { type: 'conversation', conversationId: 'c'.repeat(32), turn: 1 };
  yield { type: 'answer', answer: answerFixture(overrides) };
}

describe('ChatPage', () => {
  it('shows the service status and the example questions', async () => {
    const { element } = await render(fakeApi(answers));
    expect(element.querySelector('.status')?.textContent).toContain(
      'Connected · synthetic data as of 2026-08-16',
    );
    const examples = [...element.querySelectorAll('.example')].map((button) =>
      button.textContent?.trim(),
    );
    expect(examples).toEqual(EXAMPLE_QUESTIONS);
  });

  it('says plainly when the service cannot be reached, without developer commands', async () => {
    const { element } = await render(
      fakeApi(answers, async () => {
        throw new ApiError(0, 'unreachable', UNREACHABLE);
      }),
    );
    const status = element.querySelector('.status');
    expect(status?.textContent).toContain('The service cannot be reached');
    expect(status?.textContent).not.toContain('sql_agent');
    expect(status?.classList).toContain('down');
  });

  it('asks an example question and shows the answer with its citations', async () => {
    const api = fakeApi(answers);
    const { fixture, element } = await render(api);

    (element.querySelector('.example') as HTMLButtonElement).click();
    await fixture.whenStable();

    expect(api.askStream).toHaveBeenCalledWith(EXAMPLE_QUESTIONS[0], null, undefined, {
      model: 'claude-opus-5',
      effort: 'high',
    });
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

    expect(api.askStream).toHaveBeenCalledWith('How many patients are there?', null, undefined, {
      model: 'claude-opus-5',
      effort: 'high',
    });
    expect(box.value).toBe('');
  });

  describe('choosing the model', () => {
    /** Open one of the picker's menus and pick the item whose name is this. */
    async function pick(fixture: ComponentFixture<unknown>, menu: number, name: string) {
      const pills = fixture.nativeElement.querySelectorAll('app-model-picker .pill');
      (pills[menu] as HTMLButtonElement).click();
      await fixture.whenStable();
      const items = [...document.querySelectorAll<HTMLButtonElement>('.picker-menu .menu-item')];
      items.find((item) => item.querySelector('.name')?.textContent?.trim() === name)!.click();
      await fixture.whenStable();
    }
    const pills = (element: HTMLElement) =>
      [...element.querySelectorAll('app-model-picker .pill')].map((pill) =>
        pill.textContent?.trim(),
      );

    it('starts on the default and lists every model with its price and evaluation', async () => {
      const { fixture, element } = await render(fakeApi(answers));
      expect(pills(element)).toEqual(['Opus 5', 'High effort']);

      (element.querySelector('app-model-picker .pill') as HTMLButtonElement).click();
      await fixture.whenStable();
      const options = [...document.querySelectorAll('.picker-menu .option')];
      expect(options.map((option) => option.querySelector('.name')?.textContent?.trim())).toEqual([
        'Opus 5',
        'Haiku 5.5',
      ]);
      expect(options[1].querySelector('.facts')?.textContent).toContain(
        '$0.10 / $0.50 per million tokens',
      );
      expect(options[1].querySelector('.facts')?.textContent).toContain('Not yet evaluated');
      expect(options[0].getAttribute('aria-checked')).toBe('true');
    });

    it('asks on the model and effort picked, keeping an effort the new model offers', async () => {
      const api = fakeApi(answers);
      const { fixture, element } = await render(api);

      await pick(fixture, 1, 'Low');
      await pick(fixture, 0, 'Haiku 5.5');
      expect(pills(element)).toEqual(['Haiku 5.5', 'Low effort']);

      (element.querySelector('.example') as HTMLButtonElement).click();
      await fixture.whenStable();
      expect(api.askStream).toHaveBeenLastCalledWith(EXAMPLE_QUESTIONS[0], null, undefined, {
        model: 'claude-haiku-5-5',
        effort: 'low',
      });
    });

    it("takes the new model's default when it does not offer the effort", async () => {
      const { fixture, element } = await render(fakeApi(answers));
      await pick(fixture, 1, 'Max');
      await pick(fixture, 0, 'Haiku 5.5');
      expect(pills(element)).toEqual(['Haiku 5.5', 'Medium effort']);
    });

    it('continues a reopened conversation on the model its latest answer used', async () => {
      const api = fakeApi(answers);
      api.conversation.mockResolvedValue(
        conversationFixture({ last_model: 'claude-haiku-5-5', last_effort: 'low' }),
      );
      const { fixture, element } = await render(api, '/c/' + 'c'.repeat(32));
      await vi.waitFor(async () => {
        await fixture.whenStable();
        expect(pills(element)).toEqual(['Haiku 5.5', 'Low effort']);
      });
    });

    it('shows the model and effort under each answer', async () => {
      const { fixture, element } = await render(
        fakeApi(() => answers({ model: 'claude-haiku-5-5', effort: 'low' })),
      );
      (element.querySelector('.example') as HTMLButtonElement).click();
      await fixture.whenStable();
      expect(element.querySelector('.meta')?.textContent).toContain(
        'claude-haiku-5-5 at low effort',
      );
    });
  });

  describe('with stored conversations', () => {
    const other = summaryFixture({ id: 'd'.repeat(32), title: '<b>Heart</b> disease by age' });

    async function withList(url = '/') {
      const api = fakeApi(answers);
      api.conversations.mockResolvedValue([summaryFixture(), other]);
      const rendered = await render(api, url);
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
      expect(address()).toBe('/c/' + 'c'.repeat(32));
      expect(element.querySelector('h1')?.textContent).toBe('How many patients have diabetes?');
    });

    it('returns to the conversation named in the address after a reload', async () => {
      const { api, fixture, element } = await withList('/c/' + 'c'.repeat(32));
      await vi.waitFor(async () => {
        await fixture.whenStable();
        expect(element.querySelector('.headline')?.textContent).toBe(
          'Eight patients have diabetes.',
        );
      });
      expect(api.conversation).toHaveBeenCalledWith('c'.repeat(32));
    });

    it('moves a link from before the router, with the id after "#", to the new address', async () => {
      const { api, fixture } = await withList('/#' + 'c'.repeat(32));
      await vi.waitFor(async () => {
        await fixture.whenStable();
        expect(address()).toBe('/c/' + 'c'.repeat(32));
      });
      expect(api.conversation).toHaveBeenCalledTimes(1);
    });

    it('starts a new chat, clearing the screen and the address', async () => {
      const { fixture, element } = await withList('/c/' + 'c'.repeat(32));
      await vi.waitFor(async () => {
        await fixture.whenStable();
        expect(element.querySelector('.question')).not.toBeNull();
      });

      (element.querySelector('.side .new') as HTMLButtonElement).click();
      await vi.waitFor(async () => {
        await fixture.whenStable();
        expect(address()).toBe('/');
      });

      expect(element.querySelector('.question')).toBeNull();
      expect(element.querySelector('.intro')).not.toBeNull();
    });

    it('goes back to the address of a conversation that does not exist', async () => {
      const api = fakeApi(answers);
      api.conversation.mockRejectedValue(
        new ApiError(404, 'unknown_conversation', 'No such conversation.'),
      );
      const { fixture, element } = await render(api, '/c/' + 'e'.repeat(32));
      await vi.waitFor(async () => {
        await fixture.whenStable();
        expect(address()).toBe('/');
      });
      expect(element.querySelector('.intro')).not.toBeNull();
    });

    it('puts a new chat in the address once the service gives it an id', async () => {
      const { fixture, element } = await render(fakeApi(answers));
      (element.querySelector('.example') as HTMLButtonElement).click();
      await vi.waitFor(async () => {
        await fixture.whenStable();
        expect(address()).toBe('/c/' + 'c'.repeat(32));
      });
      expect(element.querySelector('.headline')?.textContent).toBe('Eight patients have diabetes.');
    });

    /** Open a row's "⋯" menu and pick the item with this text. */
    async function choose(fixture: ComponentFixture<unknown>, row: Element, item: string) {
      (row.querySelector('.more') as HTMLButtonElement).click();
      await fixture.whenStable();
      const items = [...document.querySelectorAll<HTMLButtonElement>('.menu .menu-item')];
      const found = items.find((button) => button.textContent?.trim() === item);
      expect(found, `menu item ${item}`).toBeDefined();
      found!.click();
      await fixture.whenStable();
    }

    it('renames a conversation from its menu', async () => {
      const { api, titles, fixture, element } = await withList();
      const row = element.querySelectorAll('.side li')[1];

      await choose(fixture, row, 'Rename');
      const input = row.querySelector('input') as HTMLInputElement;
      expect(input.value).toBe(other.title);
      input.value = 'Heart disease';
      input.dispatchEvent(new Event('input'));
      (row.querySelector('form') as HTMLFormElement).dispatchEvent(new Event('submit'));
      await fixture.whenStable();

      expect(api.updateConversation).toHaveBeenCalledWith(other.id, { title: 'Heart disease' });
      expect(api.updateConversation).toHaveBeenCalledTimes(1);
      expect(titles()[1].textContent?.trim()).toBe('Heart disease');
    });

    it('cancels a rename with Escape, keeping the old title', async () => {
      const { api, fixture, element } = await withList();
      const row = element.querySelectorAll('.side li')[1];
      await choose(fixture, row, 'Rename');
      const input = row.querySelector('input') as HTMLInputElement;
      input.value = 'Something else';
      input.dispatchEvent(new Event('input'));
      input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
      input.dispatchEvent(new Event('blur'));
      await fixture.whenStable();
      expect(api.updateConversation).not.toHaveBeenCalled();
      expect(row.querySelector('input')).toBeNull();
    });

    it('deletes a conversation only after the dialog is confirmed', async () => {
      const { api, titles, fixture, element } = await withList();
      const row = element.querySelectorAll('.side li')[1];

      await choose(fixture, row, 'Delete');
      const dialog = document.querySelector('app-confirm-dialog') as HTMLElement;
      expect(dialog.querySelector('h2')?.textContent).toBe('Delete this conversation?');
      expect(dialog.querySelector('p')?.textContent).toContain('"<b>Heart</b> disease by age"');
      expect(dialog.querySelector('b')).toBeNull();
      expect(api.deleteConversation).not.toHaveBeenCalled();

      (dialog.querySelector('.secondary') as HTMLButtonElement).click();
      await fixture.whenStable();
      expect(api.deleteConversation).not.toHaveBeenCalled();

      await choose(fixture, row, 'Delete');
      (document.querySelector('app-confirm-dialog .confirm') as HTMLButtonElement).click();
      await vi.waitFor(async () => {
        await fixture.whenStable();
        expect(api.deleteConversation).toHaveBeenCalledWith(other.id);
      });
      expect(titles().length).toBe(1);
    });

    it('pins a conversation into the Pinned section and unpins it back', async () => {
      const { api, fixture, element } = await withList();
      const sectionTitles = () =>
        [...element.querySelectorAll('.side .section .section-toggle')].map((button) =>
          button.textContent?.trim(),
        );
      expect(sectionTitles()).toEqual(['Recents']);

      await choose(fixture, element.querySelectorAll('.side li')[1], 'Pin');
      expect(api.updateConversation).toHaveBeenCalledWith(other.id, { pinned: true });
      expect(sectionTitles()).toEqual(['Pinned', 'Recents']);
      const pinnedRow = element.querySelector('#section-pinned li') as HTMLElement;
      expect(pinnedRow.querySelector('.title')?.textContent?.trim()).toBe(other.title);

      await choose(fixture, pinnedRow, 'Unpin');
      expect(api.updateConversation).toHaveBeenLastCalledWith(other.id, { pinned: false });
      expect(sectionTitles()).toEqual(['Recents']);
    });

    it('collapses a section and remembers it', async () => {
      localStorage.removeItem('sql-agent.sections');
      const { fixture, element } = await withList();
      const toggle = element.querySelector('.side .section-toggle') as HTMLButtonElement;
      expect(toggle.getAttribute('aria-expanded')).toBe('true');
      toggle.click();
      await fixture.whenStable();
      expect(toggle.getAttribute('aria-expanded')).toBe('false');
      expect((element.querySelector('#section-recents') as HTMLElement).hidden).toBe(true);
      expect(JSON.parse(localStorage.getItem('sql-agent.sections')!).recents).toBe(false);
      localStorage.removeItem('sql-agent.sections');
    });

    it('searches titles and questions on the service and shows only the matches', async () => {
      const { api, fixture, element } = await withList();
      api.conversations.mockResolvedValue([other]);
      const box = element.querySelector('#conversation-search') as HTMLInputElement;

      box.value = 'heart';
      box.dispatchEvent(new Event('input'));
      await vi.waitFor(async () => {
        await fixture.whenStable();
        expect(api.conversations).toHaveBeenLastCalledWith('heart');
        expect(element.querySelectorAll('.side li').length).toBe(1);
      });
      expect(element.querySelector('.side .label')?.textContent).toBe('Results');

      api.conversations.mockResolvedValue([]);
      box.value = 'cancer';
      box.dispatchEvent(new Event('input'));
      await vi.waitFor(async () => {
        await fixture.whenStable();
        expect(element.querySelector('.side .empty')?.textContent).toBe(
          'No conversations match "cancer".',
        );
      });

      box.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
      await fixture.whenStable();
      expect(box.value).toBe('');
      expect(element.querySelectorAll('.side li').length).toBe(2);
    });

    it('puts the cursor in the search box on Ctrl+K, opening the sidebar if it was a rail', async () => {
      localStorage.setItem('sql-agent.sidebar', JSON.stringify({ width: 272, collapsed: true }));
      const { fixture, element } = await withList();
      expect(element.querySelector('#conversation-search')).toBeNull();

      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', ctrlKey: true }));
      await fixture.whenStable();
      expect(document.activeElement?.id).toBe('conversation-search');
      expect(element.classList).not.toContain('collapsed');
      localStorage.removeItem('sql-agent.sidebar');
    });
  });

  describe('sidebar size', () => {
    beforeEach(() => localStorage.removeItem('sql-agent.sidebar'));
    afterEach(() => localStorage.removeItem('sql-agent.sidebar'));

    const host = (element: HTMLElement) => element as HTMLElement;
    const width = (element: HTMLElement) => host(element).style.getPropertyValue('--side-width');

    it('collapses and expands without touching the conversation', async () => {
      const api = fakeApi(answers);
      const { fixture, element } = await render(api);
      (element.querySelector('.example') as HTMLButtonElement).click();
      await fixture.whenStable();

      const toggle = () => element.querySelector('.side .toggle') as HTMLButtonElement;
      expect(toggle().getAttribute('aria-label')).toBe('Hide conversations');
      toggle().click();
      await fixture.whenStable();
      expect(element.classList).toContain('collapsed');
      expect(JSON.parse(localStorage.getItem('sql-agent.sidebar')!).collapsed).toBe(true);
      expect(element.querySelector('.headline')?.textContent).toBe('Eight patients have diabetes.');

      // The rail keeps the toggle first, with New chat and Search, and no list.
      expect(toggle().getAttribute('aria-label')).toBe('Show conversations');
      expect(element.querySelector('.side .rail-actions')).not.toBeNull();
      expect(element.querySelector('.side nav')).toBeNull();
      expect(element.querySelector('.side')?.firstElementChild?.firstElementChild).toBe(toggle());

      toggle().click();
      await fixture.whenStable();
      expect(element.classList).not.toContain('collapsed');
      expect(element.querySelector('.headline')?.textContent).toBe('Eight patients have diabetes.');
      expect(api.askStream).toHaveBeenCalledTimes(1);
      expect(api.conversation).not.toHaveBeenCalled();
    });

    it('is resized by dragging its edge, within limits, and remembers the width', async () => {
      const { fixture, element } = await render(fakeApi(answers));
      const edge = element.querySelector('.resizer') as HTMLElement;
      expect(width(element)).toBe('272px');

      edge.dispatchEvent(new MouseEvent('pointerdown', { button: 0, clientX: 272 }));
      edge.dispatchEvent(new MouseEvent('pointermove', { clientX: 350 }));
      await fixture.whenStable();
      expect(element.classList).toContain('resizing');
      expect(width(element)).toBe('350px');

      edge.dispatchEvent(new MouseEvent('pointermove', { clientX: 20 }));
      edge.dispatchEvent(new MouseEvent('pointerup'));
      await fixture.whenStable();
      expect(element.classList).not.toContain('resizing');
      expect(width(element)).toBe('200px');
      expect(edge.getAttribute('aria-valuenow')).toBe('200');

      edge.dispatchEvent(new MouseEvent('pointermove', { clientX: 400 }));
      await fixture.whenStable();
      expect(width(element)).toBe('200px');
      expect(JSON.parse(localStorage.getItem('sql-agent.sidebar')!).width).toBe(200);
    });

    it('is resized with the keyboard and reset with a double-click', async () => {
      const { fixture, element } = await render(fakeApi(answers));
      const edge = element.querySelector('.resizer') as HTMLElement;

      edge.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight' }));
      edge.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight' }));
      await fixture.whenStable();
      expect(width(element)).toBe('304px');

      edge.dispatchEvent(new KeyboardEvent('keydown', { key: 'Home' }));
      await fixture.whenStable();
      expect(width(element)).toBe('200px');

      edge.dispatchEvent(new MouseEvent('dblclick'));
      await fixture.whenStable();
      expect(width(element)).toBe('272px');
    });

    it('opens at the size and state it was left in', async () => {
      localStorage.setItem('sql-agent.sidebar', JSON.stringify({ width: 330, collapsed: true }));
      const { element } = await render(fakeApi(answers));
      expect(width(element)).toBe('330px');
      expect(element.classList).toContain('collapsed');
    });
  });
});
