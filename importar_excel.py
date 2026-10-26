from __future__ import annotations

import argparse
import math
import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

THRESHOLDS = {
    "1D": (500.0, 0.50, "ALERTA"),
    "3D": (800.0, 0.80, "CAPOTADA"),
    "5D": (1000.0, 1.00, "CAPOTADA"),
    "7D": (1200.0, 1.20, "CAPOTADA"),
    "10D": (1500.0, 1.50, "CAPOTADA"),
}

COLS = {
    "Data": "data",
    "Nome da Regional": "nome_regional",
    "Código da Regional": "codigo_regional",
    "UF": "uf",
    "Nome da base": "nome_base",
    "Código da base": "codigo_base",
    "Média de pedidos recebidos nos últimos 7 dias": "media_recebidos_7d",
    "Média de pedidos entregues no prazo nos últimos 7 dias": "media_entregues_prazo_7d",
    "近7日最高签收量": "maior_entrega_prazo_7d",
    "Qtd Retidos até 1 dia": "retidos_1d",
    "Índice de capotamento dentro de 1 dia": "indice_1d",
    "Qtd Retidos até 3 dias": "retidos_3d",
    "Índice de capotamento dentro de 3 dias": "indice_3d",
    "Qtd Retidos até 5 dias": "retidos_5d",
    "Índice de capotamento dentro de 5 dias": "indice_5d",
    "Qtd Retidos até 7 dias": "retidos_7d",
    "Índice de capotamento dentro de 7 dias": "indice_7d",
    "Qtd Retidos até 10 dias": "retidos_10d",
    "Índice de capotamento dentro de 10 dias": "indice_10d",
    "Base com Alerta de Capotamento?": "alerta_fonte",
    "Base Capotada?": "capotada_fonte",
    "Qtd de capotamentos nos últimos 30 dias": "capotamentos_30d",
    "Qtd de dias consecutivos em capotamento": "dias_consecutivos_capotamento",
}

GESTAO_COLS = {
    "Estação No.": "codigo_base",
    "Responsável da Região": "rm",
    "Coordenador": "coordenador",
    "Supervisor": "supervisor",
    "Líder": "lider",
    "Tipo da base": "tipo_base",
    "Status atual": "status_gestao",
}


def clean_scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            value = value.item()
        except Exception:
            pass
    return value


def as_num(value: Any, default: float = 0.0) -> float:
    value = clean_scalar(value)
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        text = str(value).strip().replace("%", "").replace(",", ".")
        try:
            return float(text)
        except ValueError:
            return default


def as_bool_sn(value: Any) -> bool:
    return str(clean_scalar(value) or "").strip().upper() in {
        "S", "SIM", "Y", "YES", "TRUE", "1"
    }


def as_int(value: Any, default: int = 0) -> int:
    return int(round(as_num(value, default)))


def normalize_date(value: Any) -> str:
    value = clean_scalar(value)
    if value is None:
        raise ValueError("Data vazia no arquivo de capotamento")

    if isinstance(value, str):
        text = value.strip()

        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            parsed = pd.to_datetime(text, format="%Y-%m-%d", errors="coerce")
        else:
            parsed = pd.to_datetime(text, dayfirst=True, errors="coerce")

        if pd.isna(parsed):
            raise ValueError(f"Data inválida: {value!r}")
        return parsed.date().isoformat()

    if isinstance(value, (int, float)):
        return (
            datetime(1899, 12, 30) + timedelta(days=float(value))
        ).date().isoformat()

    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        raise ValueError(f"Data inválida: {value!r}")
    return parsed.date().isoformat()


