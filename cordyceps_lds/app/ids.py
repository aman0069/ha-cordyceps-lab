"""Identifier allocation and validation helpers."""
from __future__ import annotations

import re
import secrets
import sqlite3
from datetime import date, datetime

BATCH_ID_RE = re.compile(r"^AC-\d{8}-\d{2}$")
JAR_ID_RE = re.compile(r"^AC-\d{8}-\d{2}-J\d{3}$")
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{22}$")


def is_valid_batch_id(value: str) -> bool:
    return bool(BATCH_ID_RE.fullmatch(value))


def is_valid_jar_id(value: str) -> bool:
    return bool(JAR_ID_RE.fullmatch(value))


def is_valid_scan_token(value: str) -> bool:
    return bool(TOKEN_RE.fullmatch(value))


def allocate_batch_id(connection: sqlite3.Connection, autoclave_date: date | datetime | str) -> str:
    """Allocate the next daily batch ID while holding a write transaction.

    Callers creating a batch should begin ``BEGIN IMMEDIATE`` before this function and
    insert the batch before committing, keeping allocation race-safe.
    """
    if isinstance(autoclave_date, datetime):
        date_text = autoclave_date.strftime("%Y%m%d")
    elif isinstance(autoclave_date, date):
        date_text = autoclave_date.strftime("%Y%m%d")
    else:
        digits = re.sub(r"\D", "", autoclave_date)[:8]
        if len(digits) != 8:
            raise ValueError("autoclave_date must contain YYYYMMDD")
        date_text = digits
    owns_transaction = not connection.in_transaction
    if owns_transaction:
        connection.execute("BEGIN IMMEDIATE")
    try:
        rows = connection.execute(
            "SELECT batch_id FROM batch_master WHERE batch_id GLOB ?", (f"AC-{date_text}-*",)
        ).fetchall()
        sequence = max((int(row["batch_id"].rsplit("-", 1)[1]) for row in rows), default=0) + 1
        if sequence > 99:
            raise ValueError("daily batch sequence exceeds 99")
        result = f"AC-{date_text}-{sequence:02d}"
        if owns_transaction:
            connection.commit()
        return result
    except Exception:
        if owns_transaction:
            connection.rollback()
        raise


def mint_jar_id(batch_id: str, jar_index: int) -> str:
    if not is_valid_batch_id(batch_id):
        raise ValueError("invalid batch ID")
    if not 1 <= jar_index <= 999:
        raise ValueError("jar index must be between 1 and 999")
    return f"{batch_id}-J{jar_index:03d}"


def mint_scan_token() -> str:
    """Return the required opaque, 22-character URL-safe scan token."""
    token = secrets.token_urlsafe(16)
    if not is_valid_scan_token(token):  # Defensive guard for future Python changes.
        raise RuntimeError("unexpected scan token format")
    return token
