"""normalize sprint timestamp columns

Revision ID: b6f3a9c2d410
Revises: 9c2a1f7b6d10
Create Date: 2026-07-15 18:30:00.000000

"""

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "b6f3a9c2d410"
down_revision = "9c2a1f7b6d10"
branch_labels = None
depends_on = None

_COLUMNS = ("start_date", "end_date", "complete_date", "activated_date")


def _parse(value: object) -> datetime | None:
    if value is None or isinstance(value, datetime):
        parsed = value
    else:
        candidate = str(value).strip()
        if not candidate:
            return None
        if candidate.endswith("Z"):
            candidate = candidate[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError as exc:
            raise RuntimeError(f"Unparseable sprint timestamp: {value!r}") from exc
    if parsed is None:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def upgrade():
    connection = op.get_bind()
    rows = list(
        connection.execute(
            sa.text(
                "SELECT id, start_date, end_date, complete_date, activated_date "
                "FROM user_board_sprints"
            )
        ).mappings()
    )
    normalized_rows = [
        {
            "row_id": row["id"],
            **{f"{column}_normalized": _parse(row[column]) for column in _COLUMNS},
        }
        for row in rows
    ]

    # Parse every legacy value before the first non-transactional SQLite DDL statement.
    for column in _COLUMNS:
        op.add_column(
            "user_board_sprints",
            sa.Column(f"{column}_normalized", sa.DateTime(timezone=True), nullable=True),
        )

    for values in normalized_rows:
        statement = sa.text(
            "UPDATE user_board_sprints SET "
            + ", ".join(f"{column}_normalized = :{column}_normalized" for column in _COLUMNS)
            + " WHERE id = :row_id"
        )
        statement = statement.bindparams(
            *(
                sa.bindparam(f"{column}_normalized", type_=sa.DateTime(timezone=True))
                for column in _COLUMNS
            )
        )
        connection.execute(statement, values)

    with op.batch_alter_table("user_board_sprints", schema=None) as batch_op:
        for column in _COLUMNS:
            batch_op.drop_column(column)
            batch_op.alter_column(
                f"{column}_normalized",
                new_column_name=column,
                existing_type=sa.DateTime(timezone=True),
            )


def downgrade():
    connection = op.get_bind()
    for column in _COLUMNS:
        op.add_column(
            "user_board_sprints",
            sa.Column(f"{column}_text", sa.String(length=64), nullable=True),
        )
        connection.execute(
            sa.text(f"UPDATE user_board_sprints SET {column}_text = CAST({column} AS TEXT)")
        )

    with op.batch_alter_table("user_board_sprints", schema=None) as batch_op:
        for column in _COLUMNS:
            batch_op.drop_column(column)
            batch_op.alter_column(
                f"{column}_text",
                new_column_name=column,
                existing_type=sa.String(length=64),
            )
