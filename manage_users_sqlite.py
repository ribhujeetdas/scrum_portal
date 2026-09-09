#!/usr/bin/env python3
"""Compatibility wrapper for the application's safe SQLite user operations.

The utility uses the same revocation epochs, server sessions, and Jira scope
invalidation as the Flask CLI. Arbitrary column updates and hard deletes are no
longer exposed because they could leave active report grants behind.
"""

from __future__ import annotations

import argparse
from getpass import getpass
from pathlib import Path

from app import create_app
from app.config import Config
from app.core.admin import (
    disable_user,
    enable_user,
    find_user,
    revoke_user_access,
    set_user_password,
)
from app.extensions import db
from app.models import User


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage Scrum Portal users safely")
    parser.add_argument("--db", required=True, help="SQLite database path")
    parser.add_argument(
        "command", choices=("list", "disable", "enable", "revoke", "set-password")
    )
    parser.add_argument("--id", type=int, dest="user_id")
    parser.add_argument("--identifier", help="User EID or email")
    parser.add_argument("--mark-deleted", action="store_true")
    args = parser.parse_args()

    database_path = Path(args.db).resolve()

    class ScriptConfig(Config):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{database_path.as_posix()}"
        LOG_TO_CONSOLE = False

    app = create_app(ScriptConfig)
    with app.app_context():
        if args.command == "list":
            for user in User.query.order_by(User.id).all():
                print(
                    f"id={user.id} eid={user.eid} email={user.email} "
                    f"active={int(user.active)} deleted={int(user.deleted)}"
                )
            return 0
        if (args.user_id is None) == (not args.identifier):
            parser.error("provide exactly one of --id or --identifier")
        user = find_user(user_id=args.user_id, identifier=args.identifier)
        if args.command == "disable":
            disable_user(user, deleted=args.mark_deleted)
        elif args.command == "enable":
            enable_user(user)
        elif args.command == "revoke":
            revoke_user_access(user)
        else:
            first = getpass("New password: ")
            second = getpass("Confirm password: ")
            if first != second:
                parser.error("password confirmation did not match")
            set_user_password(user, first)
        db.session.commit()
        print(f"Completed {args.command} for user id={user.id}; revocation rules applied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
