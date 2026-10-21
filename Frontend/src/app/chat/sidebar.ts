import { CdkMenu, CdkMenuItem, CdkMenuTrigger } from '@angular/cdk/menu';
import { NgTemplateOutlet } from '@angular/common';
import {
  Component,
  ElementRef,
  Injector,
  OnDestroy,
  afterNextRender,
  computed,
  inject,
  input,
  output,
  signal,
  viewChild,
} from '@angular/core';
import {
  LucideChevronRight,
  LucideEllipsis,
  LucidePanelLeftClose,
  LucidePanelLeftOpen,
  LucidePencil,
  LucidePin,
  LucidePinOff,
  LucideSearch,
  LucideSquarePen,
  LucideTrash,
  LucideX,
} from '@lucide/angular';

import { ConversationSummary } from '../api/types';
import { Confirm } from '../ui/confirm-dialog';
import { storageOf } from '../ui/theme';
import { partition } from './sections';

export const MAX_TITLE_CHARS = 100;
/** How long typing pauses before the service is searched. */
export const SEARCH_DELAY_MS = 250;

/**
 * - full: the expanded sidebar on a wide screen.
 * - rail: collapsed to a strip of icons on a wide screen.
 * - drawer: drawn over the page on a phone.
 */
export type SidebarMode = 'full' | 'rail' | 'drawer';

export type SectionName = 'pinned' | 'recents' | 'all';
type Expanded = Record<SectionName, boolean>;
const SECTIONS_KEY = 'sql-agent.sections';

/**
 * The conversation list: New chat, search, and the Pinned, Recents and All chats sections.
 * Its toggle stays at the same top-left spot whether it is open or a rail. Titles come from
 * what users typed, so they are rendered as text like everything else.
 */
@Component({
  selector: 'app-sidebar',
  imports: [
    CdkMenu,
    CdkMenuItem,
    CdkMenuTrigger,
    LucideChevronRight,
    LucideEllipsis,
    LucidePanelLeftClose,
    LucidePanelLeftOpen,
    LucidePencil,
    LucidePin,
    LucidePinOff,
    LucideSearch,
    LucideSquarePen,
    LucideTrash,
    LucideX,
    NgTemplateOutlet,
  ],
  templateUrl: './sidebar.html',
  styleUrl: './sidebar.css',
  host: { '[class]': "'mode-' + mode()" },
})
export class Sidebar implements OnDestroy {
  readonly conversations = input.required<ConversationSummary[]>();
  readonly activeId = input<string | null>(null);
  /** True while a question is being answered, when switching away would lose its place. */
  readonly busy = input(false);
  readonly mode = input<SidebarMode>('full');
  /** What the service found for the search text, or null while nothing has been found yet. */
  readonly searchResults = input<ConversationSummary[] | null>(null);

  readonly newChat = output<void>();
  readonly open = output<string>();
  readonly rename = output<{ id: string; title: string }>();
  readonly pin = output<{ id: string; pinned: boolean }>();
  readonly remove = output<string>();
  readonly search = output<string>();
  /** Open or close: expand the rail, collapse the sidebar, or close the drawer. */
  readonly toggle = output<void>();
  /** The rail's search button: the page expands the sidebar and then focuses the box. */
  readonly searchRequested = output<void>();

  protected readonly max = MAX_TITLE_CHARS;
  protected readonly renaming = signal<string | null>(null);
  protected readonly draftTitle = signal('');
  protected readonly query = signal('');
  protected readonly searching = computed(() => this.query().trim().length > 0);
  protected readonly sections = computed(() => partition(this.conversations()));

  private readonly storage = storageOf(typeof window === 'undefined' ? null : window);
  protected readonly expanded = signal<Expanded>(loadExpanded(this.storage));

