# ADR 0009: Password reset and email confirmation by link

- **Status:** Accepted on 2026-10-22.
- **Decision:** The service emails single-use links for two things only: resetting a
  forgotten password, and confirming that an address belongs to the person who registered
  it. Mail goes out over plain SMTP, configured in `Backend/.env`, so the provider can change
  without a code change. Confirming is optional.

## Context

Until now a forgotten password could only be reset by an admin, and a self-registered email
was never verified, so Google sign-in could not reach such an account (ADR 0007). Both were
open items after v4.0.0. The user asked whether the email services cost money. They do
not at this size: Gmail with an app password sends about 500 messages a day for free and
needs no domain, and Brevo or Resend have free tiers once a domain is verified. The user
had not chosen a mailbox yet and asked whether it could change later.

## Decision

1. **Transport.** `smtplib` from the standard library, over STARTTLS on 587 or TLS from the
   start on 465, with a 15-second limit. Email is off unless the host, username, password and
   From address are all set. The password is read in `mailer.py` and kept out of `Settings`.
2. **Tokens.** 32 random bytes, stored only as their SHA-256 in `email_tokens` (schema
   version 6), bound to one account and one purpose. A reset link lasts 30 minutes, a
   confirmation link 3 days. A link works once. A newer link for the same purpose replaces
   the older one, and changing the password any other way voids an outstanding reset link.
3. **Where the token travels.** In the link's fragment: `/reset-password#token=…`. A
   browser never sends the fragment to a server, so it does not reach the dev server's log,
   the request log or a proxy. The page reads it, removes it from the address, and posts it.
4. **Asking for a reset says nothing.** `POST /api/auth/forgot` answers 202 with the same
   body for a known, unknown, disabled or malformed email. The message is sent after the
   response, so how long the mail server takes cannot be timed. Requests are limited to 3
   per email and 10 per address in 10 minutes, counted whether or not anything was sent.
5. **What a reset does.** It sets the password, ends every session of the account, and marks
   the email confirmed, because opening the link proves the reader holds the mailbox. It
   does not sign the person in; they sign in with the new password.
6. **Confirming is optional.** Signing up sends a confirmation link, and the account page
   shows a reminder with a button to send another. Nothing is locked until it is confirmed.
   A confirmed email lets Google sign-in reach the account by its email (ADR 0007, rule 3).
7. **Failures.** A mail server failure is logged without the link and never reaches the
   person, whose answer is the same as for a sent message.

## Alternatives turned down

| Alternative | Why not |
|---|---|
| A provider's SDK or HTTP API | A dependency and lock-in to one provider; every provider considered also accepts SMTP |
| The token in the query string | Query strings reach server and proxy logs; fragments do not |
| A reset that signs the person in | A link forwarded or left in a shared inbox would then open a session as well |
| Confirmation required before use | A slow or spam-filtered message would lock a new person out, and existing accounts would need confirming; the user chose a reminder |
| Six-digit codes instead of links | Short enough to guess within the limits unless attempts per code are also counted; a link carries 256 bits |

## Consequences

- To switch email on, someone fills in five settings and restarts. For Gmail that needs
  2-Step Verification and an app password, and the From address must be the same Gmail
  address. `python -m sql_agent.mailer ADDRESS` sends a test message, and `check_setup` signs
  in to the server without sending.
- The SMTP password is a credential, kept in `.env` beside the Anthropic key and Google's
  secret, never logged and never committed. Tests blank it, so a filled-in `.env` can never
  send mail from the test suite.
- Whoever controls a mailbox controls the account that uses it. That is true of every
  password reset by email.
- Links point at `SQL_AGENT_PUBLIC_URL`, so it must be the address people open.
