import { summaryFixture } from '../testing/fixtures';
import { RECENT_COUNT, partition } from './sections';

/** A conversation last used on the given day, pinned at the given time if any. */
const chat = (id: string, used: string, pinned: string | null = null) =>
  summaryFixture({ id, title: id, updated_at: `${used}T12:00:00Z`, pinned_at: pinned });

const ids = (list: { id: string }[]) => list.map((item) => item.id);

describe('partition', () => {
  it('puts each conversation in exactly one section', () => {
    const list = [
      chat('a', '2026-10-20'),
      chat('b', '2026-10-19', '2026-10-01T00:00:00Z'),
      chat('c', '2026-10-18'),
      chat('d', '2026-10-17'),
      chat('e', '2026-10-16'),
      chat('f', '2026-10-15'),
      chat('g', '2026-10-14'),
      chat('h', '2026-09-30'),
      chat('i', '2026-08-02', '2026-10-05T00:00:00Z'),
    ];
    const { pinned, recents, older } = partition(list);

    expect(ids(pinned)).toEqual(['i', 'b']); // most recently pinned first
    expect(ids(recents)).toEqual(['a', 'c', 'd', 'e', 'f']);
    expect(recents.length).toBe(RECENT_COUNT);
    expect(older.map((group) => [group.label, ids(group.conversations)])).toEqual([
      ['October 2026', ['g']],
      ['September 2026', ['h']],
    ]);
    const all = [...pinned, ...recents, ...older.flatMap((group) => group.conversations)];
    expect(new Set(ids(all)).size).toBe(list.length);
  });

  it('moves an unpinned conversation back by when it was used', () => {
    const list = [chat('a', '2026-10-20'), chat('b', '2026-10-19', '2026-10-01T00:00:00Z')];
    expect(ids(partition(list).recents)).toEqual(['a']);
    const unpinned = list.map((item) => ({ ...item, pinned_at: null }));
    expect(ids(partition(unpinned).recents)).toEqual(['a', 'b']);
  });

  it('sorts by use even if the list arrives in another order, and copes with no list', () => {
    expect(ids(partition([chat('old', '2026-01-01'), chat('new', '2026-10-01')]).recents)).toEqual([
      'new',
      'old',
    ]);
    expect(partition([])).toEqual({ pinned: [], recents: [], older: [] });
  });

  it('treats a service without pinning as nothing pinned', () => {
    const item = summaryFixture();
    delete item.pinned_at;
    expect(ids(partition([item]).recents)).toEqual([item.id]);
  });
});
