from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()

JT_API_URL = os.getenv(
    "JT_API_URL",
    "https://jt-api.rockettechbr.com.br",
).rstrip("/")
JT_API_KEY = os.getenv("JT_API_KEY", "").strip()

if not JT_API_KEY:
    raise RuntimeError("JT_API_KEY não configurada.")

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ALLOWED_TABLES = {"capotamento_diario"}


def _ident(value: str) -> str:
    value = str(value).strip()
    if not _IDENT.fullmatch(value):
        raise ValueError(f"Identificador SQL inválido: {value!r}")
    return value


def _placeholder(column: str) -> str:
    if column == "data":
        return "%s::date"
    if column in {"codigo_base", "codigo_regional", "id"}:
        return "%s::bigint"
    return "%s"


def _headers() -> dict[str, str]:
    return {
        "X-API-Key": JT_API_KEY,
        "Content-Type": "application/json",
    }


@dataclass
class APIResult:
    data: list[dict[str, Any]]


class TableQuery:
    def __init__(self, table: str):
        if table not in _ALLOWED_TABLES:
            raise ValueError(f"Tabela não permitida: {table}")
        self.table = table
        self.columns = "*"
        self.filters: list[tuple[str, str, Any]] = []
        self.order_column: str | None = None
        self.order_desc = False
        self.limit_value: int | None = None
        self._upsert_records: list[dict[str, Any]] | None = None
        self._upsert_keys: list[str] | None = None

    def select(self, columns: str = "*") -> "TableQuery":
        columns = (columns or "*").strip()
        if columns == "*":
            self.columns = "*"
            return self

        parsed = []
        for raw in columns.split(","):
            col = _ident(raw.strip())
            parsed.append(col)
        self.columns = ", ".join(parsed)
        return self

    def eq(self, column: str, value: Any) -> "TableQuery":
        self.filters.append((_ident(column), "=", value))
        return self

    def gte(self, column: str, value: Any) -> "TableQuery":
        self.filters.append((_ident(column), ">=", value))
        return self

    def lte(self, column: str, value: Any) -> "TableQuery":
        self.filters.append((_ident(column), "<=", value))
        return self

    def order(self, column: str, desc: bool = False) -> "TableQuery":
        self.order_column = _ident(column)
        self.order_desc = bool(desc)
        return self

    def limit(self, value: int) -> "TableQuery":
        self.limit_value = max(1, int(value))
        return self

    def upsert(
        self,
        records: list[dict[str, Any]],
        on_conflict: str,
    ) -> "TableQuery":
        keys = [_ident(x.strip()) for x in str(on_conflict).split(",") if x.strip()]
        if not keys:
            raise ValueError("on_conflict não informado para upsert")
        self._upsert_records = list(records)
        self._upsert_keys = keys
        return self

    def _execute_upsert(self) -> APIResult:
        records = self._upsert_records or []
        if not records:
            return APIResult(data=[])

        response = requests.post(
            f"{JT_API_URL}/import",
            headers=_headers(),
            json={
                "tabela": self.table,
                "chave": self._upsert_keys or [],
                "registros": records,
                "criar_tabela": False,
                "adicionar_colunas": False,
            },
            timeout=(15, 180),
        )

        if not response.ok:
            raise RuntimeError(
                f"JT API /import retornou HTTP {response.status_code}: {response.text}"
            )

        payload = response.json()
        return APIResult(data=[payload] if isinstance(payload, dict) else [])

    def _execute_select(self) -> APIResult:
        sql = f"SELECT {self.columns} FROM {self.table}"
        params: list[Any] = []

        if self.filters:
            clauses = []
            for column, operator, value in self.filters:
                clauses.append(f"{column} {operator} {_placeholder(column)}")
                params.append(value)
            sql += " WHERE " + " AND ".join(clauses)

        if self.order_column:
            sql += f" ORDER BY {self.order_column} {'DESC' if self.order_desc else 'ASC'}"

        if self.limit_value is not None:
            sql += f" LIMIT {self.limit_value}"

        sql += ";"

        response = requests.post(
            f"{JT_API_URL}/query",
            headers=_headers(),
            json={"sql": sql, "params": params},
            timeout=(15, 120),
        )

        if not response.ok:
            raise RuntimeError(
                f"JT API /query retornou HTTP {response.status_code}: {response.text}"
            )

        payload = response.json()
        columns = payload.get("colunas") or []
        rows = payload.get("rows") or []

        return APIResult(
            data=[dict(zip(columns, row)) for row in rows]
        )

    def execute(self) -> APIResult:
        if self._upsert_records is not None:
            return self._execute_upsert()
        return self._execute_select()


class JTAPIClient:
    def table(self, table: str) -> TableQuery:
        return TableQuery(table)


_CLIENT = JTAPIClient()


def get_supabase() -> JTAPIClient:
    """Compatibilidade com o código antigo; os dados agora vêm da JT API."""
    return _CLIENT
