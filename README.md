# ETL — Sistema de análisis de resultados electorales

ETL en Python que carga resultados históricos, centros de votación y el padrón diario sobre el modelo PostgreSQL entregado (`sql/01_ddl_electoral.sql`), con idempotencia, carga incremental con watermark, cuarentena de registros inválidos, métricas por ejecución y orquestación programada.

Documentos de la entrega:

- [`DECISIONES.md`](DECISIONES.md): supuestos, 23 hallazgos de calidad de datos y su tratamiento, decisiones técnicas y pendientes.
- [`docs/MEJORAS_MODELO.md`](docs/MEJORAS_MODELO.md): análisis crítico del modelo, DER propuesto y plan de migración.
- [`docs/ORQUESTACION.md`](docs/ORQUESTACION.md): estrategia de orquestación, comparación, diagrama y backfill.
- [`ENUNCIADO.md`](ENUNCIADO.md): enunciado de la prueba.

## Inicio rápido (Docker, 3 comandos)

Requisitos: Docker y Docker Compose.

```bash
cp .env.example .env                       # credenciales locales (no se versiona)
docker compose up -d postgres              # crea la base, el modelo y el esquema de control etl
docker compose run --rm etl-orchestrator   # carga histórica + todos los días del padrón pendientes
```

Para dejar programada la carga diaria (02:00, hora de Guatemala):

```bash
docker compose up -d scheduler
docker compose logs -f scheduler
```

PostgreSQL queda expuesto en `localhost:5433` (configurable con `POSTGRES_PORT`) para no chocar con una instalación local.

## Ejecución local paso a paso (sin Docker para el ETL)

### 1. Prerrequisitos

- Python 3.10+ (probado con 3.12 y 3.13)
- PostgreSQL 14+ (local o `docker compose up -d postgres`)

### 2. Entorno y variables

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

| Variable | Descripción | Valor por defecto |
|---|---|---|
| `POSTGRES_HOST` | Host de PostgreSQL | `localhost` |
| `POSTGRES_PORT` | Puerto (5433 si la base es la de Docker) | `5433` |
| `POSTGRES_DB` | Base de datos | `electoral_db` |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` | Credenciales | `etl_user` / `cambiame` |
| `LOG_LEVEL` | Nivel de log | `INFO` |
| `ETL_RETRIES`, `ETL_BACKOFF_SECONDS` | Reintentos del orquestador | `3`, `30` |
| `ALERT_WEBHOOK_URL` | Webhook opcional para alertas (Slack/Teams) | vacío |

### 3. Crear la base de datos

Con Docker se hace sola al iniciar el contenedor. Con PostgreSQL local:

```bash
createdb electoral_db
psql -d electoral_db -f sql/01_ddl_electoral.sql   # modelo entregado (sin modificar)
psql -d electoral_db -f sql/02_control_etl.sql     # esquema etl: ejecuciones, cuarentena, watermark, snapshot
```

### 4. Carga histórica (una sola vez, idempotente)

```bash
python main.py load-historico
```

Carga `centros_votacion`, luego `resultados_elecciones` y deriva `mesas_votacion`. Reejecutarla deja exactamente el mismo estado.

### 5. Carga incremental del padrón

```bash
python main.py load-empadronados --fecha 2026-03-02
python main.py load-empadronados --fecha 2026-03-03
python main.py load-empadronados --fecha 2026-03-04
```

- Reprocesar la última fecha es seguro (da 0 cambios).
- Una fecha anterior al watermark se rechaza salvo con `--force`; para reconstruir use el backfill del orquestador.

### 6. Orquestación

```bash
python orchestration/runner.py historico                                  # una vez
python orchestration/runner.py diario                                     # todo lo pendiente desde el watermark
python orchestration/runner.py diario --fecha 2026-03-04                  # una fecha
python orchestration/runner.py backfill --desde 2026-03-02 --hasta 2026-03-04
```

### 7. Pruebas (no requieren base de datos)

```bash
pytest -q
```

## Verificación de la carga

```sql
SELECT count(*) FROM electoral.centros_votacion;          -- 95
SELECT count(*) FROM electoral.resultados_elecciones;     -- 18436
SELECT count(*) FROM electoral.mesas_votacion;            -- 842
SELECT estado_registro, count(*) FROM electoral.empadronados GROUP BY 1;  -- 18277 en total
SELECT * FROM etl.watermark;                              -- empadronados | 2026-03-04

-- Métricas por ejecución
SELECT id_ejecucion, pipeline, fecha_proceso, estado, leidos, cargados, rechazados, segundos
FROM etl.ejecuciones ORDER BY id_ejecucion DESC;

-- Rechazos por regla
SELECT pipeline, regla, count(*) FROM etl.cuarentena GROUP BY 1, 2;

-- Movimientos diarios del padrón (altas, traslados, bajas)
SELECT fecha_proceso, tipo_movimiento, count(*) FROM etl.empadronados_snapshot GROUP BY 1, 2 ORDER BY 1, 2;
```

## Arquitectura

```
main.py                     CLI del ETL
orchestration/runner.py     dependencias, reintentos, catch-up, backfill, alertas
orchestration/crontab       programación diaria (supercronic)
src/config/config.yaml      fuentes, transformaciones, reglas y destinos (declarativo)
src/pipelines/factory.py    arma un Pipeline desde el YAML
src/pipelines/base_pipeline.py  extract -> transform -> validate -> load + métricas y cuarentena
src/extractors/             CSVExtractor (streaming, hash del archivo)
src/transformers/common.py  transformaciones puras y componibles
src/quality/validations.py  reglas declarativas
src/loaders/                FullLoader (staging + reemplazo atómico) e IncrementalLoader (upsert + watermark)
sql/02_control_etl.sql      esquema de control (no modifica el DDL entregado)
```

**Agregar una fuente nueva** es agregar un bloque en `sources:` de `config.yaml`. Una transformación nueva es una clase en `transformers/` y su registro en `factory.py`; un destino nuevo es una subclase de `BaseLoader`.

## Estado de los flujos

| Flujo | Modo | Comando | Estado |
|---|---|---|---|
| Centros de votación | Carga única | `load-historico` | ✅ |
| Resultados históricos + mesas | Carga única | `load-historico` | ✅ |
| Padrón (empadronados) | Incremental diaria | `load-empadronados --fecha` | ✅ |
| Orquestación | cron + runner | `orchestration/runner.py` | ✅ |
