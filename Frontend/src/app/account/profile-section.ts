import { Component, OnInit, computed, inject, signal } from '@angular/core';

import { AgentApi, ApiError } from '../api/agent-api';
import { Auth } from '../auth/auth';

/**
 * Your name, and the email and role you cannot change here. An email not yet confirmed shows
 * a reminder with a button to send the link again, when the service can send email.
 */
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
            @if (!user.email_verified && emailEnabled()) {
              <div class="unverified">
                <p>
                  Your email is not confirmed yet. Confirming it lets you sign in with Google as
                  this address.
                </p>
                <button
                  type="button"
                  class="secondary"
                  [disabled]="sending()"
                  (click)="sendConfirmation()"
                >
                  {{ sending() ? 'Sending…' : 'Send confirmation email' }}
                </button>
                @if (sendStatus(); as text) {
                  <p
                    class="settings-status"
                    [class.ok]="!sendFailed()"
                    [class.error]="sendFailed()"
                    role="status"
                  >
                    {{ text }}
                  </p>
                }
              </div>
            }
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
    .unverified {
      display: grid;
      justify-items: start;
      gap: var(--space-2);
      margin-top: var(--space-2);
      padding: var(--space-3);
      border-radius: var(--radius-md);
      background: var(--warning-bg);
      color: var(--warning-text);
      font-size: var(--text-sm);
    }
    .unverified p {
      margin: 0;
    }
  `,
})
export class ProfileSection implements OnInit {
  protected readonly auth = inject(Auth);
  private readonly api = inject(AgentApi);

  protected readonly emailEnabled = computed(() => this.auth.config()?.email_enabled ?? false);
  protected readonly sending = signal(false);
  protected readonly sendStatus = signal<string | null>(null);
  protected readonly sendFailed = signal(false);

  protected readonly name = signal(this.auth.user()?.name ?? '');
  protected readonly busy = signal(false);
  protected readonly status = signal<string | null>(null);
  protected readonly failed = signal(false);
  protected readonly changed = computed(
    () => this.name().trim() !== (this.auth.user()?.name ?? ''),
  );

  ngOnInit(): void {
    void this.auth.loadConfig();
  }

  protected async sendConfirmation(): Promise<void> {
    this.sending.set(true);
    try {
      await this.api.sendVerification();
      this.sendStatus.set(`Sent to ${this.auth.user()?.email}. The link works for 3 days.`);
      this.sendFailed.set(false);
    } catch (error) {
      this.sendStatus.set(error instanceof ApiError ? error.message : 'It could not be sent.');
      this.sendFailed.set(true);
    } finally {
      this.sending.set(false);
    }
  }

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
