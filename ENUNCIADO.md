# Prueba Técnica — Ingeniero de Datos Junior

**Versión 2.0 — enfoque en desarrollo de ETL**
Tiempo asignado: **3 días calendario** · Esfuerzo esperado: **6 a 8 horas**

---

## 1. Objetivo

Evaluar tu capacidad para construir un proceso ETL mantenible sobre una base de datos existente, y tu criterio para identificar oportunidades de mejora en un modelo de datos que ya está en producción.

Este repositorio te entrega ya resueltos el modelo de datos, el DER, los DDL y la data de prueba, junto con un esqueleto de código. **El foco de la evaluación es el ETL.**

| Competencia | Peso |
|---|---|
| Desarrollo del ETL en Python (diseño, idempotencia, incrementalidad, calidad de datos) | 45% |
| Análisis crítico del modelo de datos y SQL | 25% |
| Orquestación (definición + implementación) | 15% |
| Git / GitHub (ramas, commits, PR) | 10% |
| Contenedores (deseable) | 5% |

---

## 2. Contexto del caso

Se está desarrollando una aplicación que presenta un **dashboard de resultados electorales de un país**. El propósito no es solo mostrar resultados, sino permitir el análisis de la información para encontrar *insights* que ayuden a mejorar el proceso de votación: saturación de centros de votación, brechas de participación, cobertura del padrón por zona geográfica.

Tú asumes el rol de **ingeniero de datos** del equipo. Eres responsable de que la información llegue a la base de datos de forma confiable, actualizada y trazable.

La base de datos que vas a usar **ya existe**. Fue construida de forma acelerada durante la elección anterior y hoy está en producción. Debes trabajar sobre ella tal como está.

### 2.1 Fuentes de información

Están en la carpeta `data/`.

| # | Fuente | Archivo | Naturaleza | Carga |
|---|---|---|---|---|
| 1 | Resultados históricos | `data/historico/resultados_historicos.csv` | Histórica, inmutable | **Una sola vez** |
| 2 | Centros de votación | `data/historico/centros_votacion.csv` | Histórica, con correcciones ocasionales | **Una sola vez** |
| 3 | Empadronados | `data/empadronados/empadronados_YYYYMMDD.csv` | **Fuente viva**: se recibe un archivo por día | **Diaria (incremental)** |

Se entregan tres días consecutivos del padrón (`20260302`, `20260303`, `20260304`). Entre un día y el siguiente hay:

- **altas**: empadronados nuevos que no existían el día anterior,
- **cambios**: empadronados que cambiaron de centro y mesa (traslados),
- **bajas**: empadronados que pasaron a estado `suspendido` o `fallecido`.

Cada archivo es una **fotografía completa del padrón a esa fecha**, no un delta.

### 2.2 Sobre la calidad de los datos

Las fuentes reflejan la realidad y traen inconsistencias. No están documentadas una por una a propósito: **encontrarlas es parte de la prueba**. Como referencia, vas a toparte con al menos: variaciones de acentos, mayúsculas y espacios en los nombres geográficos; valores categóricos no estandarizados; decimales con coma; números con separador de miles; fechas en dos formatos distintos; campos vacíos; duplicados exactos y duplicados con diferencias; códigos de centro que no existen en el catálogo; y registros que violan reglas de negocio.

Documenta lo que encuentres en `DECISIONES.md`, incluyendo qué decidiste hacer con cada caso y por qué.

---

## 3. Qué debes desarrollar

### 3.1 Análisis crítico del modelo de datos (25%)

El modelo está en `sql/01_ddl_electoral.sql` y documentado en `docs/BASE_DE_DATOS.md` (incluye DER y diccionario de datos).

**No modifiques el DDL entregado.** Cárgale la información tal como está y, en paralelo, entrega `docs/MEJORAS_MODELO.md` respondiendo:

1. ¿Qué problemas ves en este modelo? Ordénalos por impacto.
2. Para cada problema: ¿qué consecuencia concreta tiene en el ETL, en la integridad de los datos o en el consumo del dashboard?
3. ¿Cuál sería tu modelo propuesto? Incluye el DER de tu propuesta.
4. ¿Cómo migrarías de un modelo al otro sin interrumpir el dashboard?

Opcionalmente puedes dejar tu propuesta como script en `sql/99_propuesta_mejoras.sql`. Se valora, pero pesa menos que la calidad del análisis.

> Pista de enfoque, no exhaustiva: piensa en tipos de dato, restricciones e integridad referencial, granularidad y redundancia, normalización de catálogos, historización de cambios en el tiempo, trazabilidad de las cargas y desempeño de las consultas del dashboard.

### 3.2 Proceso ETL en Python (45%) — foco principal

Sobre el esqueleto entregado en `src/`, implementa:

**a) Carga única (histórica)**

- Centros de votación y resultados históricos.
- Debe ser **idempotente**: ejecutar el proceso dos veces no debe duplicar información ni dejar la base inconsistente. Ojo: el modelo actual no tiene restricciones de unicidad, así que la idempotencia depende de tu diseño.
- Las mesas de votación (`electoral.mesas_votacion`) no vienen en un archivo: debes derivarlas de las fuentes.

