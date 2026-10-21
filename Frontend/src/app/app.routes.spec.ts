import { UrlSegment } from '@angular/router';

import { chatMatcher } from './app.routes';

const segments = (...paths: string[]) => paths.map((path) => new UrlSegment(path, {}));

describe('chatMatcher', () => {
  const id = 'a'.repeat(32);

  it('matches a new chat and a stored conversation with the same route', () => {
    expect(chatMatcher(segments())).toEqual({ consumed: [] });
    const match = chatMatcher(segments('c', id));
    expect(match?.posParams?.['id'].path).toBe(id);
  });

  it('refuses anything that is not a conversation id', () => {
    expect(chatMatcher(segments('c', 'A'.repeat(32)))).toBeNull();
    expect(chatMatcher(segments('c', '../admin'))).toBeNull();
    expect(chatMatcher(segments('c'))).toBeNull();
    expect(chatMatcher(segments('c', id, 'extra'))).toBeNull();
    expect(chatMatcher(segments('admin'))).toBeNull();
  });
});