  private readonly titleInput = viewChild<ElementRef<HTMLInputElement>>('titleInput');
  private readonly searchInput = viewChild<ElementRef<HTMLInputElement>>('searchInput');
  private readonly toggleButton = viewChild<ElementRef<HTMLButtonElement>>('toggleButton');
  private readonly injector = inject(Injector);
  private readonly confirm = inject(Confirm);
  private searchTimer: ReturnType<typeof setTimeout> | undefined;

  protected readonly toggleLabel = computed(() => {
    const labels: Record<SidebarMode, string> = {
      full: 'Hide conversations',
      rail: 'Show conversations',
      drawer: 'Close conversations',
    };
    return labels[this.mode()];
  });

  /** Move the keyboard to the toggle, the first control, once it is on screen. */
  focusToggle(): void {
    afterNextRender(() => this.toggleButton()?.nativeElement.focus(), { injector: this.injector });
  }

  /** Put the cursor in the search box, once it is on screen. */
  focusSearch(): void {
    afterNextRender(() => this.searchInput()?.nativeElement.focus(), { injector: this.injector });
  }

  ngOnDestroy(): void {
    clearTimeout(this.searchTimer);
  }

  protected onQuery(text: string): void {
    this.query.set(text);
    clearTimeout(this.searchTimer);
    this.searchTimer = setTimeout(() => this.search.emit(text), SEARCH_DELAY_MS);
  }

  protected cancelRename(event: Event): void {
    event.stopPropagation(); // Escape here cancels the rename, not the drawer too.
    this.renaming.set(null);
  }

  /** Escape clears the search first; only an empty box lets it close the drawer. */
  protected escapeSearch(event: Event): void {
    if (this.query()) {
      event.stopPropagation();
      this.clearSearch();
    }
  }

  protected clearSearch(): void {
    clearTimeout(this.searchTimer);
    this.query.set('');
    this.search.emit('');
  }

  protected isExpanded(name: SectionName): boolean {
    return this.expanded()[name];
  }

  protected toggleSection(name: SectionName): void {
    this.expanded.update((state) => ({ ...state, [name]: !state[name] }));
    saveExpanded(this.storage, this.expanded());
  }

  protected startRename(conversation: ConversationSummary): void {
    this.draftTitle.set(conversation.title);
    this.renaming.set(conversation.id);
    // Typing replaces the old title, as it does when renaming a file.
    afterNextRender(() => this.titleInput()?.nativeElement.select(), { injector: this.injector });
  }

  protected saveRename(event: Event, conversation: ConversationSummary): void {
    event.preventDefault();
    if (this.renaming() !== conversation.id) {
      return; // Already saved or cancelled; the input is going away.
    }
    const title = this.draftTitle().trim();
    if (title && title !== conversation.title) {
      this.rename.emit({ id: conversation.id, title });
    }
    this.renaming.set(null);
  }

  protected togglePin(conversation: ConversationSummary): void {
    this.pin.emit({ id: conversation.id, pinned: !conversation.pinned_at });
  }

  protected async askDelete(conversation: ConversationSummary): Promise<void> {
    const confirmed = await this.confirm.ask({
      title: 'Delete this conversation?',
      message: `"${conversation.title}" and every answer in it will be deleted. This cannot be undone.`,
      confirm: 'Delete',
      danger: true,
    });
    if (confirmed) {
      this.remove.emit(conversation.id);
    }
  }
}

function loadExpanded(storage: Storage | undefined): Expanded {
  const all: Expanded = { pinned: true, recents: true, all: true };
  try {
    const saved = JSON.parse(storage?.getItem(SECTIONS_KEY) ?? 'null');
    for (const name of Object.keys(all) as SectionName[]) {
      if (typeof saved?.[name] === 'boolean') {
        all[name] = saved[name];
      }
    }
  } catch {
    // Unreadable or blocked: every section starts open.
  }
  return all;
}

function saveExpanded(storage: Storage | undefined, expanded: Expanded): void {
  try {
    storage?.setItem(SECTIONS_KEY, JSON.stringify(expanded));
  } catch {
    // Storage is full or blocked. The sections simply are not remembered.
  }
}
