-- Esquema de control del ETL: no modifica el modelo entregado en 01_ddl_electoral.sql.
CREATE SCHEMA IF NOT EXISTS etl;

CREATE TABLE IF NOT EXISTS etl.ejecuciones (
    id_ejecucion   BIGSERIAL PRIMARY KEY,
    pipeline       VARCHAR(100) NOT NULL,
    fecha_proceso  DATE,
    archivo        TEXT,
    hash_archivo   CHAR(64),
    estado         VARCHAR(20)  NOT NULL CHECK (estado IN ('en_curso', 'ok', 'error')),
    leidos         INTEGER,
    transformados  INTEGER,
    cargados       INTEGER,
    rechazados     INTEGER,
    detalle        JSONB,
    error          TEXT,
    inicio         TIMESTAMPTZ  NOT NULL DEFAULT now(),
    fin            TIMESTAMPTZ,
    segundos       NUMERIC(10, 2)
);

-- Rechazos con el registro original para poder corregir y reprocesar.
CREATE TABLE IF NOT EXISTS etl.cuarentena (
    id_cuarentena  BIGSERIAL PRIMARY KEY,
    id_ejecucion   BIGINT REFERENCES etl.ejecuciones (id_ejecucion),
    pipeline       VARCHAR(100) NOT NULL,
    fecha_proceso  DATE,
    linea_origen   INTEGER,
    regla          VARCHAR(100) NOT NULL,
    registro       JSONB        NOT NULL,
    creado         TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_cuarentena_pipeline_fecha ON etl.cuarentena (pipeline, fecha_proceso);

-- Marca de agua por fuente incremental.
CREATE TABLE IF NOT EXISTS etl.watermark (
    fuente          VARCHAR(100) PRIMARY KEY,
    ultima_fecha    DATE        NOT NULL,
    id_ejecucion    BIGINT REFERENCES etl.ejecuciones (id_ejecucion),
    actualizado     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Fotografía diaria del padrón: conserva la historia que el modelo actual sobrescribe.
CREATE TABLE IF NOT EXISTS etl.empadronados_snapshot (
    fecha_proceso                   DATE        NOT NULL,
    id_empadronado                  VARCHAR(50) NOT NULL,
    codigo_centro_votacion          VARCHAR(50),
    codigo_mesa                     VARCHAR(50),
    estado_registro                 VARCHAR(50),
    tipo_movimiento                 VARCHAR(20) NOT NULL,
    PRIMARY KEY (fecha_proceso, id_empadronado)
);
