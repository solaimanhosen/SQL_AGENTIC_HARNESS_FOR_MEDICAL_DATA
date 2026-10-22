import { CdkMenu, CdkMenuItem, CdkMenuTrigger } from '@angular/cdk/menu';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { LucideEllipsis } from '@lucide/angular';

import { ApiError } from '../api/agent-api';
import { AdminUser } from '../api/admin-types';
import { formatDay, formatWhen } from '../account/describe-agent';
import { Auth } from '../auth/auth';
import { Confirm } from '../ui/confirm-dialog';
import { AdminApi } from './admin-api';
import { count } from './format';

/**
 * Every account: who they are, how they sign in, how much they use the service, and what an
 * admin can change. An admin cannot change their own role or disable themselves here.
 */
@Component({
  selector: 'app-people-section',
  imports: [CdkMenu, CdkMenuItem, CdkMenuTrigger, LucideEllipsis],
  template: `
    @if (problem(); as text) {
      <p class="settings-status error" role="alert">{{ text }}</p>
    }
    @if (revealed(); as reveal) {
      <section class="settings-card reveal" aria-labelledby="reveal-title" role="status">
        <h2 id="reveal-title">Temporary password for {{ reveal.email }}</h2>
        <p class="settings-lead">
          Shown only now. Give it to them another way; they should change it in Account settings.
          Every session of theirs has ended.
        </p>
        <div class="settings-actions">
          <code class="secret">{{ reveal.password }}</code>
          <button type="button" class="secondary" (click)="copy(reveal.password)">
            {{ copied() ? 'Copied' : 'Copy' }}
          </button>
          <button type="button" class="ghost" (click)="revealed.set(null)">Done</button>
        </div>
      </section>
    }

    <section class="settings-card" aria-labelledby="people-title">
      <div class="head">
        <div>
          <h2 id="people-title">People</h2>
          <p class="settings-lead">
            {{ users().length }} accounts. Admins see accounts and totals, never anyone's questions.
          </p>
        </div>
        <label class="visually-hidden" for="people-search">Find a person</label>
        <input
          id="people-search"
          class="field search"
          placeholder="Find by name or email"
          [value]="query()"
          (input)="query.set($any($event.target).value)"
        />
      </div>
      <div class="data-table">
        <table>
          <thead>
            <tr>
              <th scope="col">Person</th>
              <th scope="col">Role</th>
              <th scope="col">Status</th>
              <th scope="col" class="num">Chats</th>
              <th scope="col" class="num" title="Questions asked this month">This month</th>
              <th scope="col">Last seen</th>
              <th scope="col"><span class="visually-hidden">Actions</span></th>
            </tr>
          </thead>
          <tbody>
            @for (person of shown(); track person.id) {
              <tr [class.off]="person.disabled">
                <td class="person">
                  <span class="name">{{ person.name || person.email }}</span>
                  @if (person.name) {
                    <span class="email">{{ person.email }}</span>
                  }
                  <span class="email">Signs in with {{ methods(person).toLowerCase() }}</span>
                </td>
                <td>
                  <span class="state" [class.busy]="person.role === 'admin'">{{
                    person.role === 'admin' ? 'Admin' : 'User'
                  }}</span>
                </td>
                <td>
                  <span
                    class="state"
                    [class.good]="!person.disabled"
                    [class.bad]="person.disabled"
                    >{{ person.disabled ? 'Disabled' : 'Active' }}</span
                  >
                </td>
                <td class="num">{{ count(person.conversations) }}</td>
                <td class="num">{{ count(person.questions_this_month) }}</td>
                <td [title]="person.last_seen_at ? when(person.last_seen_at) : ''">
                  {{ person.last_seen_at ? day(person.last_seen_at) : 'Never' }}
                </td>
                <td>
                  <button
                    type="button"
                    class="ghost icon sm"
                    [attr.aria-label]="'Actions for ' + person.email"
                    [cdkMenuTriggerFor]="actions"
                    [cdkMenuTriggerData]="{ $implicit: person }"
                  >
                    <svg lucideEllipsis [size]="16"></svg>
                  </button>
                </td>
              </tr>
            } @empty {
              <tr>
                <td colspan="7" class="none">No one matches "{{ query() }}".</td>
              </tr>
            }
          </tbody>
        </table>
      </div>
    </section>

    <ng-template #actions let-person>
      <div class="menu" cdkMenu>
        @if (person.id === auth.user()?.id) {
          <p class="menu-label">This is you. Your own role and access cannot be changed here.</p>
        } @else {
          <button
            type="button"
            class="menu-item"
            cdkMenuItem
            (cdkMenuItemTriggered)="setRole(person)"
          >
            {{ person.role === 'admin' ? 'Make a user' : 'Make an admin' }}
          </button>
          <button
            type="button"
            class="menu-item"
            [class.destructive]="!person.disabled"
            cdkMenuItem
            (cdkMenuItemTriggered)="toggleDisabled(person)"
          >
            {{ person.disabled ? 'Enable' : 'Disable' }}
          </button>
        }
        <div class="menu-separator" role="separator"></div>
        <button
          type="button"
          class="menu-item"
          cdkMenuItem
          (cdkMenuItemTriggered)="resetPassword(person)"
        >
          Set a temporary password
        </button>
      </div>
    </ng-template>
  `,
  styles: `
    .head {
      display: flex;
      flex-wrap: wrap;
      align-items: flex-start;
      justify-content: space-between;
      gap: var(--space-3);
    }
    .search {
      width: min(18rem, 100%);
      min-height: 2rem;
      font-size: var(--text-sm);
    }
    .person {
      min-width: 14rem;
      white-space: normal;
      overflow-wrap: break-word;
    }
    .name {
      display: block;
      font-weight: var(--weight-medium);
    }
    .email {
      display: block;
      color: var(--text-subtle);
      font-size: var(--text-xs);
    }
    tr.off td {
      color: var(--text-subtle);
    }
    .none {
      color: var(--text-subtle);
      text-align: center;
    }
    .reveal {
      margin-bottom: var(--space-5);
      border-color: var(--accent);
    }
    .secret {
      padding: var(--space-1-5) var(--space-3);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      background: var(--code-bg);
      font-size: var(--text-md);
      user-select: all;
    }
    .menu-label {
      max-width: 16rem;
      white-space: normal;
    }
  `,
})
export class PeopleSection implements OnInit {
  private readonly admin = inject(AdminApi);
  private readonly confirm = inject(Confirm);
  protected readonly auth = inject(Auth);

