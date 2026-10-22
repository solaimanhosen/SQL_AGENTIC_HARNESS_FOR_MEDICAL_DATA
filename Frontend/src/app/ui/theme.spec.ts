import { TestBed } from '@angular/core/testing';

import { THEME_KEY, Theme, loadTheme } from './theme';
import { ThemeToggle } from './theme-toggle';

describe('Theme', () => {
  const root = document.documentElement;
  beforeEach(() => {
    localStorage.removeItem(THEME_KEY);
    root.removeAttribute('data-theme');
  });
  afterEach(() => {
    localStorage.removeItem(THEME_KEY);
    root.removeAttribute('data-theme');
  });

  it('follows the system until a theme is chosen, and leaves no attribute for it', () => {
    const theme = TestBed.inject(Theme);
    TestBed.tick();
    expect(theme.choice()).toBe('system');
    expect(root.hasAttribute('data-theme')).toBe(false);
  });

  it('applies a chosen theme to the page and remembers it', () => {
    const theme = TestBed.inject(Theme);
    theme.set('dark');
    TestBed.tick();
    expect(root.getAttribute('data-theme')).toBe('dark');
    expect(localStorage.getItem(THEME_KEY)).toBe('dark');

    theme.set('system');
    TestBed.tick();
    expect(root.hasAttribute('data-theme')).toBe(false);
    expect(localStorage.getItem(THEME_KEY)).toBeNull();
  });

  it('reads back only the values it writes', () => {
    localStorage.setItem(THEME_KEY, 'light');
    expect(loadTheme(localStorage)).toBe('light');
    localStorage.setItem(THEME_KEY, '<script>');
    expect(loadTheme(localStorage)).toBe('system');
    expect(loadTheme(undefined)).toBe('system');
  });

  it('falls back to the system theme when storage throws', () => {
    const blocked = {
      getItem: () => {
        throw new Error('blocked');
      },
    } as unknown as Storage;
    expect(loadTheme(blocked)).toBe('system');
  });
});

describe('ThemeToggle', () => {
  afterEach(() => {
    localStorage.removeItem(THEME_KEY);
    root().removeAttribute('data-theme');
  });
  const root = () => document.documentElement;

  it('opens a menu of the three themes and applies the one picked', async () => {
    const fixture = TestBed.createComponent(ThemeToggle);
    await fixture.whenStable();
    const trigger = fixture.nativeElement.querySelector('button') as HTMLButtonElement;
    expect(trigger.getAttribute('aria-label')).toBe('Theme: System');

    trigger.click();
    await fixture.whenStable();
    const items = [...document.querySelectorAll<HTMLButtonElement>('.menu .menu-item')];
    expect(items.map((item) => item.textContent?.trim())).toEqual(['System', 'Light', 'Dark']);
    expect(items[0].getAttribute('aria-checked')).toBe('true');

    items[2].click();
    await fixture.whenStable();
    expect(root().getAttribute('data-theme')).toBe('dark');
    expect(trigger.getAttribute('aria-label')).toBe('Theme: Dark');
  });
});
