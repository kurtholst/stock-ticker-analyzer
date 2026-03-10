"""SQL warehouse query helper using Databricks SDK."""

from __future__ import annotations

import logging
from functools import lru_cache

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementParameterListItem, StatementState

logger = logging.getLogger(__name__)

WAREHOUSE_ID = "9dc098ca47a6d6a7"


@lru_cache(maxsize=1)
def _get_client() -> WorkspaceClient:
    return WorkspaceClient()


def _cast_value(value: str | None, type_name) -> object:
    """Cast a string value from the SQL result to its Python type."""
    if value is None:
        return None
    # type_name is a ColumnInfoTypeName enum; grab its string value
    tn = type_name.value if hasattr(type_name, "value") else str(type_name)
    tn = tn.upper()
    if tn in ("INT", "LONG", "SHORT", "BYTE"):
        return int(value)
    if tn in ("FLOAT", "DOUBLE", "DECIMAL"):
        return float(value)
    if tn == "BOOLEAN":
        return value.lower() in ("true", "1")
    # STRING, DATE, TIMESTAMP etc. stay as strings
    return value


def execute_sql(
    statement: str,
    parameters: dict[str, str] | None = None,
) -> list[dict]:
    """Execute a SQL statement on the serverless SQL warehouse.

    Returns rows as a list of dicts with values cast to native Python types.
    For DML statements (INSERT, UPDATE, MERGE) returns an empty list.
    """
    client = _get_client()

    params = None
    if parameters:
        params = [
            StatementParameterListItem(name=k, value=str(v))
            for k, v in parameters.items()
        ]

    response = client.statement_execution.execute_statement(
        warehouse_id=WAREHOUSE_ID,
        statement=statement,
        parameters=params,
        wait_timeout="50s",
    )

    if response.status and response.status.state != StatementState.SUCCEEDED:
        error = response.status.error
        raise RuntimeError(f"SQL execution failed: {error}")

    if not response.manifest or not response.result:
        return []

    columns = response.manifest.schema.columns
    col_names = [col.name for col in columns]
    col_types = [col.type_name for col in columns]

    rows: list[dict] = []
    for data_row in response.result.data_array or []:
        row = {}
        for i, (name, tp) in enumerate(zip(col_names, col_types)):
            row[name] = _cast_value(data_row[i] if i < len(data_row) else None, tp)
        rows.append(row)
    return rows
