from __future__ import annotations

import os
import sys
from collections import Counter

import requests
from dotenv import load_dotenv

load_dotenv()

# Códigos confirmados na Gestão de colaboradores de 04/11/2026.
BASES_JOHAN = {
    891114: "CPN -PA",
    961420: "CRA-PA",
    891108: "CST -PA",
    961365: "F CST-PA",
    961250: "F IGA-PA",
    961441: "MAR-PA",
    961562: "PRM-PA",
    961405: "SIP-PA",
    891121: "SLP -PA",
    961483: "STA-PA",
    891127: "VGA -PA",
}
JOHAN = "JOHAN RAFAEL QUEIROZ PACHECO"
API_URL = os.getenv("JT_API_URL", "").strip().rstrip("/")
API_KEY = os.getenv("JT_API_KEY", "").strip()
TABELA = "capotamento_diario"


def api_post(route: str, body: dict):
    response = requests.post(
        f"{API_URL}{route}",
        headers={"X-API-Key": API_KEY},
        json=body,
        timeout=(15, 180),
    )
    if not response.ok:
        raise RuntimeError(
            f"JT API {route}: HTTP {response.status_code}: {response.text[:1000]}"
        )
    return response.json()


def fetch_rows():
    codigos = ", ".join(str(c) for c in sorted(BASES_JOHAN))
    query = (
        f"SELECT * FROM {TABELA} "
        f"WHERE codigo_base IN ({codigos}) "
        f"ORDER BY data, codigo_base;"
    )
    result = api_post("/query", {"sql": query, "params": []})
    cols = result.get("colunas", [])
    return [dict(zip(cols, row)) for row in result.get("rows", [])]


def main():
    dry_run = "--dry-run" in sys.argv
    if not API_URL or not API_KEY:
        raise SystemExit("Configure JT_API_URL e JT_API_KEY no .env da pasta Capotamento")

    rows = fetch_rows()
    print(f"Registros históricos localizados: {len(rows)}")
    print(f"Bases previstas na Gestão: {len(BASES_JOHAN)}")
    by_code = Counter(int(r["codigo_base"]) for r in rows)
    for code, name in sorted(BASES_JOHAN.items()):
        print(f"  {code} | {name:<14} | {by_code[code]} registros")

    changed = []
    for row in rows:
        if (
            (row.get("coordenador") or "").strip() == JOHAN
            and row.get("supervisor") is None
        ):
            continue
        updated = dict(row)
        updated.pop("id", None)
        updated.pop("importado_em", None)
        updated["coordenador"] = JOHAN
        updated["supervisor"] = None
        changed.append(updated)

    print(f"Registros que precisam ser corrigidos: {len(changed)}")
    if dry_run:
        print("DRY-RUN: nenhuma alteração enviada.")
        return
    if not changed:
        print("Banco já está atualizado para essas bases.")
        return

    for pos in range(0, len(changed), 100):
        batch = changed[pos : pos + 100]
        result = api_post(
            "/import",
            {
                "tabela": TABELA,
                "chave": ["data", "codigo_base"],
                "registros": batch,
                "criar_tabela": False,
                "adicionar_colunas": False,
            },
        )
        print(f"Lote {pos // 100 + 1} enviado ({len(batch)} registros): {result}")

    # Validação após a atualização de todos os lotes.
    refreshed = fetch_rows()
    remaining = [
        r for r in refreshed
        if (r.get("coordenador") or "").strip() != JOHAN
        or r.get("supervisor") is not None
    ]
    if remaining:
        raise RuntimeError(
            f"Verificação falhou: {len(remaining)} registros permanecem incorretos"
        )
    print(f"OK: {len(refreshed)} registros históricos conferidos. Johan como coordenador, sem supervisor.")


if __name__ == "__main__":
    main()
