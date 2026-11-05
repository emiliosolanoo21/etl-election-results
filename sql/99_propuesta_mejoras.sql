-- Propuesta de modelo (docs/MEJORAS_MODELO.md): esquema core paralelo, no reemplaza electoral.
CREATE SCHEMA IF NOT EXISTS core;

CREATE TYPE core.area_enum AS ENUM ('urbana', 'rural');
CREATE TYPE core.tipo_eleccion_enum AS ENUM ('presidencial', 'legislativa', 'municipal');
CREATE TYPE core.sexo_enum AS ENUM ('M', 'F');
CREATE TYPE core.rango_edad_enum AS ENUM ('18-25', '26-35', '36-45', '46-60', '61+');
CREATE TYPE core.estado_registro_enum AS ENUM ('activo', 'suspendido', 'fallecido', 'baja_por_ausencia');

CREATE TABLE core.dim_departamento (
    codigo_departamento CHAR(2) PRIMARY KEY CHECK (codigo_departamento ~ '^[0-9]{2}$'),
    nombre              VARCHAR(100) NOT NULL UNIQUE
);

CREATE TABLE core.dim_municipio (
    codigo_municipio    CHAR(4) PRIMARY KEY CHECK (codigo_municipio ~ '^[0-9]{4}$'),
    codigo_departamento CHAR(2) NOT NULL REFERENCES core.dim_departamento,
    nombre              VARCHAR(100) NOT NULL,
    CHECK (left(codigo_municipio, 2) = codigo_departamento)
);

-- Centro versionado (SCD2): conviven las vigencias 2019 y 2023.
CREATE TABLE core.dim_centro (
    centro_sk              BIGSERIAL PRIMARY KEY,
    codigo_centro_votacion CHAR(7) NOT NULL,
    codigo_municipio       CHAR(4) NOT NULL REFERENCES core.dim_municipio,
    nombre_centro          VARCHAR(255) NOT NULL,
    direccion              VARCHAR(255),
    zona                   SMALLINT CHECK (zona BETWEEN 1 AND 25),
    area                   core.area_enum,
    latitud                NUMERIC(9, 6) CHECK (latitud BETWEEN -90 AND 90),
    longitud               NUMERIC(9, 6) CHECK (longitud BETWEEN -180 AND 180),
    cantidad_mesas         SMALLINT NOT NULL CHECK (cantidad_mesas > 0),
    capacidad_maxima       INTEGER CHECK (capacidad_maxima > 0),
    valido_desde           DATE NOT NULL,
    valido_hasta           DATE,
    es_actual              BOOLEAN NOT NULL DEFAULT true,
    id_ejecucion           BIGINT,
    UNIQUE (codigo_centro_votacion, valido_desde),
    CHECK (left(codigo_centro_votacion, 4) = codigo_municipio)
);

CREATE UNIQUE INDEX ux_centro_actual ON core.dim_centro (codigo_centro_votacion) WHERE es_actual;

CREATE TABLE core.dim_mesa (
    codigo_mesa            VARCHAR(12) PRIMARY KEY,
    codigo_centro_votacion CHAR(7) NOT NULL,
    numero_mesa            SMALLINT NOT NULL CHECK (numero_mesa > 0),
    capacidad              INTEGER CHECK (capacidad > 0),
    CHECK (codigo_mesa = codigo_centro_votacion || '-' || lpad(numero_mesa::text, 2, '0'))
);

CREATE TABLE core.dim_eleccion (
    eleccion_id SERIAL PRIMARY KEY,
    anio        SMALLINT NOT NULL CHECK (anio BETWEEN 1985 AND 2100),
    tipo        core.tipo_eleccion_enum NOT NULL,
    vuelta      SMALLINT NOT NULL DEFAULT 1 CHECK (vuelta IN (1, 2)),
    fecha       DATE,
    UNIQUE (anio, tipo, vuelta)
);

CREATE TABLE core.dim_partido (
    partido_id SERIAL PRIMARY KEY,
    sigla      VARCHAR(20) NOT NULL UNIQUE,
    nombre     VARCHAR(255)
);

