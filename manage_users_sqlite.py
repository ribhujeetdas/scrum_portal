#!/usr/bin/env python3
"""
manage_users_sqlite.py

A standalone CLI tool to manage users in a local SQLite DB:
- list users
- create user
- update user
- delete user + cascade-delete related rows across all tables (discovered via FKs)

Works WITHOUT importing your Flask app.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from typing import Any, Dict, List, Tuple, Set, Optional

try:
    # Optional: for password hashing if you have password_hash column
    from werkzeug.security import generate_password_hash
except Exception:
    generate_password_hash = None


# ----------------------------
# SQLite helpers
# ----------------------------
def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    # Enable FK enforcement (even if your DB has FKs defined)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    )
    return cur.fetchone() is not None


def list_tables(conn: sqlite3.Connection) -> List[str]:
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )
    return [r["name"] for r in cur.fetchall()]


def table_info(conn: sqlite3.Connection, table: str) -> List[sqlite3.Row]:
    return conn.execute(f"PRAGMA table_info({quote_ident(table)})").fetchall()


def pk_column(conn: sqlite3.Connection, table: str) -> Optional[str]:
    """
    Returns single-column PK name if present, else None.
    """
    info = table_info(conn, table)
    pk_cols = [row["name"] for row in info if row["pk"] == 1]
    # If composite PK, pk flags may be 1..N; we only support single pk for propagation
    if len(pk_cols) == 1:
        return pk_cols[0]
    return None


def foreign_keys(conn: sqlite3.Connection, table: str) -> List[sqlite3.Row]:
    """
    PRAGMA foreign_key_list(table) includes:
      id, seq, table, from, to, on_update, on_delete, match
    """
    return conn.execute(f"PRAGMA foreign_key_list({quote_ident(table)})").fetchall()


def quote_ident(name: str) -> str:
    # Safe quoting for identifiers
    return '"' + name.replace('"', '""') + '"'


def parse_kv_pairs(pairs: List[str]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for p in pairs:
        if "=" not in p:
            raise ValueError(f"Invalid pair '{p}'. Expected key=value.")
        k, v = p.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def coerce_value(v: str) -> Any:
    """
    Basic coercion:
    - "null" -> None
    - integers -> int
    - floats -> float
    - otherwise string
    """
    if v.lower() in ("null", "none"):
        return None
    # bool-like (optional)
    if v.lower() in ("true", "false"):
        return 1 if v.lower() == "true" else 0
    try:
        if v.isdigit() or (v.startswith("-") and v[1:].isdigit()):
            return int(v)
        # float?
        return float(v)
    except Exception:
        return v


# ----------------------------
# User operations
# ----------------------------
def list_users(conn: sqlite3.Connection, users_table: str, limit: int = 50) -> None:
    if not table_exists(conn, users_table):
        raise RuntimeError(f"Users table '{users_table}' not found.")
    cols = [r["name"] for r in table_info(conn, users_table)]
    # show common columns if present
    preferred = [c for c in ("id", "email", "username", "name") if c in cols]
    show_cols = preferred if preferred else cols[:6]

    cur = conn.execute(
        f"SELECT {', '.join(quote_ident(c) for c in show_cols)} FROM {quote_ident(users_table)} ORDER BY 1 DESC LIMIT ?",
        (limit,),
    )
    rows = cur.fetchall()
    print(f"\nUsers (table={users_table}) showing {len(rows)} row(s):")
    if not rows:
        return
    print(" | ".join(show_cols))
    print("-" * (len(" | ".join(show_cols))))
    for r in rows:
        print(" | ".join(str(r[c]) for c in show_cols))


def create_user(conn: sqlite3.Connection, users_table: str, data: Dict[str, Any], set_password: Optional[str]) -> None:
    if not table_exists(conn, users_table):
        raise RuntimeError(f"Users table '{users_table}' not found.")

    cols = [r["name"] for r in table_info(conn, users_table)]

    # If user provided --set-password, attempt to write password_hash if column exists
    if set_password is not None:
        if "password_hash" not in cols:
            raise RuntimeError(
                f"--set-password provided but '{users_table}.password_hash' column not found.")
        if generate_password_hash is None:
            raise RuntimeError(
                "werkzeug is not available to hash passwords. Install it or provide password_hash=... manually.")
        data["password_hash"] = generate_password_hash(set_password)

    # Filter only valid columns
    filtered = {k: v for k, v in data.items() if k in cols}
    invalid = [k for k in data.keys() if k not in cols]
    if invalid:
        raise RuntimeError(
            f"Invalid column(s) for {users_table}: {', '.join(invalid)}")

    if not filtered:
        raise RuntimeError("No valid user columns supplied.")

    keys = list(filtered.keys())
    values = [filtered[k] for k in keys]

    sql = f"INSERT INTO {quote_ident(users_table)} ({', '.join(quote_ident(k) for k in keys)}) VALUES ({', '.join(['?']*len(keys))})"
    cur = conn.execute(sql, values)
    conn.commit()
    print(f"✅ Created user row. New id = {cur.lastrowid}")


def update_user(conn: sqlite3.Connection, users_table: str, user_id: int, data: Dict[str, Any], set_password: Optional[str]) -> None:
    if not table_exists(conn, users_table):
        raise RuntimeError(f"Users table '{users_table}' not found.")

    cols = [r["name"] for r in table_info(conn, users_table)]
    if "id" not in cols:
        raise RuntimeError(
            f"'{users_table}' does not have an 'id' column. Provide a different key strategy.")

    if set_password is not None:
        if "password_hash" not in cols:
            raise RuntimeError(
                f"--set-password provided but '{users_table}.password_hash' column not found.")
        if generate_password_hash is None:
            raise RuntimeError(
                "werkzeug is not available to hash passwords. Install it or provide password_hash=... manually.")
        data["password_hash"] = generate_password_hash(set_password)

    filtered = {k: v for k, v in data.items() if k in cols and k != "id"}
    invalid = [k for k in data.keys() if k not in cols]
    if invalid:
        raise RuntimeError(
            f"Invalid column(s) for {users_table}: {', '.join(invalid)}")

    if not filtered:
        raise RuntimeError("No valid update columns supplied (excluding id).")

    # Ensure user exists
    cur = conn.execute(
        f"SELECT 1 FROM {quote_ident(users_table)} WHERE id=?", (user_id,))
    if cur.fetchone() is None:
        raise RuntimeError(f"User id={user_id} not found in '{users_table}'.")

    sets = ", ".join(f"{quote_ident(k)}=?" for k in filtered.keys())
    values = list(filtered.values()) + [user_id]
    sql = f"UPDATE {quote_ident(users_table)} SET {sets} WHERE id=?"
    conn.execute(sql, values)
    conn.commit()
    print(f"✅ Updated user id={user_id}")


# ----------------------------
# Cascade delete logic (FK introspection)
# ----------------------------
def build_fk_index(conn: sqlite3.Connection) -> Dict[str, List[Tuple[str, str, str]]]:
    """
    Returns a map:
      parent_table -> list of (child_table, child_fk_column, parent_pk_column)
    based on PRAGMA foreign_key_list for all tables.
    """
    index: Dict[str, List[Tuple[str, str, str]]] = {}
    for t in list_tables(conn):
        for fk in foreign_keys(conn, t):
            parent = fk["table"]
            child_fk_col = fk["from"]
            parent_pk_col = fk["to"]
            index.setdefault(parent, []).append(
                (t, child_fk_col, parent_pk_col))
    return index


def collect_delete_plan(
    conn: sqlite3.Connection,
    users_table: str,
    user_id: int,
) -> List[Tuple[int, str, str, List[Any]]]:
    """
    Collect a deletion plan from deepest to shallowest:
    Returns list of (depth, table, pk_col, ids_to_delete)
    We propagate deletions along FK chains.
    """
    fk_index = build_fk_index(conn)

    # We'll track ids_to_delete per table by PK value if possible
    to_delete: Dict[str, Set[Any]] = {}
    depth_map: Dict[str, int] = {}

    # Seed with the user row
    to_delete[users_table] = {user_id}
    depth_map[users_table] = 0

    # BFS propagation
    queue: List[str] = [users_table]
    visited: Set[Tuple[str, str]] = set()  # (parent, child) edges processed

    while queue:
        parent = queue.pop(0)
        parent_ids = list(to_delete.get(parent, set()))
        parent_pk = pk_column(conn, parent)
        # if parent_pk is None, we can still delete child rows only if FK references a stable column; but propagation may be limited
        children = fk_index.get(parent, [])

        for child_table, child_fk_col, parent_pk_col in children:
            edge = (parent, child_table)
            if edge in visited:
                continue
            visited.add(edge)

            # Only proceed if parent_pk_col matches parent_pk (most common case)
            # If mismatch, we still try to match parent_pk_col by reading it from parent table.
            ids_for_join = parent_ids

            if parent_pk is None or parent_pk_col != parent_pk:
                # Fetch parent_pk_col values for these parent rows
                # Example: child references parent.some_other_key
                cur = conn.execute(
                    f"SELECT {quote_ident(parent_pk_col)} AS k FROM {quote_ident(parent)} WHERE id IN ({','.join(['?']*len(parent_ids))})",
                    parent_ids,
                )
                ids_for_join = [row["k"] for row in cur.fetchall()]

            if not ids_for_join:
                continue

            child_pk = pk_column(conn, child_table)

            if child_pk:
                cur = conn.execute(
                    f"SELECT {quote_ident(child_pk)} AS pkv FROM {quote_ident(child_table)} "
                    f"WHERE {quote_ident(child_fk_col)} IN ({','.join(['?']*len(ids_for_join))})",
                    ids_for_join,
                )
                found = [row["pkv"] for row in cur.fetchall()]
                if found:
                    to_delete.setdefault(child_table, set()).update(found)
                    depth_map[child_table] = max(depth_map.get(
                        child_table, 0), depth_map[parent] + 1)
                    queue.append(child_table)
            else:
                # No PK; fallback: mark with a special sentinel list later using FK condition only
                # We store the FK values directly for deletion condition
                # WARNING: this can over-delete if FK values overlap; but for user_id style FKs it's ok
                to_delete.setdefault(child_table, set()).update(ids_for_join)
                depth_map[child_table] = max(depth_map.get(
                    child_table, 0), depth_map[parent] + 1)
                queue.append(child_table)

    # Build plan excluding users_table, deepest first, then delete users last
    plan: List[Tuple[int, str, str, List[Any]]] = []
    for table, ids in to_delete.items():
        if table == users_table:
            continue
        pk = pk_column(conn, table) or "__NO_PK__"
        plan.append((depth_map.get(table, 0), table, pk, sorted(ids)))

    # Sort by depth DESC so children deleted before parents
    plan.sort(key=lambda x: x[0], reverse=True)

    # Finally add users delete
    plan.append((0, users_table, "id", [user_id]))
    return plan


def execute_delete_plan(conn: sqlite3.Connection, plan: List[Tuple[int, str, str, List[Any]]], dry_run: bool) -> None:
    print("\nDelete plan (deepest first):")
    for depth, table, pk, ids in plan:
        print(f"  depth={depth:02d}  table={table}  key={pk}  rows={len(ids)}")

    if dry_run:
        print("\n🟡 DRY RUN enabled. No deletes executed.")
        return

    try:
        conn.execute("BEGIN;")
        for depth, table, pk, ids in plan:
            if not ids:
                continue

            if pk == "__NO_PK__":
                # Best-effort: assume this set is FK values for a column named user_id
                # Try to locate a likely FK column:
                cols = [r["name"] for r in table_info(conn, table)]
                fk_col = "user_id" if "user_id" in cols else None
                if not fk_col:
                    # last resort: skip to avoid dangerous deletes
                    raise RuntimeError(
                        f"Cannot safely delete from '{table}' (no PK and no user_id column). "
                        f"Please add PK or provide explicit cleanup for this table."
                    )
                sql = f"DELETE FROM {quote_ident(table)} WHERE {quote_ident(fk_col)} IN ({','.join(['?']*len(ids))})"
                conn.execute(sql, ids)
            else:
                sql = f"DELETE FROM {quote_ident(table)} WHERE {quote_ident(pk)} IN ({','.join(['?']*len(ids))})"
                conn.execute(sql, ids)

        conn.commit()
        print("\n✅ Delete completed successfully.")
    except Exception as exc:
        conn.rollback()
        print("\n❌ Delete failed. Rolled back.")
        raise


def delete_user(conn: sqlite3.Connection, users_table: str, user_id: int, cascade: bool, dry_run: bool) -> None:
    if not table_exists(conn, users_table):
        raise RuntimeError(f"Users table '{users_table}' not found.")

    cur = conn.execute(
        f"SELECT 1 FROM {quote_ident(users_table)} WHERE id=?", (user_id,))
    if cur.fetchone() is None:
        raise RuntimeError(f"User id={user_id} not found in '{users_table}'.")

    if not cascade:
        if dry_run:
            print(
                f"🟡 DRY RUN: would delete user id={user_id} from {users_table}")
            return
        conn.execute(
            f"DELETE FROM {quote_ident(users_table)} WHERE id=?", (user_id,))
        conn.commit()
        print(f"✅ Deleted user id={user_id}")
        return

    plan = collect_delete_plan(conn, users_table, user_id)
    execute_delete_plan(conn, plan, dry_run=dry_run)


# ----------------------------
# CLI
# ----------------------------
def main():
    ap = argparse.ArgumentParser(
        description="Manage users in a local SQLite DB with cascade delete.")
    ap.add_argument("--db", required=True,
                    help="Path to SQLite DB (e.g., instance/app.db)")
    ap.add_argument("--users-table", default="users",
                    help="Users table name (default: users)")

    sub = ap.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="List users")
    p_list.add_argument("--limit", type=int, default=50)

    p_create = sub.add_parser("create", help="Create a user")
    p_create.add_argument("fields", nargs="*",
                          help="key=value pairs (columns in users table)")
    p_create.add_argument("--set-password", default=None,
                          help="Hash and store password into password_hash (if present)")

    p_update = sub.add_parser("update", help="Update a user by id")
    p_update.add_argument("--id", type=int, required=True)
    p_update.add_argument("fields", nargs="*",
                          help="key=value pairs to update")
    p_update.add_argument("--set-password", default=None,
                          help="Hash and store password into password_hash (if present)")

    p_delete = sub.add_parser("delete", help="Delete a user")
    p_delete.add_argument("--id", type=int, required=True)
    p_delete.add_argument("--cascade", action="store_true",
                          help="Cascade delete related rows across tables")
    p_delete.add_argument("--dry-run", action="store_true",
                          help="Show what would be deleted without deleting")

    args = ap.parse_args()

    conn = connect(args.db)
    try:
        if args.cmd == "list":
            list_users(conn, args.users_table, limit=args.limit)

        elif args.cmd == "create":
            data = {k: coerce_value(v)
                    for k, v in parse_kv_pairs(args.fields).items()}
            create_user(conn, args.users_table, data,
                        set_password=args.set_password)

        elif args.cmd == "update":
            data = {k: coerce_value(v)
                    for k, v in parse_kv_pairs(args.fields).items()}
            update_user(conn, args.users_table, args.id,
                        data, set_password=args.set_password)

        elif args.cmd == "delete":
            delete_user(conn, args.users_table, args.id,
                        cascade=args.cascade, dry_run=args.dry_run)

    finally:
        conn.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        sys.exit(1)
