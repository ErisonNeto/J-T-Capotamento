# J&T | Dashboard de Capotamento

Mesmo padrão do dashboard SLA: **FastAPI + HTML/CSS/JS + Supabase**.

## 1. Estrutura

- `main.py` — backend/API e tela
- `importar_excel.py` — ETL diário do Excel de Capotamento + Gestão
- `db.py` — conexão Supabase
- `schema.sql` — tabela/índices
- `templates/index.html` — dashboard em uma tela
- `static/style.css` — layout
- `static/app.js` — filtros, ranking, detalhe e gráficos

## 2. Criar a tabela

No Supabase SQL Editor, execute `schema.sql`.

> O backend usa `SUPABASE_SERVICE_ROLE_KEY` apenas no servidor. Nunca coloque essa chave no JavaScript.

## 3. Ambiente local

```powershell
cd C:\Users\JT074\Documents\CAPOTAMENTO
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

Preencha `.env` com a URL e Service Role do seu Supabase.

## 4. Validar o Excel sem enviar

```powershell
python importar_excel.py "Alerta de Capotamento (Novo).xlsx" "Gestão de colaboradores.xlsx" --dry-run
```

## 5. Importar para o Supabase

```powershell
python importar_excel.py "Alerta de Capotamento (Novo).xlsx" "Gestão de colaboradores.xlsx"
```

O `upsert` usa `(data, codigo_base)`, então reimportar o mesmo dia atualiza os dados em vez de duplicar.

## 6. Subir o dashboard

```powershell
python -m uvicorn main:app --reload --port 8001
```

Abra:

`http://127.0.0.1:8001`

## Regra oficial usada

- 1D: 500 retidos + índice > 0,50 → Alerta
- 3D: 800 + índice > 0,80 → Capotamento
- 5D: 1.000 + índice > 1,00 → Capotamento
- 7D: 1.200 + índice > 1,20 → Capotamento
- 10D: 1.500 + índice > 1,50 → Capotamento

O **status oficial** é preservado conforme as colunas do arquivo-fonte. O sistema também recalcula a regra e marca `divergencia_regra` quando fonte e cálculo não coincidem.

## Pré-alerta interno

O score de cada janela é:

`MIN(retidos / limite_retidos, indice / limite_indice)`

A base usa o maior score entre 1D, 3D, 5D, 7D e 10D:

- <60%: NORMAL
- 60–79,99%: MONITORAR
- 80–89,99%: PRÉ-ALERTA
- ≥90%: PRÉ-ALERTA CRÍTICO
- ALERTA/CAPOTADA: prevalece o status oficial da fonte
