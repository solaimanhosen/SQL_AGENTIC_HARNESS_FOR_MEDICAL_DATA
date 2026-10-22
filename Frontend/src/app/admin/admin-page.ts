import { Component, computed, inject, input } from '@angular/core';
import { Router } from '@angular/router';
import {
  LucideActivity,
  LucideChartColumn,
  LucideGauge,
  LucideSettings,
  LucideUsers,
} from '@lucide/angular';

import { PageShell, PageTab } from '../ui/page-shell';
import { ChecksSection } from './checks-section';
import { MonitoringSection } from './monitoring-section';
import { OverviewSection } from './overview-section';
import { PeopleSection } from './people-section';
import { SettingsSection } from './settings-section';

export type AdminTab = 'overview' | 'checks' | 'monitoring' | 'people' | 'settings';
export const ADMIN_TABS: PageTab[] = [
  { id: 'overview', label: 'Overview', icon: LucideGauge },
  { id: 'checks', label: 'Checks', icon: LucideActivity },
  { id: 'monitoring', label: 'Monitoring', icon: LucideChartColumn },
  { id: 'people', label: 'People', icon: LucideUsers },
  { id: 'settings', label: 'Settings', icon: LucideSettings },
];

/** The admin console. Only admins reach it (adminGuard), and the service checks again. */
@Component({
  selector: 'app-admin-page',
  imports: [
    ChecksSection,
    MonitoringSection,
    OverviewSection,
    PageShell,
    PeopleSection,
    SettingsSection,
  ],
  template: `
    <app-page-shell heading="Admin console" [tabs]="tabs" [current]="current()">
      @switch (current()) {
        @case ('checks') {
          <app-checks-section />
        }
        @case ('monitoring') {
          <app-monitoring-section />
        }
        @case ('people') {
          <app-people-section />
        }
        @case ('settings') {
          <app-settings-section />
        }
        @default {
          <app-overview-section (openChecks)="go('checks')" />
        }
      }
    </app-page-shell>
  `,
})
export class AdminPage {
  private readonly router = inject(Router);
  readonly tab = input<string>();

  protected readonly tabs = ADMIN_TABS;
  protected readonly current = computed<AdminTab>(() => {
    const tab = this.tab();
    return ADMIN_TABS.some((item) => item.id === tab) ? (tab as AdminTab) : 'overview';
  });

  protected go(tab: AdminTab): void {
    void this.router.navigate([], { queryParams: { tab } });
  }
}
