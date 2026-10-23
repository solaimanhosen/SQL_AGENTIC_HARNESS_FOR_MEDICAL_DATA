import { Routes, UrlMatchResult, UrlSegment } from '@angular/router';

import { adminGuard, signedInGuard, signedOutGuard } from './auth/auth';
import { AuthPage } from './auth/auth-page';
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
  {
    path: 'login',
    component: AuthPage,
    data: { mode: 'login' },
    canActivate: [signedOutGuard],
    title: 'Sign in · Patient data questions',
  },
  {
    path: 'register',
    component: AuthPage,
    data: { mode: 'register' },
    canActivate: [signedOutGuard],
    title: 'Create an account · Patient data questions',
  },
  {
    path: 'forgot-password',
    // The pages a link in an email opens are loaded only then.
    loadComponent: () => import('./auth/email-pages').then((module) => module.ForgotPasswordPage),
    canActivate: [signedOutGuard],
    title: 'Reset your password · Patient data questions',
  },
  {
    // No guard: the link may be opened in a browser signed in to some account.
    path: 'reset-password',
    loadComponent: () => import('./auth/email-pages').then((module) => module.ResetPasswordPage),
    title: 'Choose a new password · Patient data questions',
  },
  {
    path: 'verify-email',
    loadComponent: () => import('./auth/email-pages').then((module) => module.VerifyEmailPage),
    title: 'Confirm your email · Patient data questions',
  },
  {
    path: 'account',
    // Loaded only when opened, so the chat's first load stays small.
    loadComponent: () => import('./account/account-page').then((module) => module.AccountPage),
    canActivate: [signedInGuard],
    title: 'Account · Patient data questions',
  },
  {
    path: 'admin',
    // Loaded only when an admin opens it.
    loadComponent: () => import('./admin/admin-page').then((module) => module.AdminPage),
    canActivate: [adminGuard],
    title: 'Admin console · Patient data questions',
  },
  {
    matcher: chatMatcher,
    component: ChatPage,
    canActivate: [signedInGuard],
    title: 'Patient data questions',
  },
  { path: '**', redirectTo: '' },
];
