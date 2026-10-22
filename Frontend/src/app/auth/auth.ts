import { Injectable, effect, inject, signal, untracked } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';

import { AgentApi, ApiError } from '../api/agent-api';
import { AuthConfig, AuthUser } from '../api/types';

/**
 * Who is signed in. The session itself is an HttpOnly cookie the page cannot read, so this
 * asks the service, and forgets the person as soon as any request finds the session gone.
 */
@Injectable({ providedIn: 'root' })
export class Auth {
  private readonly api = inject(AgentApi);
  private readonly router = inject(Router);

  /** The signed-in person, null when nobody is, undefined until the service has been asked. */
  readonly user = signal<AuthUser | null | undefined>(undefined);
  readonly config = signal<AuthConfig | null>(null);

  constructor() {
    // A request found the session ended, perhaps signed out elsewhere: go and sign in again.
    effect(() => {
      if (this.api.signedOut() > 0) {
        untracked(() => this.signedOut());
      }
    });
  }

  /** Ask the service who is signed in. Unreachable counts as unknown, not as signed out. */
  async load(): Promise<AuthUser | null> {
    try {
      this.user.set(await this.api.me());
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        this.user.set(null);
      } else {
        throw error;
      }
    }
    return this.user() ?? null;
  }

  async loadConfig(): Promise<AuthConfig | null> {
    try {
      this.config.set(await this.api.authConfig());
    } catch {
      // The page still offers email and password; Google simply is not shown.
    }
    return this.config();
  }

  async login(email: string, password: string): Promise<void> {
    this.user.set(await this.api.login(email, password));
  }

  async register(email: string, password: string, name: string): Promise<void> {
    this.user.set(await this.api.register(email, password, name));
  }

  async logout(): Promise<void> {
    try {
      await this.api.logout();
    } finally {
      this.user.set(null);
      await this.router.navigate(['/login']);
    }
  }

  private signedOut(): void {
    if (this.user() === null) {
      return;
    }
    this.user.set(null);
    const next = this.router.url;
    void this.router.navigate(['/login'], {
      queryParams: next && next !== '/' && !next.startsWith('/login') ? { next } : {},
    });
  }
}

/** The chat and every other page that needs an account. */
export const signedInGuard: CanActivateFn = async (_route, state) => {
  const auth = inject(Auth);
  const router = inject(Router);
  const user = auth.user() === undefined ? await auth.load().catch(() => null) : auth.user();
  if (user) {
    return true;
  }
  return router.createUrlTree(['/login'], {
    queryParams: state.url && state.url !== '/' ? { next: state.url } : {},
  });
};

/** The admin console: signed-out people sign in first; anyone else goes back to the chat. */
export const adminGuard: CanActivateFn = async (_route, state) => {
  const auth = inject(Auth);
  const router = inject(Router);
  const user = auth.user() === undefined ? await auth.load().catch(() => null) : auth.user();
  if (!user) {
    return router.createUrlTree(['/login'], { queryParams: { next: state.url } });
  }
  return user.role === 'admin' ? true : router.createUrlTree(['/']);
};

/** The sign-in pages, which a signed-in person skips. */
export const signedOutGuard: CanActivateFn = async () => {
  // Both injected before any await: inject() only works in the guard's first, synchronous part.
  const auth = inject(Auth);
  const router = inject(Router);
  const user = auth.user() === undefined ? await auth.load().catch(() => null) : auth.user();
  return user ? router.createUrlTree(['/']) : true;
};

/** Messages for the codes the service puts in /login?error=, after a Google sign-in. */
export const SIGN_IN_ERRORS: Record<string, string> = {
  google_off: 'Google sign-in is not set up on this service.',
  google_cancelled: 'Google sign-in was cancelled.',
  state_mismatch: 'That sign-in did not start here, or took too long. Please try again.',
  expired: 'That sign-in took too long. Please try again.',
  link_required:
    'An account with this email already exists. Sign in with your password, then connect Google from your account settings.',
  registration_closed: 'New accounts are not being accepted right now.',
  disabled: 'This account has been disabled. Ask an administrator.',
  email_unverified: 'Google has not verified this email address.',
  google_in_use: 'That Google account is already connected to another account.',
  signed_out: 'Sign in first.',
};

export function signInError(code: string | null): string | null {
  if (!code) {
    return null;
  }
  return SIGN_IN_ERRORS[code] ?? 'Google sign-in did not complete. Please try again.';
}
