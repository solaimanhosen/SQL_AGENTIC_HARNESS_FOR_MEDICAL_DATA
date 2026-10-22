import { DOCUMENT } from '@angular/common';
import {
  Component,
  DestroyRef,
  ElementRef,
  OnInit,
  afterRenderEffect,
  computed,
  effect,
  inject,
  input,
  signal,
  untracked,
  viewChild,
} from '@angular/core';
import { CdkTrapFocus } from '@angular/cdk/a11y';
import { ActivatedRoute, Router } from '@angular/router';
import { LucidePanelLeft } from '@lucide/angular';

import { AgentApi } from '../api/agent-api';
import { Health } from '../api/types';
import {
  NARROW_QUERY,
  SIDEBAR_DEFAULT,
  SIDEBAR_MIN,
  SIDEBAR_STEP,
  clampWidth,
  loadLayout,
  maxWidth,
  saveLayout,
} from '../sidebar-layout';
import { ProfileMenu } from '../ui/profile-menu';
import { ThemeToggle } from '../ui/theme-toggle';
import { storageOf } from '../ui/theme';
import { ChatStore } from './chat-store';
import { Composer } from './composer';
import { ExchangeView } from './exchange-view';
import { Sidebar, SidebarMode } from './sidebar';

export const EXAMPLE_QUESTIONS = [
  'How many patients have diabetes?',
  'How many diabetic patients had an emergency visit in the last 12 months?',
  'Which age band has the most hospital visits?',
];

/** A conversation id as the service issues it. Anything else is not a conversation address. */
export const CONVERSATION_ID = /^[0-9a-f]{32}$/;

/**
 * The chat screen: the conversation list, the thread and the question box. The address names
 * the conversation on screen, "/c/<id>", or "/" for a new one, so reloading, the back button
 * and shared links all return to it.
 */
