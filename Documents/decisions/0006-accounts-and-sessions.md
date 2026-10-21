# ADR 0006: Accounts, with sessions in a cookie

- **Status:** Accepted on 2026-10-21.
- **Decision:** People sign in with an account. A session is a random token in an HttpOnly,
  SameSite=Strict cookie, and only its hash is stored. Conversations belong to the account
  that started them. Accounts replace the shared token.

## Context

Until v3.0.0 the service had one shared token, or none on this machine. Everyone holding it
saw every conversation, the logs could not say who asked what, and an admin could not be
told apart from anyone else. Phase D needs per-person conversations and an admin role for
the admin console, and the user asked for accounts now rather than after the plan.

## Decision

1. **Where the data lives.** Accounts live in the application database,
   `data/conversations.db`, beside the conversations, so a conversation's `owner` is a user
   in the same file. `appdb.py` owns the connection and the schema migrations (version 4
   adds users, sessions, pending Google sign-ins and settings).
2. **Roles.** There are two: `user` and `admin`. The first admin is made from the command
   line (`python -m sql_agent.users create EMAIL --admin --claim-unowned`), typing the
   password at a prompt, never as an argument.
3. **Passwords.**
   - They are hashed with scrypt from the standard library, so there is no new dependency.
   - Each hash carries its own cost parameters, so the cost can rise later.
   - A password must be 12 to 128 characters, with no composition rules (NIST 800-63B).
   - Sign-in answers a wrong password and an unknown email identically, in the same time,
     and is throttled per address and per email.
4. **Sessions.**
   - A session is a 32-byte random token in an HttpOnly cookie: `SameSite=Strict`,
     `Path=/api`, and `Secure` unless `SQL_AGENT_SECURE_COOKIES=false`.
   - The database stores only its SHA-256.
   - A session ends after 30 idle days, after 90 days in all, on sign-out, or when the
     account is disabled.
5. **Cross-site requests.** Anything that changes state needs the header
   `X-Requested-With: sql-agent`, and any `Origin` it names must be allowed.
6. **Isolation.** Every conversation query takes the owner. Someone else's conversation is
   answered exactly like one that does not exist (404). The cap on stored conversations
   applies per owner.
7. **Budgets.** Each person has a daily token budget beside the service's.
8. **Registration** is open by default. An admin can close it, and the setting is stored in
   the database, so it holds across restarts.
9. **Logs.** Both logs name a person by id, never by email.

## Alternatives turned down

| Alternative | Why not |
|---|---|
| A second shared token for admins | It would be thrown away when accounts arrived, and still could not separate conversations |
| A bearer token in browser storage | Any script on the page could read it; an HttpOnly cookie cannot be read by the page at all |
| JWTs | They cannot be revoked before they expire without a store anyway, which is what a session table is |
| An accounts library or an identity provider | A dependency and a service to run for two roles and a sign-up page; the standard library covers hashing, and the rest is small and tested |
| bcrypt or argon2 | Each needs a native dependency; scrypt is in the standard library and memory-hard |
| A separate accounts database | The owner of a conversation could not be checked in the same transaction |

## Consequences

- The shared token is gone. `SQL_AGENT_API_TOKEN` is ignored. The service refuses to listen
  beyond this machine only when cookies are allowed over plain HTTP.
- Conversations from before accounts are invisible until an admin claims them.
- Nobody verifies the email of a self-registered account, and there is no password reset by
  email; an admin resets passwords from the command line.
- The interface sends people to a sign-in page whenever a session has ended.
