import { Component, computed, input } from '@angular/core';
import { RouterLink } from '@angular/router';
import {
  LucideArrowLeft,
  LucideChartColumn,
  LucideShieldCheck,
  LucideSlidersHorizontal,
  LucideUser,
} from '@lucide/angular';

import { ProfileMenu } from '../ui/profile-menu';
import { ThemeToggle } from '../ui/theme-toggle';
import { PreferencesSection } from './preferences-section';
import { ProfileSection } from './profile-section';
import { SecuritySection } from './security-section';
import { UsageSection } from './usage-section';

export type AccountTab = 'profile' | 'security' | 'preferences' | 'usage';
export const ACCOUNT_TABS: { id: AccountTab; label: string }[] = [
  { id: 'profile', label: 'Profile' },
  { id: 'security', label: 'Security' },
  { id: 'preferences', label: 'Preferences' },
  { id: 'usage', label: 'Usage' },
];

/** Account settings, one section at a time. The section is in the address, `?tab=`. */
@Component({
  selector: 'app-account-page',
  imports: [
    LucideArrowLeft,
    LucideChartColumn,
    LucideShieldCheck,
    LucideSlidersHorizontal,
    LucideUser,
    PreferencesSection,
    ProfileMenu,
    ProfileSection,
    RouterLink,
    SecuritySection,
    ThemeToggle,
    UsageSection,
  ],
  template: `
    <header class="bar">
      <a class="back" routerLink="/">
        <svg lucideArrowLeft [size]="16"></svg>
        <span>Back to chat</span>
      </a>
      <h1>Account</h1>
      <div class="actions">
        <app-theme-toggle />
        <app-profile-menu />
      </div>
    </header>
    <div class="layout">
      <nav class="tabs" aria-label="Account sections">
        @for (item of tabs; track item.id) {
          <a
            class="tab"
            [routerLink]="[]"
            [queryParams]="{ tab: item.id }"
            [attr.aria-current]="current() === item.id ? 'page' : null"
          >
            @switch (item.id) {
              @case ('profile') {
                <svg lucideUser [size]="16"></svg>
              }
              @case ('security') {
                <svg lucideShieldCheck [size]="16"></svg>
              }
              @case ('preferences') {
                <svg lucideSlidersHorizontal [size]="16"></svg>
              }
              @default {
                <svg lucideChartColumn [size]="16"></svg>
              }
            }
            <span>{{ item.label }}</span>
          </a>
        }
      </nav>
      <main class="content">
        @switch (current()) {
          @case ('security') {
            <app-security-section [error]="error() ?? null" />
          }
          @case ('preferences') {
            <app-preferences-section />
          }
          @case ('usage') {
            <app-usage-section />
          }
          @default {
            <app-profile-section />
          }
        }
      </main>
    </div>
  `,
  styles: `
    :host {
      display: block;
      min-height: 100dvh;
    }
    .bar {
      position: sticky;
      top: 0;
      z-index: var(--z-sticky);
      display: flex;
      align-items: center;
      gap: var(--space-4);
      min-height: var(--header-height);
      padding: var(--space-2) var(--space-4);
      border-bottom: 1px solid var(--border);
      background: color-mix(in srgb, var(--bg) 88%, transparent);
      backdrop-filter: saturate(1.4) blur(8px);
    }
    .back {
      display: inline-flex;
      align-items: center;
      gap: var(--space-1-5);
      color: var(--text-muted);
      font-size: var(--text-sm);
      text-decoration: none;
    }
    .back:hover {
      color: var(--text);
    }
    h1 {
      flex: 1;
      margin: 0;
      font-size: var(--text-md);
    }
    .actions {
      display: flex;
      align-items: center;
      gap: var(--space-1);
    }
    .layout {
      display: grid;
      grid-template-columns: 12rem minmax(0, 1fr);
      gap: var(--space-8);
      width: 100%;
      max-width: calc(var(--content-max) + 2 * var(--space-4));
      margin: 0 auto;
      padding: var(--space-8) var(--space-4);
    }
    .tabs {
      display: grid;
      align-content: start;
      gap: var(--space-0-5);
    }
    .tab {
      display: flex;
      align-items: center;
      gap: var(--space-2);
      min-height: 2.25rem;
      padding: 0 var(--space-3);
      border-radius: var(--radius-md);
      color: var(--text-muted);
      font-size: var(--text-sm);
      text-decoration: none;
    }
    .tab:hover {
      background: var(--surface-hover);
      color: var(--text);
    }
    .tab[aria-current='page'] {
      background: var(--chip);
      color: var(--text);
      font-weight: var(--weight-medium);
    }
    @media (max-width: 48rem) {
      .back span {
        display: none;
      }
      .layout {
        grid-template-columns: minmax(0, 1fr);
        gap: var(--space-4);
        padding-top: var(--space-4);
      }
      .tabs {
        display: flex;
        overflow-x: auto;
      }
      .tab {
        flex: none;
      }
    }
  `,
})
export class AccountPage {
  /** From the address: which section, and a code from connecting Google. */
  readonly tab = input<string>();
  readonly error = input<string>();

  protected readonly tabs = ACCOUNT_TABS;
  protected readonly current = computed<AccountTab>(() => {
    const tab = this.tab();
    return ACCOUNT_TABS.some((item) => item.id === tab) ? (tab as AccountTab) : 'profile';
  });
}
