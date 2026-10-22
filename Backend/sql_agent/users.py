"""Manage accounts from the command line, on the machine that runs the service.

Run from the Backend folder:

    .venv/bin/python -m sql_agent.users create you@example.org --admin --claim-unowned
    .venv/bin/python -m sql_agent.users create someone@example.org --google-only
    .venv/bin/python -m sql_agent.users list
    .venv/bin/python -m sql_agent.users set-role someone@example.org admin
    .venv/bin/python -m sql_agent.users disable someone@example.org
    .venv/bin/python -m sql_agent.users enable someone@example.org
    .venv/bin/python -m sql_agent.users reset-password someone@example.org
    .venv/bin/python -m sql_agent.users registration closed

Passwords are typed at a hidden prompt, twice, and never given as arguments, so they do not
end up in the shell's history. An account made here has a verified email: whoever runs this
vouches for it, so its owner may later sign in with Google on the same address.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from collections.abc import Callable

from .accounts import AccountError, AccountStore, User
from .appdb import AppDatabase, NewerSchema
from .config import ConfigError, load_settings
from .conversations import ConversationStore
from .passwords import PasswordRejected, check_rules


def _ask_password(prompt: Callable[[str], str] = getpass.getpass) -> str:
    first = prompt("Password (at least 12 characters): ")
    check_rules(first)
    if prompt("The same password again: ") != first:
        raise PasswordRejected("The two passwords are not the same.")
    return first


def _find(accounts: AccountStore, email: str) -> User:
    user = accounts.find_by_email(email)
    if user is None:
        raise AccountError("unknown_user", f"No account has the email {email}.")
    return user


def _describe(user: User) -> str:
    ways = [way for way, on in (("password", user.has_password), ("Google", user.google_linked)) if on]
    flags = " disabled" if user.disabled else ""
    return f"{user.email:<36} {user.role:<6} {' + '.join(ways) or 'no sign-in':<18} last seen {user.last_seen_at or 'never'}{flags}"


def main(argv: list[str] | None = None, *, prompt: Callable[[str], str] = getpass.getpass) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create", help="make an account")
    create.add_argument("email")
    create.add_argument("--name", default="")
    create.add_argument("--admin", action="store_true", help="give it the admin role")
    create.add_argument("--google-only", action="store_true", help="no password; sign in with Google")
    create.add_argument(
        "--claim-unowned", action="store_true", help="give it every conversation from before accounts existed"
    )
    commands.add_parser("list", help="list every account")
    role = commands.add_parser("set-role", help="make an account a user or an admin")
    role.add_argument("email")
    role.add_argument("role", choices=["user", "admin"])
    for name in ("disable", "enable", "reset-password"):
        commands.add_parser(name).add_argument("email")
    registration = commands.add_parser("registration", help="let anyone sign up, or nobody")
    registration.add_argument("state", choices=["open", "closed"])
    args = parser.parse_args(argv)

    try:
        settings = load_settings()
        database = AppDatabase(settings.conversations_path)
    except (ConfigError, NewerSchema) as exc:
        print(f"Settings error: {exc}", file=sys.stderr)
        return 1
    accounts = AccountStore(database)
    try:
        if args.command == "create":
            password = None if args.google_only else _ask_password(prompt)
            user = accounts.create_user(
                args.email,
                password=password,
                name=args.name,
                role="admin" if args.admin else "user",
                email_verified=True,
            )
            print(f"Created {_describe(user)}")
            if args.claim_unowned:
                claimed = ConversationStore(database=database).claim_unowned(user.id)
                print(f"Gave it {claimed} conversation(s) from before accounts.")
        elif args.command == "list":
            users = accounts.list_users()
            print("\n".join(_describe(user) for user in users) if users else "No accounts yet.")
        elif args.command == "set-role":
            print(f"Now {_describe(accounts.set_role(_find(accounts, args.email).id, args.role))}")
        elif args.command in ("disable", "enable"):
            user = accounts.set_disabled(_find(accounts, args.email).id, args.command == "disable")
            print(f"Now {_describe(user)}")
        elif args.command == "reset-password":
            user = _find(accounts, args.email)
            accounts.reset_password(user.id, _ask_password(prompt))
            print(f"Password reset for {user.email}. Every session of theirs has ended.")
        elif args.command == "registration":
            accounts.set_registration(args.state == "open")
            print(f"Registration is {args.state}.")
    except (AccountError, PasswordRejected) as exc:
        print(f"Not done: {exc}", file=sys.stderr)
        return 1
    finally:
        database.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
