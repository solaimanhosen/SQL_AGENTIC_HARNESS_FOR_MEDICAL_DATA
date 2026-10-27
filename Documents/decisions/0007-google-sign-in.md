# ADR 0007: Google sign-in, and when it may link to an existing account

- **Status:** Accepted on 2026-10-21.
- **Decision:** People may sign in with Google beside email and password. It uses OpenID
  Connect's authorization code flow with PKCE, with no new library. A Google identity is
  linked to an existing account only when that account's email was verified, by Google or by
  an admin.

## Context

The user asked whether people could sign up with their Google account, and how much
complexity it adds. They chose to build it now, beside passwords, switched off until a
Google client ID and secret are configured.

## Decision

1. **Library.** No OAuth library. `httpx`, already installed with the Anthropic SDK, makes
   the one server-to-server call to Google's token endpoint.
2. **The flow.**
   - `GET /api/auth/google/start` stores a one-time state, a nonce and a PKCE verifier,
     with the state hashed. It puts the state in a 10-minute HttpOnly cookie, `SameSite=Lax`
     because Google's redirect back is a cross-site navigation, and redirects to Google.
   - `GET /api/auth/google/callback` requires the state in the query to equal the cookie and
     a stored, unused, recent sign-in. It then exchanges the code with our secret and the
     verifier.
3. **The ID token** is read without checking its signature. That is permitted because it came
   directly from Google's token endpoint over HTTPS, to a request authenticated with our
   client secret (OpenID Connect Core, section 3.1.3.7). Its issuer, audience, expiry, nonce,
   subject, email and `email_verified` are all checked.
4. **Which account it reaches:**
   1. An account already linked to that Google identity is signed in.
   2. From Account settings, while signed in, Google is connected to the current account,
      unless another account has it.
   3. An account with the same email is linked only if its email is verified: made by an
      admin from the command line, linked to Google before, or, since ADR 0009, confirmed
      or reset through a link sent to it.
   4. Otherwise a new account is made with a verified email and no password. That happens
      only while registration is open.
5. **Failures.** Every failure returns to the login page with a short code. Details stay in
   the request log.
6. **Return path.** Where to return after sign-in must be a path inside the application.

## Why a self-registered account is never linked by email

Nobody checks that the person who registered an address with a password owns it. If Google
sign-in linked to such an account, anyone could register a victim's email first, set the
password, and wait. When the victim later signed in with Google they would land in the
attacker's account, or the attacker could keep signing in with the password. This is a
pre-account-takeover attack. Refusing the link costs the honest user one step: sign in with
the password, then connect Google from Account settings.

## Alternatives turned down

| Alternative | Why not |
|---|---|
| Authlib or another OAuth library | Two more dependencies and a session middleware, for one flow we can test completely with a fake Google |
| Verifying the token signature against Google's keys | A JWT and crypto dependency, and key caching, to defend a channel TLS and our secret already authenticate |
| The implicit flow or Google's JavaScript button | The token would pass through the browser; the code flow keeps it on the server |
| Linking every account by matching email | Opens the pre-account-takeover attack above |
| Google only, no passwords | Not everyone at Telligen may have a Google account, and the app would not work while Google is unreachable or unconfigured |

## Consequences

- To switch it on, someone creates an OAuth client in Google Cloud Console, of type Web
  application. Its redirect URI is `<SQL_AGENT_PUBLIC_URL>/api/auth/google/callback`. The ID
  and secret go in `Backend/.env`.
- In Google's "Testing" mode only listed test users can sign in. Publishing the consent
  screen for the basic scopes needs no review.
- The client secret is a credential, kept in `.env` beside the Anthropic key and never
  logged.