def compute_risk(row: dict[str, Any]) -> dict[str, Any]:
    scores: dict[str, float] = {}

    for window, (q_limit, i_limit, _) in THRESHOLDS.items():
        q = as_num(row.get(f"retidos_{window.lower()}"))
        idx = as_num(row.get(f"indice_{window.lower()}"))
        scores[window] = min(q / q_limit, idx / i_limit)

    critical_window = max(scores, key=scores.get)
    score = max(0.0, scores[critical_window])

    q1 = as_num(row.get("retidos_1d"))
    i1 = as_num(row.get("indice_1d"))
    alert_calc = q1 >= 500 and i1 > 0.50

    cap_calc = False
    for window in ("3D", "5D", "7D", "10D"):
        q_limit, i_limit, _ = THRESHOLDS[window]
        q = as_num(row.get(f"retidos_{window.lower()}"))
        idx = as_num(row.get(f"indice_{window.lower()}"))
        if q >= q_limit and idx > i_limit:
            cap_calc = True
            break

    alert_src = bool(row.get("alerta_fonte"))
    cap_src = bool(row.get("capotada_fonte"))

    if cap_src:
        status = "CAPOTADA"
    elif alert_src:
        status = "ALERTA"
    elif score >= 0.90:
        status = "PRÉ-ALERTA CRÍTICO"
    elif score >= 0.80:
        status = "PRÉ-ALERTA"
    elif score >= 0.60:
        status = "MONITORAR"
    else:
        status = "NORMAL"

    q_limit, i_limit, _ = THRESHOLDS[critical_window]
    q_now = as_num(row.get(f"retidos_{critical_window.lower()}"))
    i_now = as_num(row.get(f"indice_{critical_window.lower()}"))

    return {
        "score_risco": round(score, 6),
        "janela_critica": critical_window,
        "status_risco": status,
        "alerta_calculado": alert_calc,
        "capotada_calculado": cap_calc,
        "divergencia_regra": (alert_src != alert_calc) or (cap_src != cap_calc),
        "falta_qtd": max(0.0, q_limit - q_now),
        "falta_indice": max(0.0, i_limit - i_now),
    }


def validate_file(path: str | Path) -> Path:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {p}")
    if not p.is_file():
        raise ValueError(f"Não é um arquivo: {p}")
    return p


def load_gestao_files(
    paths: Iterable[str | Path],
) -> tuple[dict[int, dict[str, Any]], list[int], int]:
    frames: list[pd.DataFrame] = []

    for raw_path in paths:
        path = validate_file(raw_path)
        df = pd.read_excel(path, sheet_name=0)

        missing = [c for c in GESTAO_COLS if c not in df.columns]
        if missing:
            raise ValueError(
                f"Colunas ausentes em Gestão de colaboradores "
                f"({path.name}): {missing}"
            )

        df = df[list(GESTAO_COLS)].rename(columns=GESTAO_COLS)
        df["_arquivo_gestao"] = path.name
        frames.append(df)

    if not frames:
        raise ValueError("Nenhum arquivo de Gestão foi informado.")

    df = pd.concat(frames, ignore_index=True)
    df["codigo_base"] = pd.to_numeric(df["codigo_base"], errors="coerce")
    df = df.dropna(subset=["codigo_base"])
    df["codigo_base"] = df["codigo_base"].astype("int64")

    duplicate_codes = sorted(
        df.loc[
            df.duplicated("codigo_base", keep=False),
            "codigo_base",
        ].unique().tolist()
    )

    result: dict[int, dict[str, Any]] = {}
    fields = [c for c in GESTAO_COLS.values() if c != "codigo_base"]

    for code, group in df.groupby("codigo_base", sort=False):
        merged: dict[str, Any] = {"codigo_base": int(code)}

        for col in fields:
            vals = [clean_scalar(v) for v in group[col].tolist()]
            vals = [v for v in vals if v not in (None, "")]
            merged[col] = vals[-1] if vals else None

        result[int(code)] = merged

    return result, duplicate_codes, len(df)


