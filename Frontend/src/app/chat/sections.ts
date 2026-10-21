import { ConversationSummary } from '../api/types';

/** How many unpinned conversations Recents holds. The rest go to All chats. */
export const RECENT_COUNT = 5;

export interface MonthGroup {
  /** Such as "October 2026". */
  label: string;
  conversations: ConversationSummary[];
}

export interface Sections {
  /** Pinned conversations, most recently pinned first. */
  pinned: ConversationSummary[];
  /** The most recently used unpinned conversations. */
  recents: ConversationSummary[];
  /** Every other conversation, by the month it was last used, newest first. */
  older: MonthGroup[];
}

/**
 * Split the list into the sidebar's three sections. Each conversation appears in exactly one,
 * and the split is worked out again whenever the list changes, so pinning, unpinning or
 * using a conversation moves it to the right section with nothing else to keep track of.
 */
export function partition(
  list: readonly ConversationSummary[],
  monthLabel: (iso: string) => string = defaultMonthLabel,
): Sections {
  const byUse = [...list].sort((a, b) => b.updated_at.localeCompare(a.updated_at));
  const pinned = byUse
    .filter((item) => item.pinned_at)
    .sort((a, b) => b.pinned_at!.localeCompare(a.pinned_at!));
  const unpinned = byUse.filter((item) => !item.pinned_at);
  const recents = unpinned.slice(0, RECENT_COUNT);

  const older: MonthGroup[] = [];
  for (const item of unpinned.slice(RECENT_COUNT)) {
    const label = monthLabel(item.updated_at);
    const group = older.at(-1);
    if (group?.label === label) {
      group.conversations.push(item);
    } else {
      older.push({ label, conversations: [item] });
    }
  }
  return { pinned, recents, older };
}

const MONTH = new Intl.DateTimeFormat('en-US', { month: 'long', year: 'numeric' });

function defaultMonthLabel(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? 'Earlier' : MONTH.format(date);
}
