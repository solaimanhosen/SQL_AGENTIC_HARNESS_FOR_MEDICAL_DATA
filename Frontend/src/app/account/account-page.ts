import { Component, computed, input } from '@angular/core';
import {
  LucideChartColumn,
  LucideShieldCheck,
  LucideSlidersHorizontal,
  LucideUser,
} from '@lucide/angular';

import { PageShell, PageTab } from '../ui/page-shell';
import { PreferencesSection } from './preferences-section';
import { ProfileSection } from './profile-section';
import { SecuritySection } from './security-section';
import { UsageSection } from './usage-section';

export type AccountTab = 'profile' | 'security' | 'preferences' | 'usage';
export const ACCOUNT_TABS: PageTab[] = [
  { id: 'profile', label: 'Profile', icon: LucideUser },
  { id: 'security', label: 'Security', icon: LucideShieldCheck },
  { id: 'preferences', label: 'Preferences', icon: LucideSlidersHorizontal },
  { id: 'usage', label: 'Usage', icon: LucideChartColumn },
];

/** Account settings, one section at a time. The section is in the address, `?tab=`. */
@Component({
  selector: 'app-account-page',
  imports: [PageShell, PreferencesSection, ProfileSection, SecuritySection, UsageSection],
  template: `
    <app-page-shell heading="Account" [tabs]="tabs" [current]="current()">
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
    </app-page-shell>
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
