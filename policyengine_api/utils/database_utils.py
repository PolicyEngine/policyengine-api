"""
Database utility functions for safe operations.
"""

from sqlalchemy.engine.row import LegacyRow
from typing import Optional, Dict, Any, List, Tuple


def get_inserted_record_id(
    database,
    table_name: str,
    where_conditions: Dict[str, Any],
    order_by: str = "id",
) -> int:
    """
    Safely retrieve the ID of a recently inserted record by matching on unique fields.
    This avoids race conditions that can occur with LAST_INSERT_ID().

    Args:
        database: The database connection/query interface
        table_name (str): Name of the table to query
        where_conditions (Dict[str, Any]): Dictionary of column:value pairs for WHERE clause
        order_by (str): Column to order by (default: "id")

    Returns:
        int: The ID of the matched record

    Raises:
        Exception: If no matching record is found
    """
    # Build WHERE clause from conditions
    where_clauses = [f"{col} = ?" for col in where_conditions.keys()]
    where_clause = " AND ".join(where_clauses)

    # Handle NULL values properly
    where_clauses_with_nulls = []
    values = []
    for col, val in where_conditions.items():
        if val is None:
            where_clauses_with_nulls.append(f"{col} IS NULL")
        else:
            where_clauses_with_nulls.append(f"{col} = ?")
            values.append(val)

    where_clause = " AND ".join(where_clauses_with_nulls)

    query = f"""
        SELECT id FROM {table_name} 
        WHERE {where_clause}
        ORDER BY {order_by} DESC 
        LIMIT 1
    """

    row: Optional[LegacyRow] = database.query(query, tuple(values)).fetchone()

    if row is None:
        raise Exception(
            f"Failed to retrieve inserted record from {table_name}"
        )

    return row["id"]


def find_existing_record(
    database, table_name: str, where_conditions: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """
    Find an existing record in a table based on matching conditions.

    Args:
        database: The database connection/query interface
        table_name (str): Name of the table to query
        where_conditions (Dict[str, Any]): Dictionary of column:value pairs for WHERE clause

    Returns:
        Optional[Dict[str, Any]]: The matching record as a dictionary, or None if not found
    """
    # Handle NULL values properly
    where_clauses_with_nulls = []
    values = []
    for col, val in where_conditions.items():
        if val is None:
            where_clauses_with_nulls.append(f"{col} IS NULL")
        else:
            where_clauses_with_nulls.append(f"{col} = ?")
            values.append(val)

    where_clause = " AND ".join(where_clauses_with_nulls)

    query = f"SELECT * FROM {table_name} WHERE {where_clause}"

    row: Optional[LegacyRow] = database.query(query, tuple(values)).fetchone()

    if row is not None:
        return dict(row)

    return None