@Component({
  selector: 'app-chat-page',
  imports: [
    CdkTrapFocus,
    Composer,
    ExchangeView,
    LucidePanelLeft,
    ProfileMenu,
    Sidebar,
    ThemeToggle,
  ],
  templateUrl: './chat-page.html',
  styleUrl: './chat-page.css',
  host: {
    '[style.--side-width]': "sideWidth() + 'px'",
    '[class.collapsed]': 'collapsed()',
    '[class.resizing]': 'resizing()',
    '(document:keydown)': 'onKeydown($event)',
  },
})
export class ChatPage implements OnInit {
  protected readonly store = inject(ChatStore);
  private readonly api = inject(AgentApi);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);

  /** The conversation in the address, bound from the route. Undefined for a new chat. */
  readonly id = input<string>();

  protected readonly examples = EXAMPLE_QUESTIONS;
  protected readonly health = signal<Health | 'checking' | 'unreachable'>('checking');
  /** Whether the conversation list is drawn over the page, at phone width. */
  protected readonly menuOpen = signal(false);
  private readonly end = viewChild<ElementRef<HTMLElement>>('end');
  private readonly sidebar = viewChild.required<Sidebar>('sidebar');
  private readonly menuToggle = viewChild<ElementRef<HTMLButtonElement>>('menuToggle');
  private readonly window = inject(DOCUMENT).defaultView;
  /** True at phone width, where the sidebar is a drawer instead of a column. */
  protected readonly narrow = signal(this.window?.matchMedia?.(NARROW_QUERY).matches ?? false);
  protected readonly drawerOpen = computed(() => this.narrow() && this.menuOpen());
  protected readonly sideMode = computed<SidebarMode>(() =>
    this.narrow() ? 'drawer' : this.collapsed() ? 'rail' : 'full',
  );
  /** False until the address has been read once, so it is not overwritten before then. */
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

  /**
   * What a screen reader hears when an answer arrives or a question ends, read from the
   * newest exchange. The live steps announce themselves inside the exchange.
   */
  protected readonly announcement = computed(() => {
    const last = this.store.exchanges().at(-1);
    if (!last || last.status === 'working') {
      return '';
    }
    if (last.status === 'answered') {
      return `Answer ready: ${last.answer?.headline ?? 'see below'}`;
    }
    return last.error?.message ?? 'The question did not finish.';
  });

  /** The open conversation's title, or nothing for a new chat. */
  protected readonly title = computed(() => {
    const id = this.store.conversationId();
    return this.store.conversations().find((item) => item.id === id)?.title ?? '';
  });

  constructor() {
    const media = this.window?.matchMedia?.(NARROW_QUERY);
    const follow = (event: MediaQueryListEvent) => this.narrow.set(event.matches);
    media?.addEventListener?.('change', follow);
    inject(DestroyRef).onDestroy(() => media?.removeEventListener?.('change', follow));
    // Keep the newest step or answer in view as the conversation grows.
    afterRenderEffect(() => {
      this.store.exchanges();
      this.end()?.nativeElement.scrollIntoView?.({ block: 'end' });
    });
    effect(() =>
      saveLayout(this.storage, { width: this.sideWidth(), collapsed: this.collapsed() }),
    );
    // The address changed, by a link, the back button or a click in the list: show that one.
    effect(() => {
      const id = this.id() ?? null;
      if (this.restored()) {
        untracked(() => void this.follow(id));
      }
    });
    // The conversation on screen changed, when a new chat got its id or the open one was
    // deleted: put it in the address without adding a step to the history.
    effect(() => {
      const id = this.store.conversationId();
      if (this.restored() && id !== (untracked(this.id) ?? null)) {
        untracked(() => void this.address(id));
      }
    });
  }

  async ngOnInit(): Promise<void> {
    try {
      this.health.set(await this.api.health());
    } catch {
      this.health.set('unreachable');
    }
    // Before the conversation is opened, so its last model can be restored.
    await this.store.loadModels();
    await this.restore();
  }

  /** Load the list, and the conversation named in the address if there is one. */
  private async restore(): Promise<void> {
    await this.store.refreshConversations();
    // Links from before the router named the conversation after a "#".
    const legacy = this.route.snapshot.fragment;
    const id = this.id() ?? (legacy && CONVERSATION_ID.test(legacy) ? legacy : null);
    if (id && id !== this.store.conversationId()) {
      await this.store.open(id);
    }
    // Correct the address first, so following it afterwards changes nothing.
    if ((this.id() ?? null) !== this.store.conversationId() || legacy) {
      await this.address(this.store.conversationId());
    }
    this.restored.set(true);
  }

  /** Show the conversation the address names, or a new chat. */
  private async follow(id: string | null): Promise<void> {
    if (id === this.store.conversationId()) {
      return;
    }
    if (this.store.busy()) {
      // An answer is still being written here. Stay with it.
      void this.address(this.store.conversationId());
      return;
    }
    if (id === null) {
      this.store.newConversation();
    } else if (!(await this.store.open(id))) {
      void this.address(this.store.conversationId());
    }
  }

  private address(id: string | null): Promise<boolean> {
    return this.router.navigate(id ? ['/c', id] : ['/'], { replaceUrl: true });
  }

  protected newChat(): void {
    this.menuOpen.set(false);
    void this.router.navigate(['/']);
  }

  protected open(id: string): void {
    this.menuOpen.set(false);
    if (id !== this.store.conversationId()) {
      void this.router.navigate(['/c', id]);
    }
  }

  /**
   * The sidebar's own toggle: close the drawer on a phone, or switch between the full sidebar
   * and the rail. Nothing about the conversation on screen changes.
   */
  protected toggleSidebar(): void {
    if (this.narrow()) {
      this.closeDrawer();
    } else {
      this.collapsed.update((collapsed) => !collapsed);
    }
  }

  /** Show the sidebar, whatever its state, with the cursor in the search box. */
  protected openSearch(): void {
    if (this.narrow()) {
      this.menuOpen.set(true);
    } else {
      this.collapsed.set(false);
    }
    this.sidebar().focusSearch();
  }

  /** Open the drawer at phone width, and move the keyboard into it. */
  protected openDrawer(): void {
    this.menuOpen.set(true);
    this.sidebar().focusToggle();
  }

  private closeDrawer(): void {
    this.menuOpen.set(false);
    this.menuToggle()?.nativeElement.focus();
  }

  /** Ctrl+K or Cmd+K searches the conversations; Escape closes the drawer. */
  protected onKeydown(event: KeyboardEvent): void {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
      event.preventDefault();
      this.openSearch();
    } else if (event.key === 'Escape' && this.drawerOpen()) {
      this.closeDrawer();
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

  protected ask(question: string): void {
    void this.store.ask(question);
  }

  protected healthInfo(): Health | null {
    const health = this.health();
    return typeof health === 'string' ? null : health;
  }
}
