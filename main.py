from __future__ import annotations

import csv
import io
import os
import traceback
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from db import get_supabase


app = FastAPI(title="J&T | Capotamento")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

STATUS_ORDER = {
    "CAPOTADA": 6,
    "ALERTA": 5,
    "PRÉ-ALERTA CRÍTICO": 4,
    "PRÉ-ALERTA": 3,
    "MONITORAR": 2,
    "NORMAL": 1,
}


def api_error(endpoint: str, exc: Exception) -> JSONResponse:
    print(f"\n{'=' * 72}")
    print(f"ERRO EM {endpoint}")
    print(f"Tipo: {type(exc).__name__}")
    print(f"Mensagem: {exc}")
    traceback.print_exc()
    print(f"{'=' * 72}\n")
    return JSONResponse(
        status_code=500,
        content={
            "ok": False,
            "endpoint": endpoint,
            "tipo": type(exc).__name__,
            "erro": str(exc),
        },
    )


def latest_date() -> str | None:
    sb = get_supabase()
    result = (
        sb.table("capotamento_diario")
        .select("data")
        .order("data", desc=True)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    return str(rows[0]["data"]) if rows else None


def resolve_date(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or latest_date()


def get_sc(row: dict[str, Any]) -> str:
    """S/C: usa Coordenador quando existe; caso contrário, Supervisor."""
    return str(row.get("coordenador") or row.get("supervisor") or "").strip()


def query_day(
    data_ref: str,
    uf: str | None = None,
    sc: str | None = None,
    rm: str | None = None,
) -> list[dict[str, Any]]:
    sb = get_supabase()
    q = sb.table("capotamento_diario").select("*").eq("data", data_ref)

    if uf:
        q = q.eq("uf", uf)
    if rm:
        q = q.eq("rm", rm)

    rows = q.execute().data or []

    if sc:
        rows = [r for r in rows if get_sc(r) == sc]

    return rows


def unique_values(rows: list[dict[str, Any]], key: str) -> list[str]:
    return sorted(
        {
            str(r.get(key)).strip()
            for r in rows
            if r.get(key) not in (None, "")
        }
    )


def unique_sc(rows: list[dict[str, Any]]) -> list[str]:
    return sorted({get_sc(r) for r in rows if get_sc(r)})


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={},
    )


@app.get("/api/health")
async def api_health():
    try:
        sb = get_supabase()
        result = sb.table("capotamento_diario").select("data").limit(1).execute()
        return {
            "ok": True,
            "supabase": True,
            "tem_dados": bool(result.data),
        }
    except Exception as exc:
        return api_error("/api/health", exc)


@app.get("/api/datas")
async def api_datas():
    try:
        sb = get_supabase()
        response = (
            sb.table("capotamento_diario")
            .select("data")
            .order("data", desc=True)
            .execute()
        )
        rows = response.data or []
        datas = sorted(
            {str(r.get("data")) for r in rows if r.get("data")},
            reverse=True,
        )
        return {
            "ok": True,
            "datas": datas,
            "registros_lidos": len(rows),
        }
    except Exception as exc:
        return api_error("/api/datas", exc)


@app.get("/api/filtros")
async def api_filtros(data: str | None = None):
    try:
        data_ref = resolve_date(data)
        if not data_ref:
            return {
                "data": None,
                "ufs": [],
                "rms": [],
                "scs": [],
            }

        rows = query_day(data_ref)
        return {
            "data": data_ref,
            "ufs": unique_values(rows, "uf"),
            "rms": unique_values(rows, "rm"),
            "scs": unique_sc(rows),
        }
    except Exception as exc:
        return api_error("/api/filtros", exc)


@app.get("/api/resumo")
async def api_resumo(
    data: str | None = None,
    uf: str | None = None,
    rm: str | None = None,
    sc: str | None = None,
):
    try:
        data_ref = resolve_date(data)
        if not data_ref:
            return {
                "data": None,
                "total": 0,
                "normal": 0,
                "monitorar": 0,
                "pre_alerta": 0,
                "pre_critico": 0,
                "alerta": 0,
                "capotadas": 0,
                "retidos_10d": 0,
                "reincidentes_30d": 0,
                "divergencias": 0,
            }

        rows = query_day(data_ref, uf, sc, rm)
        count: defaultdict[str, int] = defaultdict(int)
        retidos = 0.0
        divergencias = 0
        reincidentes = 0

        for r in rows:
            status = str(r.get("status_risco") or "NORMAL")
            count[status] += 1
            retidos += float(r.get("retidos_10d") or 0)
            divergencias += 1 if r.get("divergencia_regra") else 0
            reincidentes += 1 if int(r.get("capotamentos_30d") or 0) > 0 else 0

        return {
            "data": data_ref,
            "total": len(rows),
            "normal": count["NORMAL"],
            "monitorar": count["MONITORAR"],
            "pre_alerta": count["PRÉ-ALERTA"],
            "pre_critico": count["PRÉ-ALERTA CRÍTICO"],
            "alerta": count["ALERTA"],
            "capotadas": count["CAPOTADA"],
            "retidos_10d": round(retidos),
            "reincidentes_30d": reincidentes,
            "divergencias": divergencias,
        }
    except Exception as exc:
        return api_error("/api/resumo", exc)


@app.get("/api/ranking")
async def api_ranking(
    data: str | None = None,
    uf: str | None = None,
    rm: str | None = None,
    sc: str | None = None,
    status: str | None = None,
    limit: int = Query(100, ge=1, le=500),
):
    try:
        data_ref = resolve_date(data)
        if not data_ref:
            return {"data": None, "rows": [], "total": 0}

        rows = query_day(data_ref, uf, sc, rm)

        if status:
            rows = [r for r in rows if r.get("status_risco") == status]

        rows.sort(
            key=lambda r: (
                STATUS_ORDER.get(str(r.get("status_risco") or "NORMAL"), 0),
                float(r.get("score_risco") or 0),
            ),
            reverse=True,
        )

        return {
            "data": data_ref,
            "rows": rows[:limit],
            "total": len(rows),
        }
    except Exception as exc:
        return api_error("/api/ranking", exc)


@app.get("/api/evolucao/{codigo_base}")
async def api_evolucao(
    codigo_base: int,
    dias: int = Query(30, ge=7, le=180),
):
    try:
        sb = get_supabase()
        fim = latest_date()
        if not fim:
            return {"codigo_base": codigo_base, "rows": []}

        inicio = (date.fromisoformat(fim) - timedelta(days=dias - 1)).isoformat()

        result = (
            sb.table("capotamento_diario")
            .select(
                "data,nome_base,retidos_1d,retidos_3d,retidos_5d,"
                "retidos_7d,retidos_10d,indice_1d,indice_3d,indice_5d,"
                "indice_7d,indice_10d,score_risco,status_risco"
            )
            .eq("codigo_base", codigo_base)
            .gte("data", inicio)
            .lte("data", fim)
            .order("data")
            .execute()
        )

        return {
            "codigo_base": codigo_base,
            "rows": result.data or [],
        }
    except Exception as exc:
        return api_error("/api/evolucao/{codigo_base}", exc)


@app.get("/api/gestao")
async def api_gestao(
    data: str | None = None,
    tipo: str = Query("sc", pattern="^(sc|rm)$"),
):
    try:
        data_ref = resolve_date(data)
        if not data_ref:
            return {"rows": []}

        rows = query_day(data_ref)
        groups: dict[str, dict[str, Any]] = {}

        for r in rows:
            if tipo == "sc":
                owner = get_sc(r) or "SEM RESPONSÁVEL"
            else:
                owner = str(r.get("rm") or "SEM RESPONSÁVEL").strip()

            g = groups.setdefault(
                owner,
                {
                    "responsavel": owner,
                    "bases": 0,
                    "monitorar": 0,
                    "pre_alerta": 0,
                    "pre_critico": 0,
                    "alerta": 0,
                    "capotadas": 0,
                    "retidos_10d": 0,
                    "score_max": 0.0,
                },
            )

            g["bases"] += 1
            g["retidos_10d"] += float(r.get("retidos_10d") or 0)
            g["score_max"] = max(g["score_max"], float(r.get("score_risco") or 0))

            s = r.get("status_risco")
            if s == "MONITORAR":
                g["monitorar"] += 1
            elif s == "PRÉ-ALERTA":
                g["pre_alerta"] += 1
            elif s == "PRÉ-ALERTA CRÍTICO":
                g["pre_critico"] += 1
            elif s == "ALERTA":
                g["alerta"] += 1
            elif s == "CAPOTADA":
                g["capotadas"] += 1

        out = list(groups.values())
        out.sort(
            key=lambda x: (
                x["capotadas"],
                x["alerta"],
                x["pre_critico"],
                x["score_max"],
            ),
            reverse=True,
        )

        return {
            "data": data_ref,
            "tipo": tipo,
            "rows": out,
        }
    except Exception as exc:
        return api_error("/api/gestao", exc)


@app.get("/api/exportar.csv")
async def api_exportar(
    data: str | None = None,
    uf: str | None = None,
    rm: str | None = None,
    sc: str | None = None,
):
    try:
        data_ref = resolve_date(data)
        rows = query_day(data_ref, uf, sc, rm) if data_ref else []

        output = io.StringIO()
        fields = [
            "data",
            "uf",
            "nome_base",
            "codigo_base",
            "rm",
            "coordenador",
            "supervisor",
            "status_risco",
            "janela_critica",
            "score_risco",
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
            "maior_entrega_prazo_7d",
            "alerta_fonte",
            "capotada_fonte",
            "capotamentos_30d",
            "dias_consecutivos_capotamento",
            "falta_qtd",
            "falta_indice",
        ]

        writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

        data_bytes = output.getvalue().encode("utf-8-sig")
        filename = f'capotamento_{data_ref or "sem_dados"}.csv'

        return StreamingResponse(
            io.BytesIO(data_bytes),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            },
        )
    except Exception as exc:
        return api_error("/api/exportar.csv", exc)


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8001"))
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=True,
    )
