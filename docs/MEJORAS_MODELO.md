# Análisis crítico del modelo de datos

Modelo analizado: `sql/01_ddl_electoral.sql`. Cada problema está conectado con lo que se observó al cargar la data real (ver `DECISIONES.md`).

## 1. Problemas identificados

Ordenados por impacto (mayor a menor).

| # | Problema | Tabla / columna afectada | Consecuencia concreta | Severidad |
|---|---|---|---|---|
| 1 | Sin llaves únicas sobre la llave natural | `centros_votacion.codigo_centro_votacion`, `mesas_votacion.codigo_mesa`, `resultados_elecciones` (elección+vuelta+mesa+partido) | Una reejecución duplica todo y el dashboard suma doble. Impide `ON CONFLICT`: la idempotencia tuvo que resolverse con reemplazo total bajo `LOCK`, que bloquea lecturas durante la carga. El CSV traía `0104001` dos veces con datos distintos y la base lo habría aceptado. | Alta |
| 2 | Sin llaves foráneas | todas las relaciones de `BASE_DE_DATOS.md` | El centro `0104999` (inexistente) entraría a resultados y padrón; los cruces por geografía pierden esas filas sin aviso. Toda la integridad depende de que el ETL valide. | Alta |
| 3 | Todo es `VARCHAR(50)`: votos, fechas, coordenadas, años | casi todas las columnas | `SUM(votos_validos)` exige `CAST` y falla con un solo valor no numérico; `'10' < '9'` en texto, así que los ordenamientos y rangos de fecha son incorrectos; `16,489162` es válido como texto. No hay índices útiles por rango. | Alta |
| 4 | El padrón se **sobrescribe**: no hay historia | `empadronados` | Tras un traslado se pierde el centro y la mesa anteriores y la fecha del cambio. No se puede responder "¿cuántos se trasladaron este mes?" ni reconstruir el padrón de una fecha pasada. Un fallecido que reaparece activo no deja rastro. Mitigado con `etl.empadronados_snapshot`. | Alta |
| 5 | Granularidad mezclada: totales de mesa repetidos en cada fila de partido | `resultados_elecciones.votos_nulos`, `votos_en_blanco`, `total_empadronados_mesa`, `total_votantes_mesa` | `SUM(total_votantes_mesa)` multiplica por el número de partidos; obliga a `DISTINCT`/`MAX` en cada consulta. Se encontraron 45 mesas con totales distintos entre sus propias filas: la redundancia permite contradicciones. | Alta |
| 6 | Catálogos sin normalizar: nombres geográficos y partido como texto libre repetido | `nombre_departamento`, `nombre_municipio`, `partido`, `candidato`, `area`, `sexo`, `estado_registro`, `rango_edad` | 36 grafías para 8 departamentos; `une`/`UNE`/`U.N.E.` produjeron dos filas por mesa. Sin `CHECK` ni tablas de dominio, cualquier valor nuevo rompe los filtros del dashboard. | Alta |
| 7 | Sin dimensión de elección | `anio_eleccion`, `tipo_eleccion`, `vuelta` repetidos | `vuelta` vacía para legislativa hace que la llave natural tenga NULL (y `NULL <> NULL` en una restricción única). No hay lugar para la fecha del evento ni el estado (oficial/preliminar). | Media |
| 8 | `mesas_votacion` sin atributos y sin relación declarada con el padrón | `mesas_votacion` | La mesa existe solo como código; `numero_mesa` es derivable del código (redundante). No se puede guardar la capacidad por mesa, que es la base del análisis de saturación. | Media |
| 9 | Centros sin versión: `anio_vigencia` como atributo y no como vigencia | `centros_votacion` | Un centro que cambia de mesas entre 2019 y 2023 solo puede tener una fila (o duplicarse sin control). Las correcciones sobrescriben lo histórico. | Media |
| 10 | Trazabilidad débil | `fechaCarga` como texto, `carga_log` libre de 255 caracteres | No se sabe qué ejecución ni qué archivo generó una fila; no hay métricas ni watermark. Se agregó el esquema `etl` para cubrirlo. | Media |
| 11 | Mezcla de convenciones de nombres | `fechaCarga` (camelCase) vs snake_case | Sin comillas PostgreSQL la convierte en `fechacarga`; con comillas falla. Fuente de errores en el ETL. | Baja |
| 12 | Sin índices además de las PK | columnas de cruce y filtro | Las consultas del dashboard por departamento, municipio, elección o estado hacen recorridos completos. Con 9 millones de empadronados se vuelve el cuello de botella. | Media |
| 13 | Sentinelas en lugar de NULL / sin validación geográfica | `codigo_departamento = '99'`, `capacidad_maxima = 0` | Un centro en "DEPARTAMENTO DESCONOCIDO" aparece como un departamento más; capacidad 0 hace que la saturación dé infinito. | Baja |
| 14 | `created_at` sin `updated_at` y `DROP SCHEMA ... CASCADE` en el DDL de producción | `empadronados`, script | No se distingue cuándo cambió un registro; reejecutar el DDL borra producción. | Baja |

