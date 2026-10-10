import { TestBed } from '@angular/core/testing';

import { PREVIEW_ROWS, ResultTable } from './result-table';

async function render(columns: string[], rows: unknown[][]) {
  const fixture = TestBed.createComponent(ResultTable);
  fixture.componentRef.setInput('columns', columns);
  fixture.componentRef.setInput('rows', rows);
  await fixture.whenStable();
  return { fixture, element: fixture.nativeElement as HTMLElement };
}

const cells = (element: HTMLElement) =>
  [...element.querySelectorAll('tbody tr')].map((row) =>
    [...row.querySelectorAll('td')].map((cell) => cell.textContent),
  );

describe('ResultTable', () => {
  it('shows the columns and the rows', async () => {
    const { element } = await render(
      ['gender', 'n'],
      [
        ['F', 13],
        ['M', 21],
      ],
    );
    expect([...element.querySelectorAll('th')].map((th) => th.textContent)).toEqual([
      'gender',
      'n',
    ]);
    expect(cells(element)).toEqual([
      ['F', '13'],
      ['M', '21'],
    ]);
    expect(element.querySelector('button')).toBeNull();
    expect([...element.querySelectorAll('th.num')].map((th) => th.textContent)).toEqual(['n']);
  });

  it('marks a null apart from an empty string, and keeps zero', async () => {
    const { element } = await render(['a', 'b', 'c'], [[null, '', 0]]);
    expect(cells(element)).toEqual([['null', '', '0']]);
    expect(element.querySelectorAll('td.null').length).toBe(1);
    expect(element.querySelector('td.num')?.textContent).toBe('0');
  });

  it('previews a long result and shows the rest when asked', async () => {
    const rows = Array.from({ length: 25 }, (_, index) => [index]);
    const { fixture, element } = await render(['n'], rows);
    expect(cells(element).length).toBe(PREVIEW_ROWS);

    const more = element.querySelector('button') as HTMLButtonElement;
    expect(more.textContent?.trim()).toBe('Show all 25 rows');
    more.click();
    await fixture.whenStable();
    expect(cells(element).length).toBe(25);
    expect(element.querySelector('button')).toBeNull();
  });

  it('renders markup in a cell or a column name as text', async () => {
    const injected = '<img src=x onerror="alert(1)">';
    const { element } = await render([injected], [[injected]]);
    expect(element.querySelector('img')).toBeNull();
    expect(cells(element)).toEqual([[injected]]);
  });
});
