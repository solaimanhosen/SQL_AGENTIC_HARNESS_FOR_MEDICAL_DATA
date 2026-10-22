import { CdkMenu, CdkMenuItem, CdkMenuTrigger } from '@angular/cdk/menu';
import { Component, computed, inject } from '@angular/core';
import { Router } from '@angular/router';
import { LucideLogOut, LucideSettings, LucideShieldCheck } from '@lucide/angular';

import { Auth } from '../auth/auth';

/** Up to two letters for the avatar: from the name, or the email when there is no name. */
export function initials(name: string, email: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  if (words.length) {
    return (words[0][0] + (words.length > 1 ? words[words.length - 1][0] : '')).toUpperCase();
  }
  return (email[0] ?? '?').toUpperCase();
}

/** The signed-in person's avatar, opening a menu with who they are and Sign out. */
@Component({
  selector: 'app-profile-menu',
  imports: [CdkMenu, CdkMenuItem, CdkMenuTrigger, LucideLogOut, LucideSettings, LucideShieldCheck],
  template: `
    @if (auth.user(); as user) {
      <button
        type="button"
        class="ghost icon avatar-button"
        [cdkMenuTriggerFor]="menu"
        [attr.aria-label]="'Account: ' + (user.name || user.email)"
        [title]="user.email"
      >
        <span class="avatar" aria-hidden="true">{{ letters() }}</span>
      </button>
      <ng-template #menu>
        <div class="menu profile" cdkMenu>
          <div class="who">
            <p class="name">{{ user.name || user.email }}</p>
            @if (user.name) {
              <p class="email">{{ user.email }}</p>
            }
            @if (user.role === 'admin') {
              <p class="role">
                <svg lucideShieldCheck [size]="12"></svg>
                <span>Administrator</span>
              </p>
            }
          </div>
          <div class="menu-separator" role="separator"></div>
          <button
            type="button"
            class="menu-item"
            cdkMenuItem
            (cdkMenuItemTriggered)="openAccount()"
          >
            <svg lucideSettings [size]="16"></svg>
            <span>Account settings</span>
          </button>
          @if (user.role === 'admin') {
            <button
              type="button"
              class="menu-item"
              cdkMenuItem
              (cdkMenuItemTriggered)="openAdmin()"
            >
              <svg lucideShieldCheck [size]="16"></svg>
              <span>Admin console</span>
            </button>
          }
          <button
            type="button"
            class="menu-item"
            cdkMenuItem
            (cdkMenuItemTriggered)="auth.logout()"
          >
            <svg lucideLogOut [size]="16"></svg>
            <span>Sign out</span>
          </button>
        </div>
      </ng-template>
    }
  `,
  styles: `
    .avatar-button {
      border-radius: var(--radius-full);
    }
    .avatar {
      display: grid;
      place-items: center;
      width: 1.75rem;
      height: 1.75rem;
      border-radius: var(--radius-full);
      background: var(--accent-soft);
      color: var(--accent);
      font-size: var(--text-xs);
      font-weight: var(--weight-semibold);
    }
    .profile {
      min-width: 14rem;
    }
    .who {
      padding: var(--space-2);
    }
    .who p {
      margin: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .name {
      font-weight: var(--weight-medium);
    }
    .email {
      color: var(--text-muted);
      font-size: var(--text-xs);
    }
    .role {
      display: flex;
      align-items: center;
      gap: var(--space-1);
      margin-top: var(--space-1) !important;
      color: var(--accent);
      font-size: var(--text-xs);
    }
  `,
})
export class ProfileMenu {
  protected readonly auth = inject(Auth);
  private readonly router = inject(Router);

  protected openAccount(): void {
    void this.router.navigate(['/account']);
  }

  protected openAdmin(): void {
    void this.router.navigate(['/admin']);
  }

  protected readonly letters = computed(() => {
    const user = this.auth.user();
    return user ? initials(user.name, user.email) : '';
  });
}