-- Grano mesa-elección: los totales se guardan una sola vez.
CREATE TABLE core.fact_mesa_eleccion (
    eleccion_id        INTEGER NOT NULL REFERENCES core.dim_eleccion,
    codigo_mesa        VARCHAR(12) NOT NULL REFERENCES core.dim_mesa,
    votos_nulos        INTEGER NOT NULL CHECK (votos_nulos >= 0),
    votos_en_blanco    INTEGER NOT NULL CHECK (votos_en_blanco >= 0),
    total_empadronados INTEGER NOT NULL CHECK (total_empadronados >= 0),
    total_votantes     INTEGER NOT NULL CHECK (total_votantes >= 0),
    id_ejecucion       BIGINT,
    PRIMARY KEY (eleccion_id, codigo_mesa),
    CHECK (total_votantes <= total_empadronados)
);

-- Grano partido-mesa-elección.
CREATE TABLE core.fact_votos_partido (
    eleccion_id   INTEGER NOT NULL,
    codigo_mesa   VARCHAR(12) NOT NULL,
    partido_id    INTEGER NOT NULL REFERENCES core.dim_partido,
    candidato     VARCHAR(255),
    votos_validos INTEGER NOT NULL CHECK (votos_validos >= 0),
    id_ejecucion  BIGINT,
    PRIMARY KEY (eleccion_id, codigo_mesa, partido_id),
    FOREIGN KEY (eleccion_id, codigo_mesa) REFERENCES core.fact_mesa_eleccion
);

CREATE TABLE core.dim_empadronado (
    id_empadronado    VARCHAR(20) PRIMARY KEY,
    sexo              core.sexo_enum,
    rango_edad        core.rango_edad_enum,
    fecha_inscripcion DATE CHECK (fecha_inscripcion >= DATE '1900-01-01')
);

-- Historia de asignación y estado (SCD2): resuelve la sobrescritura del padrón.
CREATE TABLE core.empadronado_hist (
    id_empadronado              VARCHAR(20) NOT NULL REFERENCES core.dim_empadronado,
    valido_desde                DATE NOT NULL,
    valido_hasta                DATE,
    codigo_mesa                 VARCHAR(12) NOT NULL REFERENCES core.dim_mesa,
    estado_registro             core.estado_registro_enum NOT NULL,
    codigo_municipio_residencia CHAR(4) REFERENCES core.dim_municipio,
    es_actual                   BOOLEAN NOT NULL DEFAULT true,
    id_ejecucion                BIGINT,
    PRIMARY KEY (id_empadronado, valido_desde),
    CHECK (valido_hasta IS NULL OR valido_hasta >= valido_desde)
);

CREATE UNIQUE INDEX ux_empadronado_actual ON core.empadronado_hist (id_empadronado) WHERE es_actual;
CREATE INDEX ix_empadronado_mesa_actual ON core.empadronado_hist (codigo_mesa) WHERE es_actual;
CREATE INDEX ix_mesa_centro ON core.dim_mesa (codigo_centro_votacion);
CREATE INDEX ix_votos_partido ON core.fact_votos_partido (partido_id);

-- Vista de compatibilidad: misma forma que electoral.empadronados para migrar sin cortar el dashboard.
CREATE VIEW core.v_empadronados_actual AS
SELECT h.id_empadronado,
       m.codigo_centro_votacion,
       h.codigo_mesa,
       d.rango_edad::text AS rango_edad,
       d.sexo::text AS sexo,
       left(h.codigo_municipio_residencia, 2) AS codigo_departamento_residencia,
       h.codigo_municipio_residencia,
       h.estado_registro::text AS estado_registro,
       d.fecha_inscripcion,
       h.valido_desde AS fecha_ultima_actualizacion
FROM core.empadronado_hist h
JOIN core.dim_empadronado d USING (id_empadronado)
JOIN core.dim_mesa m USING (codigo_mesa)
WHERE h.es_actual;