**b) Carga incremental (padrón)**

- Debe procesar una fecha específica: `python main.py load-empadronados --fecha 2026-03-03`.
- Debe manejar altas, cambios y bajas.
- Debe registrar hasta qué fecha se procesó (marca de agua / *watermark*), y permitir **reprocesar** una fecha ya cargada sin duplicar.
- Considera qué información se pierde con el enfoque de sobrescritura del modelo actual y menciónalo en `MEJORAS_MODELO.md`.

**c) Diseño del código**

El esqueleto ya define las interfaces (`BaseExtractor`, `BaseTransformer`, `BaseLoader`, `Pipeline`). Respétalas o cámbialas justificando el motivo. El criterio de evaluación es: **agregar una fuente nueva, una transformación nueva o un destino nuevo no debe implicar reescribir el flujo existente.**

Concretamente:

- Configuración externalizada (`src/config/config.yaml`), credenciales solo por variables de entorno.
- Transformaciones componibles y probables de forma aislada.
- Sin lógica de negocio duplicada entre fuentes.

**d) Calidad de datos y trazabilidad**

- Implementa al menos las reglas listadas en `src/quality/validations.py`.
- Un registro inválido no debe romper la ejecución en silencio: decide entre cuarentena, descarte con log o fallo del flujo, y documenta el criterio.
- Emite métricas por ejecución: filas leídas, cargadas y rechazadas, y duración.

**e) Pruebas**

- Al menos **3 pruebas unitarias reales** de transformaciones en `tests/`. No requieren base de datos.

### 3.3 Estrategia de orquestación (15%)

- Documenta y **justifica** tu elección en `docs/ORQUESTACION.md`, comparándola con al menos una alternativa (Airflow, Prefect, Dagster, cron + contenedor, GitHub Actions).
- Define: dependencias entre flujos, frecuencia y horario, política de reintentos, comportamiento ante fallos, alertamiento y cómo se hace un *backfill*.
- **Implementa** al menos dos flujos ejecutables en `orchestration/`: la carga histórica (una vez) y la actualización diaria del padrón.
- Incluye un diagrama del flujo (Mermaid o imagen).

### 3.4 Contenedores (5%, deseable)

`docker-compose.yml` y `Dockerfile` vienen iniciados. Complétalos para que la solución se levante y ejecute con la menor cantidad de comandos posible.

---

## 4. Entregables

Un repositorio de GitHub (público o con acceso al evaluador) que contenga:

1. El código del ETL implementado.
2. La implementación de la orquestación.
3. `docs/MEJORAS_MODELO.md` — análisis crítico del modelo + DER propuesto.
4. `docs/ORQUESTACION.md` — estrategia, justificación y diagrama.
5. `DECISIONES.md` — supuestos, hallazgos de calidad de datos, y qué quedó fuera de alcance con el motivo.
6. `README.md` actualizado con el paso a paso completo para ejecutar todo desde cero: prerrequisitos, variables de entorno, creación de la base de datos, carga histórica, carga incremental y ejecución del orquestador. Debe alcanzar para que un tercero lo reproduzca sin preguntarte nada.

**No es un entregable:** vistas ni tablas de consumo para KPIs. Ese apartado queda fuera del alcance de esta prueba.

### 4.1 Requisitos de Git / GitHub

- Trabajar en **al menos dos ramas** (por ejemplo `main` y `feature/etl`).
- Commits descriptivos y con granularidad razonable. No un único commit final.
- Al terminar, abrir un **Pull Request** de la rama de trabajo hacia la principal, con descripción del cambio. **Déjalo abierto, no lo fusiones**: forma parte de lo que se revisa.
- No versionar `.env` ni credenciales.

---

## 5. Restricciones técnicas

- Python 3.10+ y PostgreSQL 14+.
- Librerías libres. Se valora que justifiques la elección (por ejemplo pandas vs. Polars, psycopg2 vs. SQLAlchemy).
- Se permite el uso de asistentes de IA, siempre que puedas explicar y defender cada decisión de tu código en la sustentación.
- No se requiere frontend ni dashboard.

---

## 6. Priorización si el tiempo no alcanza

1. Carga histórica idempotente y funcional.
2. Carga incremental del padrón con altas, cambios y bajas.
3. `MEJORAS_MODELO.md`.
4. Orquestación implementada.
5. Pruebas unitarias.
6. Contenedores.

Documenta en `DECISIONES.md` lo que quedó pendiente y cómo lo abordarías. Una entrega parcial bien argumentada vale más que una entrega completa que no se puede ejecutar.

---

## 7. Cómo se evalúa

Cada criterio se califica de 1 a 5 (1 = no cumple, 3 = cumple lo esperado para un junior, 5 = sobresaliente).

### ETL en Python (45%)

