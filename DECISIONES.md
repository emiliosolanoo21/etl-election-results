# Decisiones y supuestos

## 1. Supuestos tomados

| # | Supuesto | Motivo |
|---|---|---|
| 1 | Cada archivo del padrón es una fotografía completa; un id ausente respecto al día anterior es una baja por ausencia. | Lo indica el enunciado (2.1). En la data entregada no hay ausencias, pero el mecanismo queda implementado (`baja_por_ausencia`). |
| 2 | Ante duplicados con la misma llave natural y datos distintos, **sobrevive la última fila del archivo**. | La fuente de centros "trae correcciones ocasionales": la fila posterior se asume como corrección. Es determinista y queda contado en las métricas. |
| 3 | `une`, `UNE` y `U.N.E.` son el mismo partido (mismo candidato, Sandra Aguilar). | El candidato coincide en las tres grafías. |
| 4 | El padrón se procesa en orden de fecha. Reprocesar la fecha del watermark está permitido; una fecha anterior exige `--force`. | Aplicar una foto vieja sobre el estado actual regresaría el padrón en el tiempo. |
| 5 | Nombres geográficos canónicos: Title Case, espacios colapsados y, por código, la variante con acentos (`Peten` → `Petén`). | El código es la llave confiable; el nombre solo es descriptivo. Se conservan acentos porque son la grafía oficial. |
| 6 | `resultados_elecciones` no trae nombres de departamento/municipio: se completan desde el catálogo de centros ya cargado. | Evita columnas vacías en el dashboard sin duplicar lógica de normalización. |

## 2. Hallazgos de calidad de datos

| # | Fuente | Hallazgo | Ejemplo | Tratamiento | Motivo |
|---|---|---|---|---|---|
| 1 | centros | Nombres geográficos con mayúsculas, espacios y acentos variables (36 variantes para 8 departamentos) | `' Guatemala '`, `GUATEMALA`, `Peten`/`Petén` | `NormalizeText` + `CanonicalByKey` por código | Un solo nombre por código para agrupar en el dashboard |
| 2 | centros | `area` no estandarizada | `U`, `urbana`, `URBANA`, `R`, vacío | Mapeo a `urbana`/`rural`; vacío queda NULL | Dominio cerrado de 2 valores |
| 3 | centros | `zona` con texto `SIN ZONA` y vacíos | `SIN ZONA` | NULL | Ambos significan "sin dato" |
| 4 | centros | Latitud con coma decimal y coordenadas vacías (8) | `16,489162` | `CastNumeric` a float; vacío NULL | No se inventan coordenadas |
| 5 | centros | Duplicado exacto | `0102004` dos veces | Se elimina | Idéntico |
| 6 | centros | Duplicado con diferencias | `0104001` con 8 y 9 mesas | Sobrevive la última fila | Supuesto 2 |
| 7 | centros | Código centinela de departamento desconocido | `9999999`, depto `99`, `DEPARTAMENTO DESCONOCIDO` | Cuarentena (`valor_centinela`) | No se puede ubicar geográficamente |
| 8 | centros | `capacidad_maxima = 0` (5 centros) | | Se carga | Es dato faltante, no inválido; se señala en MEJORAS |
| 9 | resultados | 120 duplicados exactos | | Se eliminan | Idénticos |
| 10 | resultados | Partido no estandarizado que genera dos filas por mesa con votos distintos (1,682 mesas en legislativa 2019 y municipal 2023) | `une`=93 y `U.N.E.`=98 en la misma mesa | Sobrevive la última; registrado en métricas (`con_diferencias`) | No hay forma de saber cuál es la correcta; sumarlas duplicaría votos. Pendiente validar con negocio |
| 11 | resultados | `votos_validos` vacío (40 filas) | | Cuarentena (`no_nulo`) | Sin votos no hay hecho que cargar |
| 12 | resultados | Votos negativos | `-12` | Cuarentena (`no_negativo`) | Regla de negocio imposible |
| 13 | resultados | Votantes > empadronados (37 filas tras deduplicar) | mesa `0902003-01` | Cuarentena (`total_votantes<=total_empadronados`) | Viola la regla 3 de `BASE_DE_DATOS.md`. Puede ser un hallazgo real (votantes trasladados), por eso no se descarta: queda consultable en `etl.cuarentena` |
| 14 | resultados | Centro huérfano `0104999` (no existe en catálogo) | mesa `0104999-01` | Cuarentena (`huerfano`) | Cargarlo rompería los cruces por geografía |
| 15 | resultados | Validos + nulos + blancos ≠ votantes en casi todas las mesas | 5,037 de 5,057 | Se carga y se documenta | Aplicarla rechazaría el 99% de la fuente; es un problema de origen que debe escalarse |
| 16 | resultados | Totales de mesa distintos entre filas de la misma mesa (45 mesas) | | Se carga tal cual | Consecuencia del modelo que repite totales por partido (ver MEJORAS) |
| 17 | padrón | `sexo` con 6 grafías y vacíos (~14%) | `m`, `MASCULINO`, `f`, `FEMENINO` | `M`/`F`; vacío NULL | Dominio cerrado |
| 18 | padrón | `rango_edad` en dos notaciones | `18 a 25`, `mayor de 60` | `18-25`, `61+` | `mayor de 60` equivale a `61+` porque existe `46-60` |
| 19 | padrón | `estado_registro` en mayúsculas mixtas | `ACTIVO`, `Activo` | minúsculas | Dominio `activo/suspendido/fallecido` |
| 20 | padrón | Fechas en dos formatos (~1%) | `04/06/2004` | `ParseDates` a ISO | El formato `dd/mm/yyyy` se confirmó por días > 12 |
| 21 | padrón | 25 ids duplicados exactos por archivo | `E0000943` | Se eliminan | Idénticos |
| 22 | padrón | Centro `0104999` inexistente pero mesa válida de otro centro (30 por día) | centro `0104999`, mesa `0502002-09` | `RepairCentroFromMesa`: la mesa manda | La mesa es más específica; al día siguiente la fuente corrige el centro al de la mesa (`E0011238`) |
| 23 | padrón | Empadronados fallecidos que luego aparecen suspendidos o trasladados | `E0000561` fallecido → suspendido | Se carga, movimiento `cambio_estado` | Es lo que reporta la fuente; se señala como alerta de negocio |

