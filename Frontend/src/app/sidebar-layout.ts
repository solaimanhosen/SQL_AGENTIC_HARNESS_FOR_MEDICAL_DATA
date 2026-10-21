/** The sidebar's width in pixels: where it starts, and how far it may be dragged. */
export const SIDEBAR_DEFAULT = 272;
export const SIDEBAR_MIN = 200;
export const SIDEBAR_MAX = 480;
/** Never wider than this share of the window, so the chat always keeps most of it. */
export const SIDEBAR_MAX_SHARE = 0.5;
/** How far one arrow key press moves the edge. */
export const SIDEBAR_STEP = 16;
/** Below this width the sidebar is a drawer over the page, as in app.css. */
export const NARROW_QUERY = '(max-width: 48rem)';

const STORAGE_KEY = 'sql-agent.sidebar';

export interface SidebarLayout {
  width: number;
  collapsed: boolean;
}

/** The widest the sidebar may be in a window this wide. */
export function maxWidth(windowWidth: number): number {
  return Math.max(SIDEBAR_MIN, Math.min(SIDEBAR_MAX, Math.round(windowWidth * SIDEBAR_MAX_SHARE)));
}

export function clampWidth(width: number, windowWidth: number): number {
  return Math.round(Math.min(Math.max(width, SIDEBAR_MIN), maxWidth(windowWidth)));
}

/**
 * The layout this browser last used. It is only a convenience: storage can be missing or
 * blocked, so anything unreadable falls back to the defaults. Nothing sensitive is kept.
 */
export function loadLayout(storage: Storage | undefined): SidebarLayout {
  const fallback = { width: SIDEBAR_DEFAULT, collapsed: false };
  try {
    const saved = JSON.parse(storage?.getItem(STORAGE_KEY) ?? 'null');
    return {
      width: typeof saved?.width === 'number' && saved.width > 0 ? saved.width : fallback.width,
      collapsed: saved?.collapsed === true,
    };
  } catch {
    return fallback;
  }
}

export function saveLayout(storage: Storage | undefined, layout: SidebarLayout): void {
  try {
    storage?.setItem(STORAGE_KEY, JSON.stringify(layout));
  } catch {
    // Storage is full or blocked. The layout simply is not remembered.
  }
}
