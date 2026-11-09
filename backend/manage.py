"""User account management for the login system — no self-signup, an admin
runs this to create/remove accounts for authorized colleagues.

Usage (from backend/, with the venv active):
    python manage.py create-user <username>
    python manage.py reset-password <username>
    python manage.py list-users
    python manage.py delete-user <username>
"""
from __future__ import annotations

import argparse
import getpass
import sys

from app import auth
from app.db import init_db
from app import repository as repo


def create_user(username: str, role: str = "admin") -> None:
    if repo.get_user_by_username(username):
        print(f"'{username}' already exists.", file=sys.stderr)
        raise SystemExit(1)
    password = _prompt_password()
    repo.create_user(username=username, password_hash=auth.hash_password(password), role=role)
    print(f"Created {role} user '{username}'.")


def reset_password(username: str) -> None:
    row = repo.get_user_by_username(username)
    if row is None:
        print(f"No such user '{username}'.", file=sys.stderr)
        raise SystemExit(1)
    password = _prompt_password()
    repo.set_user_password(row["id"], auth.hash_password(password))
    repo.delete_sessions_for_user(row["id"])  # force re-login everywhere
    print(f"Password reset for '{username}'.")


def delete_user(username: str) -> None:
    row = repo.get_user_by_username(username)
    if row is None:
        print(f"No such user '{username}'.", file=sys.stderr)
        raise SystemExit(1)
    repo.delete_user(row["id"])
    print(f"Deleted user '{username}'.")


def list_users() -> None:
    rows = repo.list_users()
    if not rows:
        print("No users yet.")
        return
    for r in rows:
        print(f"{r['username']}  [{r['role']}]  (created {r['created_at']})")


def _prompt_password() -> str:
    while True:
        pw = getpass.getpass("Password: ")
        if len(pw) < 8:
            print("Password must be at least 8 characters.", file=sys.stderr)
            continue
        if pw != getpass.getpass("Confirm password: "):
            print("Passwords didn't match, try again.", file=sys.stderr)
            continue
        return pw


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("create-user")
    p.add_argument("username")
    p.add_argument("--role", choices=["admin", "user"], default="admin")

    p = sub.add_parser("reset-password")
    p.add_argument("username")

    p = sub.add_parser("delete-user")
    p.add_argument("username")

    sub.add_parser("list-users")

    args = parser.parse_args()
    init_db()

    if args.command == "create-user":
        create_user(args.username, args.role)
    elif args.command == "reset-password":
        reset_password(args.username)
    elif args.command == "delete-user":
        delete_user(args.username)
    elif args.command == "list-users":
        list_users()


if __name__ == "__main__":
    main()
