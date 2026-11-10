# Guía de sustentación y pruebas — CrediMarket

## Preparación

1. Abrir Docker Desktop, ejecutar `iniciar_windows.ps1`, comprobar que `docker compose ps` indica **healthy** para APIs y MLflow y que el contenedor `train` terminó con código 0.
2. Abrir http://localhost:8080 y consultar `ACCESOS_LOCALES.txt` **sin mostrar contraseñas en una grabación pública**.
3. Abrir http://localhost:5000: experimento `CrediMarket-riesgo-sintetico`, **8 corridas** (1 baseline + 7), artefactos, datasets identificados por hash, métricas y manifiesto de versiones.
4. Abrir http://localhost:15672: login de RabbitMQ creado por el instalador. Mostrar exchanges, colas y DLQ; revisar `loans-worker` y `inventory-worker` en logs.

## Flujo desde navegador

**Caso 1 — riesgo favorable y entrega.** Inicia `cliente_demo`, elige producto y 1 unidad, plazo 12. Verifica respuesta pendiente → `APROBADA` en Solicitudes. Ingresa como `admin`, abre Solicitudes y pulsa Entregar; finalmente `COMPLETADA`. Inventario descuenta físicamente la unidad solo al confirmar entrega.

**Caso 2 — rechazo de riesgo.** Entra como `cliente_riesgo` y solicita un producto: en el dataset ficticio la probabilidad suele superar el umbral. Debe quedar `RECHAZADA` y no existir reserva. La política no se aplica a humanos reales.

**Caso 3 — sin existencias.** Admin crea un producto, **no registra** existencias; `cliente_demo` solicita, aparece `CANCELADA_SIN_STOCK`.

**Caso 4 — dos solicitudes por la última unidad.** Inicia contenedores, ejecuta en PowerShell (con Python opcional en Windows / WSL):

```bash
python scripts/probar_sistema.py
```

El script registra producto con 1 unidad, envía solicitudes concurrentes de `cliente_demo` y `cliente_dos` y confirma un solo ganador. También prueba idempotencia `202/409`, 403 de autorización, liberación, cambio de precio, Redis, promoción y rollback. Es evidencia ejecutada, no respuesta simulada.

**Caso 5 — petición HTTP y evento repetidos.** Script repite idéntica `Idempotency-Key` y payload → mismo ID; cambia cantidad con misma key → `409`. Verifica en tabla loans índice único `(actor_id,idem_key)`. Para demostrar reentrega **real por RabbitMQ** (después de que un préstamo haya sido aprobado), sustituye `ID` y ejecuta:

```bash
docker compose exec loans-worker python scripts/demo_reentrega.py ID
```

Reinyecta el mismo `event_id` que fue publicado originalmente. El consumer de Inventario debe encontrarlo en `inbox` y no descontar ni reservar inventario otra vez. Inspeccionar movimiento y stock antes/después.

**Caso 6 — consumidor detenido / recuperación.** En terminal:

```bash
docker compose stop inventory-worker
```

Desde la web crea una solicitud favorable y observa `PENDIENTE_INVENTARIO`. Ejecuta:

```bash
docker compose start inventory-worker
docker compose logs -f inventory-worker
```

El comando pendiente debe procesarse y el estado converger. Para caída del broker (requiere que outbox ya esté pendiente), detén `rabbitmq`, registra solicitud y reanúdalo: el outbox conserva pendientes y se publica después de la reconexión. NO borres volúmenes. RabbitMQ puede demorar unos segundos en reiniciar.

**Caso 7 — evento tardío / cancelación.** Crear solicitud, detener `inventory-worker` antes de consumir, cancelar la solicitud y luego reanudar el worker; la reserva puede recibir un `TOMBSTONE` antes de la solicitud y no debe reactivarse tras `CANCELADA`. La carrera exacta entre solicitudes puede variar; repetir con los registros para evidenciar el caso.

**Caso 8 — Redis miss, hit, expiración y caída.** Admin consulta un producto recién creado (miss), lo consulta nuevamente (hit) y examina botón Métricas. Esperar 31 s, volver a consultar (miss). Cambiar el precio (invalidación), verificar versión. Detén Redis y consulta de nuevo: la lectura sale de PostgreSQL (`fallback` aumenta). Reanudar:

```bash
docker compose stop redis
docker compose start redis
python scripts/medir_redis.py
```

El script guarda `docs/medicion_redis_local.json` con p50, p95, tasa hit y fallback realmente observados.

**Caso 9 — precio cotizado.** Crear/actualizar producto antes de `POST /prestamos`; préstamo guarda `precio_unitario`, `version_precio` y `monto`. Endpoint interno de cotización lee PostgreSQL, no Redis.

**Caso 10 — pipeline exportado vs. API.** Dentro de `loans` ejecutar:

```bash
docker compose exec loans python -c "import joblib,json,pandas as pd; from pathlib import Path; p=Path('/models'); v=json.load(open(p/'active.json'))['version']; a=joblib.load(p/(v+'.joblib')); e=json.load(open(p/('sample.'+v+'.json'))); q=float(a.predict_proba(pd.DataFrame([e['input']]))[0,1]); print('equivale:',abs(q-e['probability'])<1e-10,'probabilidad:',q)"
```

**Caso 11 — promoción y rollback.** Admin abre Modelo, observa v1 / run ID / umbral, cambia a v2 y verifica. Regresa a v1; `GET /modelo/info` identifica de forma estable versión activa y run ID.

**Caso 12 — importación idempotente.** Admin entra en Clientes y sube `data/solicitudes_nuevas.csv` dos veces. La primera inserta 200 si no hay registros externos previos; la segunda actualiza sin duplicar IDs externos. El informe identifica errores por fila.

**Caso 13 — préstamo ajeno.** `scripts/probar_sistema.py` verifica que otro cliente obtiene 403 cuando consulta el préstamo del primero.

**Casos 14, 15 y 16 — frontend real.** Mostrar catálogo, CRUD de productos, clientes, importación, inventario, préstamo, historial, modelo; captura de pantalla de `PENDIENTE_INVENTARIO` y polling. Probar formulario vacío, credenciales falsas y detener una API; la UI muestra error explícito, sin éxito falso.

## Observaciones y límites

- Pruebas de reintento/dead-letter: provoque una entrada con contrato inválido mediante herramientas controladas en un ambiente de demo; nunca en producción. RabbitMQ expone colas `.retry` y `.dead` para inspección. La auto-reinyección de DLQ no está incluida; requiere intervención manual para no repetir indefinidamente un mensaje defectuoso.
- No se ha medido carga masiva ni disponibilidad de producción; cualquier resultado debe reflejar pruebas realmente ejecutadas en el PC.
- Modelo de scoring sobre datos sintéticos. No suponer que las métricas prueban validez crediticia real.
- La vista de RabbitMQ es solo para demostración local; no publicarla en Internet.

**Demostración adicional de drift (ML).** Ejecutar `python scripts/simular_drift.py` para generar 20 predicciones de un perfil sintético desplazado respecto al dataset de desarrollo. Revisar `GET /modelo/monitor` en el frontend (la alerta compara medias, no calcula accuracy sin etiquetas).
