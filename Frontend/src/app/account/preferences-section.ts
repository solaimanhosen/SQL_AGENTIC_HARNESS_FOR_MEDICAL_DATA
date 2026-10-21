import { Component, OnInit, computed, inject, signal } from '@angular/core';

import { AgentApi, ApiError } from '../api/agent-api';
import { Effort } from '../api/types';
import { Auth } from '../auth/auth';
import { ChatStore } from '../chat/chat-store';
import { EFFORT_LABELS, priceText } from '../chat/model-picker';
import { THEME_CHOICES, Theme, ThemeChoice } from '../ui/theme';

const THEME_LABELS: Record<ThemeChoice, string> = {
  system: 'System',
  light: 'Light',
  dark: 'Dark',
};

/**
 * Where a new chat starts, and the theme. The default model is kept with the account, so it
 * follows the person to any browser; the theme belongs to this browser.
 */
@Component({
  selector: 'app-preferences-section',
  template: `
    <section class="settings-card" aria-labelledby="model-title">
      <h2 id="model-title">Default model</h2>
      <p class="settings-lead">
        New chats start on this model and effort. You can still change them for any question.
      </p>
      @if (store.catalog(); as catalog) {
        <form (submit)="save($event)">
          <div class="settings-row">
            <label for="default-model">Model</label>
            <select
              id="default-model"
              class="field"
              [value]="model()"
              (change)="pickModel($any($event.target).value)"
            >
              <option value="">The service's default</option>
              @for (option of catalog.models; track option.id) {
                <option [value]="option.id" [selected]="option.id === model()">
                  {{ option.label }} · {{ price(option) }}
                </option>
              }
            </select>
          </div>
          @if (current(); as option) {
            <div class="settings-row">
              <label for="default-effort">Effort</label>
              <select
                id="default-effort"
                class="field"
                [value]="effort()"
                (change)="effort.set($any($event.target).value)"
              >
                @for (level of option.efforts; track level) {
                  <option [value]="level" [selected]="level === effort()">
                    {{ effortLabels[level] }}
                  </option>
                }
              </select>
              <p class="settings-hint">{{ option.description }}</p>
            </div>
          }
          <div class="settings-actions">
            <button type="submit" [disabled]="!changed() || busy()">Save</button>
            @if (status(); as text) {
              <p
                class="settings-status"
                [class.ok]="!failed()"
                [class.error]="failed()"
                role="status"
              >
                {{ text }}
              </p>
            }
          </div>
        </form>
      } @else {
        <p class="settings-hint">The models on offer could not be loaded.</p>
      }
    </section>

    <section class="settings-card" aria-labelledby="theme-title">
      <h2 id="theme-title">Theme</h2>
      <p class="settings-lead">Kept in this browser.</p>
      <div class="themes" role="radiogroup" aria-labelledby="theme-title">
        @for (choice of themes; track choice) {
          <label class="theme" [class.on]="theme.choice() === choice">
            <input
              type="radio"
              name="theme"
              [value]="choice"
              [checked]="theme.choice() === choice"
              (change)="theme.set(choice)"
            />
            <span class="swatch {{ choice }}" aria-hidden="true"></span>
            <span>{{ themeLabels[choice] }}</span>
          </label>
        }
      </div>
    </section>
  `,
  styles: `
    select.field {
      appearance: auto;
    }
    .themes {
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-3);
    }
    .theme {
      display: grid;
      justify-items: center;
      gap: var(--space-2);
      padding: var(--space-3);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      font-size: var(--text-sm);
      cursor: pointer;
    }
    .theme.on {
      border-color: var(--accent);
      box-shadow: 0 0 0 1px var(--accent);
    }
    .theme input {
      position: absolute;
      opacity: 0;
      pointer-events: none;
    }
    .theme:focus-within {
      outline: 2px solid var(--focus-ring);
      outline-offset: 2px;
    }
    .swatch {
      width: 5rem;
      height: 3rem;
      border: 1px solid var(--border-strong);
      border-radius: var(--radius-sm);
    }
    .swatch.light {
      background: linear-gradient(135deg, #ffffff 50%, #f4f4f5 50%);
    }
    .swatch.dark {
      background: linear-gradient(135deg, #18181b 50%, #111113 50%);
    }
    .swatch.system {
      background: linear-gradient(135deg, #ffffff 50%, #18181b 50%);
    }
  `,
})
export class PreferencesSection implements OnInit {
  protected readonly store = inject(ChatStore);
  protected readonly theme = inject(Theme);
  private readonly auth = inject(Auth);
  private readonly api = inject(AgentApi);

  protected readonly themes = THEME_CHOICES;
  protected readonly themeLabels = THEME_LABELS;
  protected readonly effortLabels = EFFORT_LABELS;
  protected readonly price = priceText;

  protected readonly model = signal(this.auth.user()?.default_model ?? '');
  protected readonly effort = signal<Effort>(this.auth.user()?.default_effort ?? 'high');
  protected readonly busy = signal(false);
  protected readonly status = signal<string | null>(null);
  protected readonly failed = signal(false);

  protected readonly current = computed(
    () => this.store.catalog()?.models.find((option) => option.id === this.model()) ?? null,
  );
  protected readonly changed = computed(() => {
    const user = this.auth.user();
    return (
      this.model() !== (user?.default_model ?? '') ||
      (this.model() !== '' && this.effort() !== (user?.default_effort ?? null))
    );
  });

  ngOnInit(): void {
    if (!this.store.catalog()) {
      void this.store.loadModels();
    }
  }

  /** A new model keeps the effort if it offers it, and otherwise takes its own default. */
  protected pickModel(id: string): void {
    this.model.set(id);
    const option = this.store.catalog()?.models.find((item) => item.id === id);
    if (option && !option.efforts.includes(this.effort())) {
      this.effort.set(option.default_effort);
    }
  }

  protected async save(event: Event): Promise<void> {
    event.preventDefault();
    this.busy.set(true);
    try {
      const model = this.model() || null;
      const user = await this.api.updateAccount(
        model ? { default_model: model, default_effort: this.effort() } : { default_model: null },
      );
      this.auth.user.set(user);
      // New chats start on the new default from now on.
      await this.store.loadModels({ reset: this.store.exchanges().length === 0 });
      this.status.set('Saved. New chats start on this model.');
      this.failed.set(false);
    } catch (error) {
      this.status.set(error instanceof ApiError ? error.message : 'It could not be saved.');
      this.failed.set(true);
    } finally {
      this.busy.set(false);
    }
  }
}
