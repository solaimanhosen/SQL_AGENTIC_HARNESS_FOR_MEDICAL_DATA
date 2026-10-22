import { Component, input } from '@angular/core';
import { RouterLink } from '@angular/router';
import { LucideArrowLeft, LucideDynamicIcon, LucideIconInput } from '@lucide/angular';

import { ProfileMenu } from './profile-menu';
import { ThemeToggle } from './theme-toggle';

export interface PageTab {
  id: string;
  label: string;
  icon: LucideIconInput;
}

/**
 * The frame of a settings-style page, such as the account page and the admin console: a
 * header with the way back to the chat, and a list of sections beside the content. Which
 * section is open is in the address, `?tab=`, so it survives a reload and can be linked.
 */
@Component({
  selector: 'app-page-shell',
  imports: [LucideArrowLeft, LucideDynamicIcon, ProfileMenu, RouterLink, ThemeToggle],
  template: `
    <header class="bar">
      <a class="back" routerLink="/">
        <svg lucideArrowLeft [size]="16"></svg>
        <span>Back to chat</span>
      </a>
      <h1>{{ heading() }}</h1>
      <div class="actions">
        <app-theme-toggle />
        <app-profile-menu />
      </div>
    </header>
    <div class="layout">
      <nav class="tabs" [attr.aria-label]="heading() + ' sections'">
        @for (item of tabs(); track item.id) {
          <a
            class="tab"
            [routerLink]="[]"
            [queryParams]="{ tab: item.id }"
            [attr.aria-current]="current() === item.id ? 'page' : null"
          >
            <svg [lucideIcon]="item.icon" [size]="16"></svg>
            <span>{{ item.label }}</span>
          </a>
        }
      </nav>
      <main class="content">
        <ng-content />
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
    .content {
      min-width: 0;
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
export class PageShell {
  readonly heading = input.required<string>();
  readonly tabs = input.required<PageTab[]>();
  readonly current = input.required<string>();
}
