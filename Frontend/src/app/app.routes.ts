import { Routes, UrlMatchResult, UrlSegment } from '@angular/router';

import { CONVERSATION_ID, ChatPage } from './chat/chat-page';

/**
 * Matches both "/" (a new chat) and "/c/<id>" (a stored one) with one route, so moving between
 * them keeps the same chat page instead of rebuilding it, which would interrupt a running
 * answer when a new chat gets its id.
 */
export function chatMatcher(segments: UrlSegment[]): UrlMatchResult | null {
  if (segments.length === 0) {
    return { consumed: [] };
  }
  if (segments.length === 2 && segments[0].path === 'c' && CONVERSATION_ID.test(segments[1].path)) {
    return { consumed: segments, posParams: { id: segments[1] } };
  }
  return null;
}

export const routes: Routes = [
  { matcher: chatMatcher, component: ChatPage, title: 'Patient data questions' },
  { path: '**', redirectTo: '' },
];
