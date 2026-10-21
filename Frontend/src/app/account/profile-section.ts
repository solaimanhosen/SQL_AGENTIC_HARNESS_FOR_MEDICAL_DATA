import { Component, computed, inject, signal } from '@angular/core';

import { AgentApi, ApiError } from '../api/agent-api';
import { Auth } from '../auth/auth';

/** Your name, and the email and role you cannot change here. */
@Component({
  selector: 'app-profile-section',
  template: `
    @if (auth.user(); as user) {
      <section class="settings-card" aria-labelledby="profile-title">
        <h2 id="profile-title">Profile</h2>
        <p class="settings-lead">How you appear in the application.</p>
        <form (submit)="save($event)">
          <div class="settings-row">
            <label for="profile-name">Name</label>
            <input
              id="profile-name"
              class="field"
              autocomplete="name"
              maxlength="100"
              [value]="name()"
              (input)="name.set($any($event.target).value)"
            />
          </div>
          <div class="settings-row">
            <label for="profile-email">Email</label>
            <input id="profile-email" class="field" [value]="user.email" readonly />
            <p class="settings-hint">
              Your email is how you sign in, so only an administrator can change it.
            </p>
          </div>
          <div class="settings-row">
            <span class="label">Role</span>
            <p class="role">{{ user.role === 'admin' ? 'Administrator' : 'User' }}</p>
          </div>
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
      </section>
    }
  `,
  styles: `
    .label {
      font-size: var(--text-sm);
      font-weight: var(--weight-medium);
    }
    .role {
      margin: 0;
      color: var(--text-muted);
    }
    input[readonly] {
      background: var(--surface-2);
      color: var(--text-muted);
    }
  `,
})
export class ProfileSection {
  protected readonly auth = inject(Auth);
  private readonly api = inject(AgentApi);

  protected readonly name = signal(this.auth.user()?.name ?? '');
  protected readonly busy = signal(false);
  protected readonly status = signal<string | null>(null);
  protected readonly failed = signal(false);
  protected readonly changed = computed(
    () => this.name().trim() !== (this.auth.user()?.name ?? ''),
  );

  protected async save(event: Event): Promise<void> {
    event.preventDefault();
    this.busy.set(true);
    try {
      this.auth.user.set(await this.api.updateAccount({ name: this.name().trim() }));
      this.name.set(this.auth.user()?.name ?? '');
      this.report('Saved.', false);
    } catch (error) {
      this.report(error instanceof ApiError ? error.message : 'It could not be saved.', true);
    } finally {
      this.busy.set(false);
    }
  }

  private report(text: string, failed: boolean): void {
    this.status.set(text);
    this.failed.set(failed);
  }
}
