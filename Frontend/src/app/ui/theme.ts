import { DOCUMENT } from '@angular/common';
import { Injectable, effect, inject, signal } from '@angular/core';

export type ThemeChoice = 'system' | 'light' | 'dark';

export const THEME_CHOICES: readonly ThemeChoice[] = ['system', 'light', 'dark'];

/** Also read by the script in index.html, which applies the theme before the app starts. */
export const THEME_KEY = 'sql-agent.theme';

/**
 * The colour theme. "system" follows the operating system, through the media query in
 * styles.css; the other two set data-theme on <html>. The choice is a convenience kept in this
 * browser only, so storage that is missing or blocked just means the system theme.
 */
@Injectable({ providedIn: 'root' })
export class Theme {
  private readonly document = inject(DOCUMENT);
  private readonly storage = storageOf(this.document.defaultView);

  readonly choice = signal<ThemeChoice>(loadTheme(this.storage));

  constructor() {
    effect(() => {
      const choice = this.choice();
      const root = this.document.documentElement;
      if (choice === 'system') {
        root.removeAttribute('data-theme');
      } else {
        root.setAttribute('data-theme', choice);
      }
      saveTheme(this.storage, choice);
    });
  }

  set(choice: ThemeChoice): void {
    this.choice.set(choice);
  }
}

export function loadTheme(storage: Storage | undefined): ThemeChoice {
  try {
    const saved = storage?.getItem(THEME_KEY);
    return saved === 'light' || saved === 'dark' ? saved : 'system';
  } catch {
    return 'system';
  }
}

function saveTheme(storage: Storage | undefined, choice: ThemeChoice): void {
  try {
    if (choice === 'system') {
      storage?.removeItem(THEME_KEY);
    } else {
      storage?.setItem(THEME_KEY, choice);
    }
  } catch {
    // Storage is full or blocked. The theme lasts until the page is closed.
  }
}

export function storageOf(window: Window | null): Storage | undefined {
  try {
    return window?.localStorage;
  } catch {
    return undefined; // Reading it can throw when site data is blocked.
  }
}
