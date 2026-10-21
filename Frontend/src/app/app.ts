import { DOCUMENT } from '@angular/common';
import {
  Component,
  ElementRef,
  OnInit,
  afterRenderEffect,
  effect,
  inject,
  signal,
  viewChild,
} from '@angular/core';

import { AgentApi } from './api/agent-api';
import { Health } from './api/types';
import { ChatStore } from './chat/chat-store';
import { Composer } from './chat/composer';
import { ExchangeView } from './chat/exchange-view';
import { Sidebar } from './chat/sidebar';
import { TokenPrompt } from './chat/token-prompt';
import {
  NARROW_QUERY,
  SIDEBAR_DEFAULT,
  SIDEBAR_MIN,
  SIDEBAR_STEP,
  clampWidth,
  loadLayout,
  maxWidth,
  saveLayout,
} from './sidebar-layout';

export const EXAMPLE_QUESTIONS = [
  'How many patients have diabetes?',
  'How many diabetic patients had an emergency visit in the last 12 months?',
  'Which age band has the most hospital visits?',
];

@Component({
  selector: 'app-root',
  imports: [Composer, ExchangeView, Sidebar, TokenPrompt],
  templateUrl: './app.html',
  styleUrl: './app.css',
  host: {
    '[style.--side-width]': "sideWidth() + 'px'",
    '[class.collapsed]': 'collapsed()',
    '[class.resizing]': 'resizing()',
  },
})
export class App implements OnInit {
  protected readonly store = inject(ChatStore);
  private readonly api = inject(AgentApi);

  protected readonly examples = EXAMPLE_QUESTIONS;
  protected readonly health = signal<Health | 'checking' | 'unreachable'>('checking');
  /** Whether the conversation list is drawn over the page, at phone width. */
  protected readonly menuOpen = signal(false);
  private readonly end = viewChild<ElementRef<HTMLElement>>('end');
  private readonly window = inject(DOCUMENT).defaultView;
  private readonly restored = signal(false);

  private readonly storage = storageOf(this.window);
  private readonly layout = loadLayout(this.storage);
  /** The sidebar's width in pixels, set by dragging its edge and kept between visits. */
  protected readonly sideWidth = signal(this.layout.width);
  /** Whether the sidebar is hidden on a wide screen. A phone uses the drawer instead. */
  protected readonly collapsed = signal(this.layout.collapsed);
  /** True while the edge is being dragged, so the width follows the pointer without easing. */
  protected readonly resizing = signal(false);
  protected readonly sideMin = SIDEBAR_MIN;

  constructor() {
    // Keep the newest step or answer in view as the conversation grows.
    afterRenderEffect(() => {
      this.store.exchanges();
      this.end()?.nativeElement.scrollIntoView?.({ block: 'end' });
    });
    effect(() =>
      saveLayout(this.storage, { width: this.sideWidth(), collapsed: this.collapsed() }),
    );
    // Keep the conversation in the address, so reloading the page returns to it.
    effect(() => {
      const id = this.store.conversationId();
      if (this.restored() && this.window && addressId(this.window) !== id) {
        const { pathname, search } = this.window.location;
        this.window.history.replaceState(null, '', pathname + search + (id ? `#${id}` : ''));
      }
    });
  }

  async ngOnInit(): Promise<void> {
    try {
      this.health.set(await this.api.health());
    } catch {
      this.health.set('unreachable');
    }
    await this.restore();
  }

  /** Load the list, and the conversation named in the address if there is one. */
  private async restore(): Promise<void> {
    await this.store.refreshConversations();
    const id = this.window ? addressId(this.window) : null;
    if (id && id !== this.store.conversationId() && !this.store.needsToken()) {
      await this.store.open(id);
    }
    // While the token is still needed the address is left alone, to be tried again with it.
    this.restored.set(!this.store.needsToken());
  }

  protected newChat(): void {
    this.store.newConversation();
    this.menuOpen.set(false);
  }

  protected open(id: string): void {
    this.menuOpen.set(false);
    if (id !== this.store.conversationId()) {
      void this.store.open(id);
    }
  }

  /** Show the conversations: open the drawer on a phone, or expand the sidebar. */
  protected showSidebar(): void {
    if (this.narrow()) {
      this.menuOpen.set(true);
    } else {
      this.collapsed.set(false);
    }
  }

  /** Hide the conversations. Nothing about the conversation on screen changes. */
  protected hideSidebar(): void {
    if (this.narrow()) {
      this.menuOpen.set(false);
    } else {
      this.collapsed.set(true);
    }
  }

  protected sideMax(): number {
    return maxWidth(this.window?.innerWidth ?? Infinity);
  }

  protected startResize(event: PointerEvent): void {
    if (event.button !== 0) {
      return;
    }
    event.preventDefault();
    (event.target as Element).setPointerCapture?.(event.pointerId);
    this.resizing.set(true);
  }

  protected resize(event: PointerEvent): void {
    if (this.resizing()) {
      // The sidebar starts at the left edge of the window, so the pointer gives its width.
      this.setWidth(event.clientX);
    }
  }

  protected endResize(): void {
    this.resizing.set(false);
  }

  /** Arrow keys move the edge, Home and End go to the narrowest and widest. */
  protected resizeWithKey(event: KeyboardEvent): void {
    const width = this.sideWidth();
    const next: Record<string, number> = {
      ArrowLeft: width - SIDEBAR_STEP,
      ArrowRight: width + SIDEBAR_STEP,
      Home: SIDEBAR_MIN,
      End: this.sideMax(),
    };
    if (event.key in next) {
      event.preventDefault();
      this.setWidth(next[event.key]);
    }
  }

  protected resetWidth(): void {
    this.setWidth(SIDEBAR_DEFAULT);
  }

  private setWidth(width: number): void {
    this.sideWidth.set(clampWidth(width, this.window?.innerWidth ?? Infinity));
  }

  private narrow(): boolean {
    return this.window?.matchMedia?.(NARROW_QUERY).matches ?? false;
  }

  protected ask(question: string): void {
    void this.store.ask(question);
  }

  protected useToken(token: string): void {
    this.api.token.set(token);
    this.store.needsToken.set(false);
    const failed = this.store.lastFailed();
    if (failed) {
      void this.store.retry(failed.id);
    }
    if (!this.restored()) {
      void this.restore();
    }
  }

  protected healthInfo(): Health | null {
    const health = this.health();
    return typeof health === 'string' ? null : health;
  }
}

/** The conversation id in the address, if it holds a well-formed one. */
function addressId(window: Window): string | null {
  const id = window.location.hash.slice(1);
  return /^[0-9a-f]{32}$/.test(id) ? id : null;
}

function storageOf(window: Window | null): Storage | undefined {
  try {
    return window?.localStorage;
  } catch {
    return undefined; // Reading it can throw when site data is blocked.
  }
}