| Criterio | 1–2 | 3 | 4–5 |
|---|---|---|---|
| Idempotencia de la carga histórica | Reejecutar duplica datos | Idempotente con un mecanismo simple y explicado | Control por tabla de estado o staging + swap, con reprocesamiento seguro |
| Carga incremental | Recarga total (truncate + insert) sin justificar | Upsert que maneja altas, cambios y bajas | Upsert + watermark + backfill por fecha + detección de bajas por ausencia |
| Extensibilidad del diseño | Script monolítico con todo mezclado | Respeta las interfaces del template | Componentes desacoplados y configurables; agregar una fuente es agregar configuración |
| Tratamiento de la data sucia | Ignora las inconsistencias o falla | Normaliza los casos principales | Normalización consistente entre fuentes, criterio documentado para duplicados y huérfanos |
| Calidad y trazabilidad | Sin validaciones ni logs | Validaciones básicas y logging | Rechazos en cuarentena, métricas por ejecución, errores accionables |
| Pruebas | Ninguna | 3 pruebas de transformaciones | Pruebas con casos borde (vacíos, formatos mixtos, duplicados) |

### Análisis del modelo y SQL (25%)

| Criterio | 1–2 | 3 | 4–5 |
|---|---|---|---|
| Detección de problemas | Comentarios genéricos o ninguno | Identifica tipos de dato, falta de FK y unicidad, redundancia | Además: granularidad, historización, catálogos, trazabilidad e índices, priorizados por impacto |
| Consecuencias | No las explica | Explica el impacto de los principales | Conecta cada problema con un síntoma concreto en el ETL o el dashboard |
| Modelo propuesto | Ausente o equivalente al actual | DER coherente con llaves y tipos correctos | Modelo por capas o dimensional justificado, con estrategia de historización |
| Migración | No la considera | Menciona el enfoque | Plan por pasos, reversible y sin interrumpir el consumo |
| SQL | Consultas incorrectas | SQL correcto para carga y verificación | Uso adecuado de upsert, transacciones y consultas de validación |

### Orquestación (15%)

| Criterio | 1–2 | 3 | 4–5 |
|---|---|---|---|
| Definición | Solo menciona una herramienta | Estrategia con frecuencias, dependencias y reintentos | Justificación comparativa, alertamiento y estrategia de backfill |
| Implementación | No implementa | Dos flujos ejecutables | Flujos con dependencias, reintentos y ejecución reproducible |

### Git / GitHub (10%)

| Criterio | 1–2 | 3 | 4–5 |
|---|---|---|---|
| Ramas y PR | Una rama, un commit | Dos ramas y PR abierto descrito | Historia limpia, commits atómicos, PR con contexto |
| Higiene del repositorio | Credenciales versionadas | `.gitignore` correcto | README reproducible de punta a punta |

### Contenedores (5%, deseable)

Dockerfile funcional; `docker-compose` que levante el stack; ejecución en pocos comandos.

### Criterio transversal — comunicación

Se evalúa la claridad del README, de `DECISIONES.md` y de `MEJORAS_MODELO.md`. Una solución técnicamente correcta que un tercero no pueda ejecutar se califica como incompleta.

---

## 8. Sustentación

Sesión de 30 a 45 minutos: 10 minutos de presentación de tu solución y luego preguntas. El evaluador tomará al menos 5 de estas:

1. Si mañana el archivo de empadronados llega con dos columnas nuevas y una renombrada, ¿qué partes de tu código cambian?
2. ¿Cómo garantizas que ejecutar la carga histórica dos veces no duplique datos?
3. Un empadronado cambió de centro de votación entre el día 2 y el día 3. ¿Qué pasó en tu base de datos y qué información se perdió?
4. La carga diaria falló a las 2 a.m. y nadie se dio cuenta hasta las 10 a.m. ¿Qué pasa con los datos y cómo lo resuelves?
5. ¿Qué haces con un registro cuyo código de centro no existe en el catálogo? ¿Lo descartas, lo cargas o lo pones en cuarentena? ¿Por qué?
6. Encontraste mesas donde los votantes superan a los empadronados. ¿Es un error de datos o un hallazgo del negocio? ¿Cómo lo manejaste en el pipeline?
7. De todas las mejoras que propusiste al modelo, ¿cuál harías primero y por qué?
8. ¿Cómo pruebas tus transformaciones sin ejecutar todo el pipeline ni tener base de datos?
9. ¿Por qué elegiste ese orquestador y en qué escenario sería la elección equivocada?
10. Si el padrón pasara de 18 mil a 9 millones de registros diarios, ¿qué se rompe primero en tu solución?

---

## 9. Señales de alerta para el evaluador

- Credenciales versionadas en el repositorio.
- Un único commit con todo el trabajo, o PR ya fusionado sin historia.
- README que no permite ejecutar la solución sin preguntar.
- Carga incremental resuelta con `TRUNCATE` + `INSERT` del archivo completo sin justificarlo.
- `MEJORAS_MODELO.md` genérico, que aplicaría a cualquier base de datos sin haber leído esta.
- El candidato no puede explicar por qué existe una parte de su propio código.

---

## 10. Contacto

Dudas sobre el enunciado: **[correo del evaluador]**. Las preguntas sobre supuestos son bienvenidas y se toman como señal positiva; también es válido tomar un supuesto propio y documentarlo.
