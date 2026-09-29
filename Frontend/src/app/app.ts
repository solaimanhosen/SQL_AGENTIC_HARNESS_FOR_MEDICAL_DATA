import {
  Component,
  ElementRef,
  OnInit,
  afterRenderEffect,
  inject,
  signal,
  viewChild,
} from '@angular/core';

import { AgentApi } from './api/agent-api';
import { Health } from './api/types';
import { ChatStore } from './chat/chat-store';
import { Composer } from './chat/composer';
import { ExchangeView } from './chat/exchange-view';
import { TokenPrompt } from './chat/token-prompt';

export const EXAMPLE_QUESTIONS = [
  'How many patients have diabetes?',
  'How many diabetic patients had an emergency visit in the last 12 months?',
  'Which age band has the most hospital visits?',
];

@Component({
  selector: 'app-root',
  imports: [Composer, ExchangeView, TokenPrompt],
  templateUrl: './app.html',
  styleUrl: './app.css',
})
export class App implements OnInit {
  protected readonly store = inject(ChatStore);
  private readonly api = inject(AgentApi);

  protected readonly examples = EXAMPLE_QUESTIONS;
  protected readonly health = signal<Health | 'checking' | 'unreachable'>('checking');
  private readonly end = viewChild<ElementRef<HTMLElement>>('end');

  constructor() {
    // Keep the newest step or answer in view as the conversation grows.
    afterRenderEffect(() => {
      this.store.exchanges();
      this.end()?.nativeElement.scrollIntoView?.({ block: 'end' });
    });
  }

  async ngOnInit(): Promise<void> {
    try {
      this.health.set(await this.api.health());
    } catch {
      this.health.set('unreachable');
    }
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
  }

  protected healthInfo(): Health | null {
    const health = this.health();
    return typeof health === 'string' ? null : health;
  }
}
