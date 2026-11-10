# MLOps — metodología reproducible y resultados sintéticos

## A. Datos

- Histórico original: `data/prestamos_entrenamiento.csv`, 12.000 filas, 15 columnas, `incumplimiento_90d` como objetivo.
- Inferencias nuevas: `data/solicitudes_nuevas.csv`, 200 filas, 14 columnas, **sin objetivo**. No se usa para entrenamiento ni para calcular precision / ROC-AUC / AP.
- Entrenamiento/validación/prueba: 60 % / 20 % / 20 %, con estratificación `incumplimiento_90d`, semilla 42. Los IDs se conservan en `train_ids.csv`, `validation_ids.csv`, `test_ids.csv` para trazabilidad.
- Identificadores `cliente_id`, `solicitud_id` excluidos. Tasa de interés mensual fija también excluida por ser constante. Etiqueta excluida por prevención de fuga de información.
- Imputadores de variables numéricas (mediana), categórica (moda), codificación one-hot y escalado de numéricas dentro del mismo `Pipeline`, ajustados **solo con entrenamiento**. Variables faltantes admitidas en antigüedad, historial, puntualidad y tipo de empleo.
- Validación original con hash SHA-256 de bytes fuente y checks de tipos, duplicación, nulidad y distribución de clases. EDA exportada `eda.json`.

## B. Candidatos y criterio ANTES de ver prueba

Se ejecutan **8 corridas**: `baseline` (predice proporción de clases), `logistic_C02`, `logistic_C1`, `logistic_C4`, `tree_leaf20`, `tree_leaf50`, `forest_leaf3`, `forest_leaf8`. Semilla fija y parámetros declarados en script.

**Métrica primaria:** average precision de la clase 1 en validación (área bajo precisión-recall). **Desempate:** menor Brier score en validación. Se registran `precision`, `recall`, `F1`, `ROC-AUC`, `AP` y `Brier` (sin seleccionar por accuracy). Las corridas se visualizan en MLflow con sus parámetros, hashes, métricas y reportes.

### Umbral didáctico

Se optimiza exclusivamente en validación con **costos ficticios**: aprobar a un incumplidor = 5 unidades y rechazar a un cumplidor = 1 unidad. No son tasas reales ni políticas financieras. Se genera curva de costo por umbrales 0.05 a 0.95. Se congela el mejor umbral antes de evaluar prueba. **El conjunto de prueba se usa únicamente para `v1` después de seleccionar el candidato y el umbral; `v2` es versión alternativa con métricas de validación, sin segunda evaluación del test**.

## C. Experimentos MLflow

- Imagen de MLflow: `Dockerfile.ml`, servidor en puerto local 5000.
- SQLite de tracking y artefactos persistidos en volumen `mlflow_data`; observables después de reiniciar contenedores.
- Cada corrida añade `run_name`, código/dataset hash, split, semilla, features, preprocesamiento, hiperparámetros, entorno, duración, métricas y archivo reporte de matriz.
- Para candidato seleccionado se registra también evaluación del test bajo nombres `test_*` y modelo/manifest exportado. Una corrida nueva queda separada por `run_id`, no sustituye automáticamente la activa.

## D. Exportación y promoción

- `v1.joblib` = candidato seleccionado; `v2.joblib` = segunda alternativa según **la misma validación**. Cada versión lleva `manifest.v*.json` con el algoritmo, run ID, datos/hash, features, clase positiva, umbral, métricas, dependencias y `artifact_sha256`.
- `active.json` selecciona versión explícita. No hay selección dinámica de "último archivo". La API verifica SHA-256 del objeto antes de cargarlo y nunca entrena durante una solicitud.
- Administración: `POST /modelo/activar {"version":"v2"}` o `v1` (rollback); `GET /modelo/info` comprueba run ID y umbral.
- `sample.v*.json`: entrada/salida para equivalencia predictiva; al exportar se comprueba diferencia menor que `1e-12` entre pipeline en memoria y pipeline recargado.

## E. Inferencia

- `POST /riesgo/predict`: solo rol admin; once variables, sin etiqueta o IDs. Responde `probabilidad_incumplimiento`, `decision_riesgo`, `umbral`, `model_version`.
- `POST /prestamos`: compone las **mismas variables** a partir del perfil auténtico, cantidad/plazo y cotización vigente, calculando cuota con tasa **ficticia** 1,8 % mensual, coherente con el dataset.
- `solicitudes_nuevas_predicciones.csv`: 200 filas puntuadas por `v1`, cada una con solicitud/cliente de trazabilidad, score, decisión sintética y versión; no contiene etiquetas ni métricas de rendimiento.

## F. Monitoreo y evolución

- Tabla `predictions` propia de Préstamos, con la versión y probabilidad para cada solicitud/inferencia.
- `GET /modelo/monitor`: media observada vs media de validación, alerta descriptiva con al menos 10 observaciones y diferencia absoluta > 0.15.
- `scripts/simular_drift.py` genera predicciones extremas sintéticas para ejercitar esta alerta; **no afirma medir drift estadístico robusto ni degradación de desempeño real**.
- Ampliaciones de producción: datos etiquetados con retraso, PSI/KS o tests de dos muestras, esquema de consentimiento, calibración y evaluación por segmento, auditoría y aprobación humana, reentrenamiento supervisado.
