import { CdkMenu, CdkMenuItemRadio, CdkMenuTrigger } from '@angular/cdk/menu';
import { Component, computed, inject } from '@angular/core';
import { LucideCheck, LucideMonitor, LucideMoon, LucideSun } from '@lucide/angular';

import { THEME_CHOICES, Theme, ThemeChoice } from './theme';

const LABELS: Record<ThemeChoice, string> = {
  system: 'System',
  light: 'Light',
  dark: 'Dark',
};

/** The header's theme button: a menu of System, Light and Dark. */
@Component({
  selector: 'app-theme-toggle',
  imports: [
    CdkMenu,
    CdkMenuItemRadio,
    CdkMenuTrigger,
    LucideCheck,
    LucideMonitor,
    LucideMoon,
    LucideSun,
  ],
  template: `
    <button
      type="button"
      class="ghost icon"
      [cdkMenuTriggerFor]="menu"
      [attr.aria-label]="'Theme: ' + label()"
      [title]="'Theme: ' + label()"
    >
      @switch (theme.choice()) {
        @case ('light') {
          <svg lucideSun [size]="18"></svg>
        }
        @case ('dark') {
          <svg lucideMoon [size]="18"></svg>
        }
        @default {
          <svg lucideMonitor [size]="18"></svg>
        }
      }
    </button>
    <ng-template #menu>
      <div class="menu" cdkMenu aria-label="Theme">
        <p class="menu-label" aria-hidden="true">Theme</p>
        @for (choice of choices; track choice) {
          <button
            type="button"
            class="menu-item"
            cdkMenuItemRadio
            [cdkMenuItemChecked]="theme.choice() === choice"
            (cdkMenuItemTriggered)="theme.set(choice)"
          >
            @switch (choice) {
              @case ('light') {
                <svg lucideSun [size]="16"></svg>
              }
              @case ('dark') {
                <svg lucideMoon [size]="16"></svg>
              }
              @default {
                <svg lucideMonitor [size]="16"></svg>
              }
            }
            <span>{{ labels[choice] }}</span>
            @if (theme.choice() === choice) {
              <svg lucideCheck class="check" [size]="16"></svg>
            }
          </button>
        }
      </div>
    </ng-template>
  `,
})
export class ThemeToggle {
  protected readonly theme = inject(Theme);
  protected readonly choices = THEME_CHOICES;
  protected readonly labels = LABELS;
  protected readonly label = computed(() => LABELS[this.theme.choice()]);
}
