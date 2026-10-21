import {
  Component,
  ElementRef,
  Injector,
  afterNextRender,
  inject,
  input,
  output,
  signal,
  viewChild,
} from '@angular/core';

import { ConversationSummary } from '../api/types';

export const MAX_TITLE_CHARS = 100;

/**
 * The list of stored conversations, most recently used first, with a button to start a new
 * one. Titles come from what users typed, so they are rendered as text like everything else.
 */
@Component({
  selector: 'app-sidebar',
  templateUrl: './sidebar.html',
  styleUrl: './sidebar.css',
})
export class Sidebar {
  readonly conversations = input.required<ConversationSummary[]>();
  readonly activeId = input<string | null>(null);
  /** True while a question is being answered, when switching away would lose its place. */
  readonly busy = input(false);

  readonly newChat = output<void>();
  readonly open = output<string>();
  readonly rename = output<{ id: string; title: string }>();
  readonly remove = output<string>();
  /** Hide the sidebar. On a phone this closes the drawer. */
  readonly collapse = output<void>();

  protected readonly max = MAX_TITLE_CHARS;
  protected readonly renaming = signal<string | null>(null);
  protected readonly deleting = signal<string | null>(null);
  protected readonly draftTitle = signal('');
  private readonly titleInput = viewChild<ElementRef<HTMLInputElement>>('titleInput');
  private readonly injector = inject(Injector);

  protected startRename(conversation: ConversationSummary): void {
    this.deleting.set(null);
    this.draftTitle.set(conversation.title);
    this.renaming.set(conversation.id);
    // Typing replaces the old title, as it does when renaming a file.
    afterNextRender(() => this.titleInput()?.nativeElement.select(), { injector: this.injector });
  }

  protected saveRename(event: Event, conversation: ConversationSummary): void {
    event.preventDefault();
    const title = this.draftTitle().trim();
    if (title && title !== conversation.title) {
      this.rename.emit({ id: conversation.id, title });
    }
    this.renaming.set(null);
  }

  protected askDelete(id: string): void {
    this.renaming.set(null);
    this.deleting.set(id);
  }

  protected confirmDelete(id: string): void {
    this.deleting.set(null);
    this.remove.emit(id);
  }
}
