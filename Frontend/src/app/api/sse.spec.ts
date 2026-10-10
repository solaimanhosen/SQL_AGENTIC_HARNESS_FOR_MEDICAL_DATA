import { SseParser } from './sse';

describe('SseParser', () => {
  it('reads named events with JSON data', () => {
    const parser = new SseParser();
    expect(parser.push('event: step\ndata: {"kind":"sql"}\n\n')).toEqual([
      { event: 'step', data: '{"kind":"sql"}' },
    ]);
  });

  it('holds a partial event until the rest arrives, even mid-line', () => {
    const parser = new SseParser();
    expect(parser.push('event: ans')).toEqual([]);
    expect(parser.push('wer\ndata: {"a":')).toEqual([]);
    expect(parser.push('1}\n\nevent: step\ndata: 2\n\n')).toEqual([
      { event: 'answer', data: '{"a":1}' },
      { event: 'step', data: '2' },
    ]);
  });

  it('accepts CRLF line endings, joins multi-line data and skips comments', () => {
    const parser = new SseParser();
    expect(parser.push(': keep-alive\r\n\r\ndata: one\r\ndata: two\r\n\r\n')).toEqual([
      { event: 'message', data: 'one\ntwo' },
    ]);
  });
});
