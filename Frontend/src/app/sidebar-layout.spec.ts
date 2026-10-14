import {
  SIDEBAR_DEFAULT,
  SIDEBAR_MAX,
  SIDEBAR_MIN,
  clampWidth,
  loadLayout,
  maxWidth,
  saveLayout,
} from './sidebar-layout';

function memoryStorage(initial: Record<string, string> = {}): Storage {
  const items = new Map(Object.entries(initial));
  return {
    getItem: (key: string) => items.get(key) ?? null,
    setItem: (key: string, value: string) => void items.set(key, value),
    removeItem: (key: string) => void items.delete(key),
    clear: () => items.clear(),
    key: () => null,
    get length() {
      return items.size;
    },
  };
}

describe('sidebar layout', () => {
  it('keeps the width between the narrowest and half the window, up to a cap', () => {
    expect(clampWidth(50, 1600)).toBe(SIDEBAR_MIN);
    expect(clampWidth(320.4, 1600)).toBe(320);
    expect(clampWidth(2000, 1600)).toBe(SIDEBAR_MAX);
    expect(maxWidth(700)).toBe(350);
    expect(maxWidth(300)).toBe(SIDEBAR_MIN);
  });

  it('remembers the width and whether it was collapsed', () => {
    const storage = memoryStorage();
    expect(loadLayout(storage)).toEqual({ width: SIDEBAR_DEFAULT, collapsed: false });
    saveLayout(storage, { width: 340, collapsed: true });
    expect(loadLayout(storage)).toEqual({ width: 340, collapsed: true });
  });

  it('falls back to the defaults when storage is missing, blocked or holds nonsense', () => {
    const defaults = { width: SIDEBAR_DEFAULT, collapsed: false };
    expect(loadLayout(undefined)).toEqual(defaults);
    expect(loadLayout(memoryStorage({ 'sql-agent.sidebar': '{not json' }))).toEqual(defaults);
    expect(loadLayout(memoryStorage({ 'sql-agent.sidebar': '{"width":"wide"}' }))).toEqual(
      defaults,
    );
    const blocked = memoryStorage();
    blocked.getItem = () => {
      throw new Error('blocked');
    };
    blocked.setItem = blocked.getItem;
    expect(loadLayout(blocked)).toEqual(defaults);
    expect(() => saveLayout(blocked, defaults)).not.toThrow();
  });
});