## 2. Modelo propuesto

Enfoque **por capas** con un núcleo **dimensional**:

- **staging** (`stg`): copia cruda de cada archivo, todo texto, más `id_ejecucion` y `linea_origen`. Permite reprocesar sin releer el archivo.
- **core** (`core`): dimensiones y hechos tipados, con llaves naturales únicas, FK y `CHECK`. Es lo que el ETL garantiza.
- **control** (`etl`): ejecuciones, watermark y cuarentena (ya implementado).

Se elige dimensional porque el consumo es analítico (agregaciones por geografía, elección, partido y fecha) y porque separa los dos granos que hoy están mezclados (partido-mesa y mesa).

El DDL ejecutable de esta propuesta está en [`sql/99_propuesta_mejoras.sql`](../sql/99_propuesta_mejoras.sql). Crea el esquema `core` en paralelo, sin tocar `electoral`, e incluye una vista de compatibilidad para la migración.

### 2.1 DER propuesto

```mermaid
erDiagram
    DIM_DEPARTAMENTO ||--o{ DIM_MUNICIPIO : contiene
    DIM_MUNICIPIO ||--o{ DIM_CENTRO : contiene
    DIM_CENTRO ||--o{ DIM_MESA : contiene
    DIM_ELECCION ||--o{ FACT_MESA_ELECCION : ""
    DIM_MESA ||--o{ FACT_MESA_ELECCION : ""
    FACT_MESA_ELECCION ||--o{ FACT_VOTOS_PARTIDO : ""
    DIM_PARTIDO ||--o{ FACT_VOTOS_PARTIDO : ""
    DIM_MESA ||--o{ EMPADRONADO_HIST : "asignado a"
    DIM_EMPADRONADO ||--o{ EMPADRONADO_HIST : versiones

    DIM_DEPARTAMENTO { char2 codigo_departamento PK  varchar nombre }
    DIM_MUNICIPIO { char4 codigo_municipio PK  char2 codigo_departamento FK  varchar nombre }
    DIM_CENTRO {
        bigint centro_sk PK
        varchar codigo_centro_votacion "UNIQUE(codigo, valido_desde)"
        char4 codigo_municipio FK
        varchar nombre_centro
        varchar direccion
        smallint zona
        area_enum area
        numeric latitud "CHECK -90..90"
        numeric longitud
        smallint cantidad_mesas
        int capacidad_maxima "CHECK > 0"
        date valido_desde
        date valido_hasta
        bool es_actual
    }
    DIM_MESA { varchar codigo_mesa PK  varchar codigo_centro_votacion FK  smallint numero_mesa  int capacidad }
    DIM_ELECCION { int eleccion_id PK  smallint anio  tipo_enum tipo  smallint vuelta "NOT NULL default 1"  date fecha }
    DIM_PARTIDO { int partido_id PK  varchar sigla UNIQUE  varchar nombre }
    FACT_MESA_ELECCION {
        int eleccion_id PK
        varchar codigo_mesa PK
        int votos_nulos "CHECK >= 0"
        int votos_en_blanco
        int total_empadronados
        int total_votantes "CHECK <= total_empadronados"
        bigint id_ejecucion
    }
    FACT_VOTOS_PARTIDO {
        int eleccion_id PK
        varchar codigo_mesa PK
        int partido_id PK
        varchar candidato
        int votos_validos "CHECK >= 0"
    }
    DIM_EMPADRONADO { varchar id_empadronado PK  sexo_enum sexo  rango_enum rango_edad  date fecha_inscripcion }
    EMPADRONADO_HIST {
        varchar id_empadronado PK
        date valido_desde PK
        date valido_hasta
        varchar codigo_mesa FK
        estado_enum estado_registro
        char4 codigo_municipio_residencia FK
        bool es_actual
        bigint id_ejecucion
    }
```

### 2.2 Cambios clave respecto al modelo actual