def parse_capotamento_file(
    path: str | Path,
    gestao: dict[int, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    path = validate_file(path)
    df = pd.read_excel(path, sheet_name=0)

    missing = [c for c in COLS if c not in df.columns]
    if missing:
        raise ValueError(
            f"Colunas ausentes no arquivo de capotamento "
            f"({path.name}): {missing}"
        )

    df = df[list(COLS)].rename(columns=COLS)

    payload: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []

    for _, raw in df.iterrows():
        code = as_int(raw.get("codigo_base"), -1)
        if code < 0:
            continue

        item = {k: clean_scalar(v) for k, v in raw.to_dict().items()}
        item["data"] = normalize_date(raw.get("data"))
        item["codigo_base"] = code
        item["codigo_regional"] = as_int(raw.get("codigo_regional"), 0) or None

        for col in [
            "media_recebidos_7d",
            "media_entregues_prazo_7d",
            "maior_entrega_prazo_7d",
            "retidos_1d",
            "indice_1d",
            "retidos_3d",
            "indice_3d",
            "retidos_5d",
            "indice_5d",
            "retidos_7d",
            "indice_7d",
            "retidos_10d",
            "indice_10d",
        ]:
            item[col] = (
                as_num(raw.get(col))
                if clean_scalar(raw.get(col)) is not None
                else None
            )

        item["alerta_fonte"] = as_bool_sn(raw.get("alerta_fonte"))
        item["capotada_fonte"] = as_bool_sn(raw.get("capotada_fonte"))
        item["capotamentos_30d"] = as_int(raw.get("capotamentos_30d"))
        item["dias_consecutivos_capotamento"] = as_int(
            raw.get("dias_consecutivos_capotamento")
        )

        g = gestao.get(code)

        if g:
            for col in (
                "rm",
                "coordenador",
                "supervisor",
                "lider",
                "tipo_base",
                "status_gestao",
            ):
                item[col] = clean_scalar(g.get(col))
        else:
            for col in (
                "rm",
                "coordenador",
                "supervisor",
                "lider",
                "tipo_base",
                "status_gestao",
            ):
                item[col] = None

            unmatched.append(
                {
                    "codigo_base": code,
                    "nome_base": item.get("nome_base"),
                    "arquivo": path.name,
                }
            )

        item.update(compute_risk(item))
        payload.append(item)

    return payload, unmatched


def parse_files(
    capotamento_paths: Iterable[str | Path],
    gestao_paths: Iterable[str | Path],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    capotamento_paths = list(capotamento_paths)
    gestao_paths = list(gestao_paths)

    if not capotamento_paths:
        raise ValueError("Nenhum arquivo de Capotamento foi informado.")
    if not gestao_paths:
        raise ValueError("Nenhum arquivo de Gestão foi informado.")

    gestao, duplicated_gestao, linhas_gestao = load_gestao_files(gestao_paths)

    keyed: dict[tuple[str, int], dict[str, Any]] = {}
    unmatched_all: list[dict[str, Any]] = []
    arquivos_info: list[dict[str, Any]] = []

    for raw_path in capotamento_paths:
        path = validate_file(raw_path)
        rows, unmatched = parse_capotamento_file(path, gestao)

        datas = sorted({r["data"] for r in rows})
        arquivos_info.append(
            {
                "arquivo": path.name,
                "linhas": len(rows),
                "datas": datas,
            }
        )

        for item in rows:
            keyed[(item["data"], int(item["codigo_base"]))] = item

        unmatched_all.extend(unmatched)

    payload = list(keyed.values())
    payload.sort(
        key=lambda x: (
            x["data"],
            float(x.get("score_risco") or 0),
        ),
        reverse=True,
    )

    status_total: dict[str, int] = defaultdict(int)
    por_data: dict[str, dict[str, Any]] = {}

    for item in payload:
        status = item["status_risco"]
        status_total[status] += 1

        d = item["data"]
        bucket = por_data.setdefault(
            d,
            {
                "linhas": 0,
                "status": defaultdict(int),
                "divergencias": 0,
            },
        )
        bucket["linhas"] += 1
        bucket["status"][status] += 1
        bucket["divergencias"] += 1 if item["divergencia_regra"] else 0

    unmatched_unique = []
    seen_unmatched = set()

    for x in unmatched_all:
        key = (x["codigo_base"], x.get("nome_base"), x.get("arquivo"))
        if key not in seen_unmatched:
            seen_unmatched.add(key)
            unmatched_unique.append(x)

    summary: dict[str, Any] = {
        "arquivos_capotamento": arquivos_info,
        "qtd_arquivos_capotamento": len(capotamento_paths),
        "qtd_arquivos_gestao": len(gestao_paths),
        "linhas_gestao": linhas_gestao,
        "linhas": len(payload),
        "datas": sorted(por_data.keys()),
        "por_data": por_data,
        "sem_gestao": unmatched_unique,
        "codigos_gestao_duplicados": duplicated_gestao,
        "status": dict(status_total),
        "divergencias": sum(
            1 for x in payload if x["divergencia_regra"]
        ),
    }

    summary["top_10"] = [
        {
            "data": x["data"],
            "base": x["nome_base"],
            "uf": x["uf"],
            "score": x["score_risco"],
            "janela": x["janela_critica"],
            "status": x["status_risco"],
        }
        for x in sorted(
            payload,
            key=lambda x: float(x.get("score_risco") or 0),
            reverse=True,
        )[:10]
    ]

    return payload, summary


def upload(payload: list[dict[str, Any]], batch_size: int = 200) -> None:
    if not payload:
        return

    from db import get_supabase

    sb = get_supabase()

    for start in range(0, len(payload), batch_size):
        batch = payload[start:start + batch_size]
        sb.table("capotamento_diario").upsert(
            batch,
            on_conflict="data,codigo_base",
        ).execute()


def print_summary(summary: dict[str, Any]) -> None:
    print("=" * 80)
    print("IMPORTAÇÃO CAPOTAMENTO - J&T | LOTE")
    print("=" * 80)
    print(f"Arquivos Capotamento:         {summary['qtd_arquivos_capotamento']}")
    print(f"Arquivos Gestão:              {summary['qtd_arquivos_gestao']}")
    print(f"Registros Gestão consolidados: {summary['linhas_gestao']:,}")
    print(f"Registros Capotamento finais: {summary['linhas']:,}")
    print(f"Datas processadas:            {', '.join(summary['datas']) or '-'}")
    print(f"Sem match na Gestão:          {len(summary['sem_gestao'])}")
    print(f"Códigos duplicados Gestão:    {len(summary['codigos_gestao_duplicados'])}")
    print(f"Divergências regra x fonte:   {summary['divergencias']}")

    print("\nArquivos de Capotamento:")
    for x in summary["arquivos_capotamento"]:
        datas = ", ".join(x["datas"]) if x["datas"] else "-"
        print(f"  - {x['arquivo']} | {x['linhas']} linhas | {datas}")

    print("\nResumo por data:")
    for data_ref in summary["datas"]:
        x = summary["por_data"][data_ref]
        print(f"\n  {data_ref} | {x['linhas']} bases")
        for status, qtd in x["status"].items():
            print(f"    {status:<24} {qtd:>5}")
        print(f"    {'DIVERGÊNCIAS':<24} {x['divergencias']:>5}")

    print("\nTop 10 risco do lote:")
    for i, x in enumerate(summary["top_10"], 1):
        print(
            f"  {i:>2}. {x['data']} | "
            f"{x['base']:<24} {str(x['uf'] or ''):<2} "
            f"{x['score'] * 100:6.1f}% "
            f"{x['janela']:<3} {x['status']}"
        )

    if summary["sem_gestao"]:
        print("\nBases sem Gestão:")
        for x in summary["sem_gestao"]:
            print(
                f"  {x['codigo_base']} - "
                f"{x['nome_base']} "
                f"({x['arquivo']})"
            )

    print("=" * 80)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Importa vários arquivos Alerta de Capotamento + "
            "vários arquivos Gestão para o Supabase."
        )
    )

    parser.add_argument(
        "capotamento",
        nargs="+",
        help=(
            "Um ou mais arquivos Excel de Alerta de Capotamento. "
            "Use aspas quando houver espaços no nome."
        ),
    )

    parser.add_argument(
        "--gestao",
        "-g",
        nargs="+",
        help=(
            "Um ou mais arquivos Excel de Gestão de colaboradores. "
            "Ex.: -g \"Gestão atual.xlsx\" \"Gestão antiga.xlsx\""
        ),
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Valida/calcula sem enviar ao Supabase.",
    )

    args = parser.parse_args()

    if args.gestao:
        capotamento_paths = args.capotamento
        gestao_paths = args.gestao
    else:
        if len(args.capotamento) < 2:
            parser.error(
                "Informe pelo menos 1 arquivo de Capotamento e 1 de Gestão. "
                "Para vários arquivos, prefira usar --gestao."
            )

        capotamento_paths = args.capotamento[:-1]
        gestao_paths = [args.capotamento[-1]]

    payload, summary = parse_files(
        capotamento_paths,
        gestao_paths,
    )

    print_summary(summary)

    if args.dry_run:
        print("DRY-RUN: nada foi enviado ao Supabase.")
        return

    upload(payload)
    print(
        f"Importação concluída com sucesso. "
        f"{len(payload):,} registros processados."
    )


if __name__ == "__main__":
    main()
