import { answerFixture } from '../testing/fixtures';
import { answerJson, fileStem, toCsv } from './export';

describe('toCsv', () => {
  it('writes a header and rows with CRLF line ends', () => {
    expect(
      toCsv(
        ['gender', 'n'],
        [
          ['F', 13],
          ['M', 21],
        ],
      ),
    ).toBe('gender,n\r\nF,13\r\nM,21\r\n');
  });

  it('quotes cells holding commas, quotes or line breaks', () => {
    const csv = toCsv(['description'], [['Hypertension, essential'], ['say "ah"'], ['two\nlines']]);
    expect(csv).toBe(
      'description\r\n"Hypertension, essential"\r\n"say ""ah"""\r\n"two\nlines"\r\n',
    );
  });

  it('writes a null as an empty cell and keeps zero and false', () => {
    expect(toCsv(['a', 'b', 'c'], [[null, 0, false]])).toBe('a,b,c\r\n,0,false\r\n');
  });

  it('writes only the header for a query with no rows', () => {
    expect(toCsv(['n'], [])).toBe('n\r\n');
  });

  it('defuses text a spreadsheet would run as a formula', () => {
    const csv = toCsv(
      ['value'],
      [['=HYPERLINK("http://evil")'], ['@SUM(A1)'], ['+cmd'], ['-2+3'], ['\tx']],
    );
    expect(csv.split('\r\n').slice(1, 6)).toEqual([
      `"'=HYPERLINK(""http://evil"")"`,
      `'@SUM(A1)`,
      `'+cmd`,
      `'-2+3`,
      `'\tx`,
    ]);
  });

  it('leaves numbers alone, including negative numbers stored as text', () => {
    expect(toCsv(['a', 'b', 'c'], [[-5, '-1.5', '+2']])).toBe('a,b,c\r\n-5,-1.5,+2\r\n');
  });
});

describe('answer export', () => {
  it('keeps the whole answer, rows included, as readable JSON', () => {
    const answer = answerFixture();
    const text = answerJson(answer);
    expect(JSON.parse(text)).toEqual(answer);
    expect(text).toContain('\n  "headline"');
    expect(JSON.parse(text).queries[0].rows).toEqual([[8]]);
  });

  it('names files after the conversation and the turn', () => {
    expect(fileStem(answerFixture({ conversation_id: 'abcdef0123456789', turn: 3 }))).toBe(
      'abcdef01-turn3',
    );
  });
});
