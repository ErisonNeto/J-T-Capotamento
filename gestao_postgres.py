"""Consulta centralizada da gestão atual de colaboradores na JT API / PostgreSQL.

Somente a gestão é atualizada; métricas históricas não são modificadas.
Cache de cinco minutos. Falhas de leitura são explícitas (sem gestão antiga oculta).
"""
from __future__ import annotations

import os
import time
from functools import lru_cache
from typing import Any

import requests

SQL_GESTAO = """
SELECT estacao_no, nome_base, uf, regional, responsavel_regiao,
       coordenador, supervisor, lider, assistente, sc_dc_responsavel,
       status_atual
FROM jt_operacao.vw_gestao_colaboradores_atual
WHERE estacao_no IS NOT NULL
"""


def _codigo(valor: Any) -> str:
    codigo = str(valor or "").strip()
    if codigo.endswith(".0") and codigo[:-2].isdigit():
        return codigo[:-2]
    return codigo


@lru_cache(maxsize=2)
def _mapa(bucket: int) -> dict[str, dict]:
    url = os.getenv("JT_API_URL", "https://jt-api.rockettechbr.com.br").rstrip("/")
    chave = os.getenv("JT_API_KEY", "").strip()
    if not url.startswith("https://") or not chave:
        raise RuntimeError("Configure JT_API_URL HTTPS e JT_API_KEY no backend.")
    resposta = requests.post(
        url + "/query",
        headers={"X-API-Key": chave},
        json={"sql": SQL_GESTAO, "params": []},
        timeout=(15, 90),
    )
    resposta.raise_for_status()
    payload = resposta.json()
    colunas, linhas = payload.get("colunas"), payload.get("rows")
    if not isinstance(colunas, list) or not isinstance(linhas, list):
        raise RuntimeError("JT API retornou gestão em formato inesperado.")
    mapa = {}
    for linha in linhas:
        row = linha if isinstance(linha, dict) else dict(zip(colunas, linha))
        codigo = _codigo(row.get("estacao_no"))
        if codigo:
            mapa[codigo] = row
    if not mapa:
        raise RuntimeError("A gestão central PostgreSQL está vazia.")
    return mapa


def aplicar_gestao(registros: list[dict], *, coluna_base: str = "base") -> list[dict]:
    """Associa sem duplicar linhas e sem alterar volumetria ou métricas operacionais."""
    if not registros:
        return registros
    gestao = _mapa(int(time.time() // 300))
    saida = []
    for original in registros:
        row = dict(original)
        g = gestao.get(_codigo(row.get("codigo_base")))
        if g:
            row["gestao_encontrada"] = True
            row["rm"] = str(g.get("responsavel_regiao") or "").strip()
            row["coordenador"] = str(g.get("coordenador") or "").strip()
            row["supervisor"] = str(g.get("supervisor") or "").strip()
            row["lider"] = str(g.get("lider") or "").strip()
            row["assistente"] = str(g.get("assistente") or "").strip()
            row["sc"] = row["coordenador"] or row["supervisor"]
            row["sc_dc_responsavel"] = str(g.get("sc_dc_responsavel") or "").strip()
            row["status_gestao"] = str(g.get("status_atual") or "").strip()
            if g.get("nome_base"):
                row[coluna_base] = g["nome_base"]
            if g.get("uf"):
                row["uf"] = g["uf"]
        else:
            row["gestao_encontrada"] = False
        saida.append(row)
    return saida