## 3. Decisiones técnicas

| # | Decisión | Alternativas consideradas | Motivo de la elección |
|---|---|---|---|
| 1 | `csv` de la librería estándar + psycopg2 (sin pandas) | pandas, Polars, SQLAlchemy | 18 mil filas por día caben de sobra; transformaciones por registro son puras y fáciles de probar; menos dependencias en el contenedor. Con 9 millones migraría a Polars + `COPY`. |
| 2 | Fuentes, transformaciones, reglas y destino declarados en `config.yaml`; `factory.py` los ensambla | Un pipeline por fuente en código | Agregar una fuente es agregar un bloque YAML; agregar una transformación es una clase + una línea en el registro. |
| 3 | Carga histórica: staging temporal + `DELETE`/`INSERT` en **una transacción** con `LOCK` | Hash de archivo para omitir; `ON CONFLICT` | El modelo no tiene llaves únicas, así que `ON CONFLICT` no es posible sin alterar el DDL. El reemplazo atómico es idempotente por construcción y el dashboard nunca ve la tabla a medias. El hash queda en `etl.ejecuciones` para auditoría. |
| 4 | Padrón: `INSERT ... ON CONFLICT (id_empadronado) DO UPDATE ... WHERE IS DISTINCT FROM` | `TRUNCATE` + `INSERT` | Solo toca filas que cambian; `xmax = 0` distingue altas de cambios. Reprocesar la misma fecha da 0 cambios. |
| 5 | Bajas por ausencia: `UPDATE` de ids que no vienen en el archivo, excluyendo los que fueron a cuarentena | Borrado físico | Un registro con un error temporal no debe darse de baja. No se borra para no perder la referencia. |
| 6 | Esquema `etl` aparte (`sql/02_control_etl.sql`) con `ejecuciones`, `cuarentena`, `watermark` y `empadronados_snapshot` | Usar solo `carga_log` | `carga_log` es texto libre de 255 caracteres. Además se escribe una línea resumen en `carga_log` para no romper consumidores existentes. |
| 7 | Snapshot diario del padrón y clasificación del movimiento contra la foto anterior | Comparar contra la tabla viva | Comparar contra la tabla viva no es reprocesable (al reejecutar todo saldría "sin cambio"). Contra el snapshot es determinista y conserva la historia que `empadronados` sobrescribe. |
| 8 | Rechazos a cuarentena con el registro original en JSONB, y el flujo **falla** si superan 5% | Descartar con log; fallar siempre | Un registro malo no frena la carga, pero un archivo masivamente corrupto sí se detiene. Umbral configurable en `quality.max_reject_ratio`. |
| 9 | El registro de la ejecución usa una conexión propia en autocommit | Misma transacción | Si la carga hace rollback, el error igual queda registrado. |
| 10 | `pg_advisory_xact_lock` por fuente en la carga incremental | Ninguno | Evita dos cargas del padrón simultáneas (por ejemplo, un reintento y un backfill). |
| 11 | PostgreSQL de Docker expuesto en el puerto 5433 | 5432 | Evita choques con un PostgreSQL local. Configurable con `POSTGRES_PORT`. |

## 4. Fuera de alcance

| # | Pendiente | Cómo lo abordaría |
|---|---|---|
| 1 | Validar con negocio el duplicado de UNE (hallazgo 10) y la regla de suma de votos (15) | Reporte desde `etl.cuarentena` y métricas de `Deduplicate`; según respuesta, cambiar la estrategia en `config.yaml` |
| 2 | Reprocesar automáticamente la cuarentena una vez corregida | Comando `reprocess-quarantine --id` que reinyecta el JSONB por el mismo pipeline |
| 3 | Pruebas de integración contra PostgreSQL | `pytest` con un servicio Postgres en CI y aserciones de idempotencia (cargar 2 veces y comparar conteos) |
| 4 | Alertamiento real (Slack/correo) | Hoy es log + código de salida; el orquestador lo propaga (ver ORQUESTACION.md) |