| # | Cambio | Qué resuelve | Costo o riesgo |
|---|---|---|---|
| 1 | `UNIQUE` en llaves naturales y `vuelta NOT NULL DEFAULT 1` | Idempotencia con `ON CONFLICT` sin bloquear la tabla (problemas 1 y 7) | Requiere deduplicar antes de crear el índice |
| 2 | FK en toda la jerarquía geográfica y mesa | Huérfanos rechazados por la base, no solo por el ETL (2) | Orden de carga obligatorio (catálogos primero) |
| 3 | Tipos correctos (`INT`, `DATE`, `NUMERIC(9,6)`, `ENUM`/catálogos) + `CHECK` | Agregaciones sin `CAST`, reglas de negocio en la base (3, 6) | Migración de tipos con validación previa |
| 4 | Separar `fact_mesa_eleccion` de `fact_votos_partido` | Totales de mesa una sola vez; sumas correctas (5) | Las consultas actuales cambian; se cubre con vista de compatibilidad |
| 5 | `empadronado_hist` SCD tipo 2 y `dim_centro` versionado | Historia de traslados y bajas, padrón a cualquier fecha (4, 9) | Más filas; consultas del "padrón actual" usan `es_actual` (índice parcial) |
| 6 | Catálogos `dim_partido`, `dim_departamento`, `dim_municipio` | Una sola grafía; el dashboard filtra por id (6) | Mantenimiento del catálogo |
| 7 | `id_ejecucion` en cada hecho y esquema `etl` | Saber qué carga produjo cada fila (10) | Mínimo |
| 8 | Índices: `(codigo_municipio)`, `(eleccion_id)`, parcial `WHERE es_actual` en historial, `(estado_registro)` | Consultas del dashboard por geografía y estado (12) | Escritura un poco más lenta |

### 2.3 Historización

- **Empadronado (SCD tipo 2):** cada cambio de mesa, centro o estado cierra la versión vigente (`valido_hasta = fecha - 1`, `es_actual = false`) y abre una nueva. La carga diaria compara contra la versión actual igual que hoy lo hace `etl.empadronados_snapshot`.
- **Centro (SCD tipo 2 por vigencia):** `anio_vigencia` pasa a `valido_desde/valido_hasta`, de modo que 2019 y 2023 conviven y los resultados de cada elección se cruzan con el centro vigente en su fecha.

Preguntas que habilita y hoy no se pueden responder:

- ¿Cuántos traslados recibió cada centro en la última semana y desde dónde vienen? (saturación)
- ¿Cuál era el padrón de una mesa el día de la elección versus hoy?
- ¿Cuánto tiempo pasa entre la inscripción y el primer traslado? ¿Hay registros que vuelven de `fallecido` a `activo` (alerta de calidad o fraude)?
- ¿Cambió la capacidad de un centro entre elecciones y cómo afectó la participación?

## 3. Plan de migración

Patrón **expand / migrate / contract**: el modelo nuevo se construye al lado y el dashboard se cambia en un solo paso reversible.

| Paso | Acción | Reversible | Riesgo |
|---|---|---|---|
| 1 | Crear esquemas `core` y `etl` con las tablas nuevas, sin tocar `electoral` | Sí (drop del esquema) | Nulo: nadie lo consume |
| 2 | El ETL escribe en **ambos** modelos (doble escritura) en la misma transacción | Sí (apagar por configuración) | Duplica el tiempo de carga |
| 3 | Backfill de `core` desde `electoral` y desde `etl.empadronados_snapshot` para la historia | Sí | Datos inválidos: van a cuarentena, no bloquean |
| 4 | Conciliación diaria: conteos y sumas por departamento/elección iguales entre modelos | — | Detecta diferencias antes del cambio |
| 5 | Crear vistas `electoral_v2.*` con la forma exacta de las tablas viejas sobre `core` | Sí | Validar desempeño de las vistas |
| 6 | Cambiar el dashboard a las vistas (o al modelo nuevo) | Sí: volver a apuntar a `electoral` | Ventana corta; se hace fuera de horario |
| 7 | Tras un periodo de estabilidad, apagar la doble escritura y dejar `electoral` como vistas | Sí mientras se conserve un respaldo | Consumidores no inventariados; se detectan con `pg_stat_statements` |
| 8 | Eliminar las tablas viejas | No | Solo después de 1 ciclo electoral sin uso |

**¿Qué haría primero?** Las llaves únicas + FK (cambios 1 y 2): son baratas, no cambian la forma que consume el dashboard y eliminan de raíz el riesgo de duplicar resultados, que es el error más visible para el usuario final.