  protected readonly users = signal<AdminUser[]>([]);
  protected readonly query = signal('');
  protected readonly problem = signal<string | null>(null);
  protected readonly revealed = signal<{ email: string; password: string } | null>(null);
  protected readonly copied = signal(false);
  protected readonly count = count;
  protected readonly when = formatWhen;
  protected readonly day = formatDay;

  protected readonly shown = computed(() => {
    const text = this.query().trim().toLowerCase();
    return text
      ? this.users().filter((person) =>
          `${person.name} ${person.email}`.toLowerCase().includes(text),
        )
      : this.users();
  });

  ngOnInit(): void {
    void this.load();
  }

  protected methods(person: AdminUser): string {
    const ways = [person.has_password && 'Password', person.google_linked && 'Google'].filter(
      Boolean,
    );
    return ways.length ? ways.join(', ') : 'No sign-in';
  }

  protected async setRole(person: AdminUser): Promise<void> {
    const role = person.role === 'admin' ? 'user' : 'admin';
    const confirmed = await this.confirm.ask({
      title: role === 'admin' ? 'Make an admin?' : 'Make a user?',
      message:
        role === 'admin'
          ? `${person.email} will be able to run checks, see usage, and manage every account.`
          : `${person.email} will no longer reach the admin console.`,
      confirm: role === 'admin' ? 'Make admin' : 'Make user',
    });
    if (confirmed) {
      await this.change(person, { role });
    }
  }

  protected async toggleDisabled(person: AdminUser): Promise<void> {
    if (!person.disabled) {
      const confirmed = await this.confirm.ask({
        title: 'Disable this account?',
        message: `${person.email} will be signed out everywhere and cannot sign in until enabled again. Their conversations are kept.`,
        confirm: 'Disable',
        danger: true,
      });
      if (!confirmed) {
        return;
      }
    }
    await this.change(person, { disabled: !person.disabled });
  }

  protected async resetPassword(person: AdminUser): Promise<void> {
    const confirmed = await this.confirm.ask({
      title: 'Set a temporary password?',
      message: `${person.email}'s current password stops working, and every session of theirs ends. You will see the new one once.`,
      confirm: 'Set password',
    });
    if (!confirmed) {
      return;
    }
    try {
      const { temporary_password } = await this.admin.resetPassword(person.id);
      this.copied.set(false);
      this.revealed.set({ email: person.email, password: temporary_password });
      await this.load();
    } catch (error) {
      this.problem.set(error instanceof ApiError ? error.message : 'It could not be done.');
    }
  }

  protected async copy(text: string): Promise<void> {
    try {
      await navigator.clipboard.writeText(text);
      this.copied.set(true);
    } catch {
      // Clipboard blocked: the password is selectable in the page.
    }
  }

  private async change(
    person: AdminUser,
    changes: { role?: 'user' | 'admin'; disabled?: boolean },
  ): Promise<void> {
    this.problem.set(null);
    try {
      await this.admin.changeUser(person.id, changes);
      await this.load();
    } catch (error) {
      this.problem.set(error instanceof ApiError ? error.message : 'It could not be changed.');
    }
  }

  private async load(): Promise<void> {
    try {
      this.users.set(await this.admin.users());
    } catch {
      this.problem.set('The accounts could not be loaded.');
    }
  }
}
