# Redis — diseño, evidencia y medición real

**Servicio propietario:** Productos. Patrón **cache-aside**. Clave `productos:v1:{producto_id}` con TTL 30 segundos; respuesta JSON de producto (precio, categoría, activo y versión). Primer acceso: miss → PostgreSQL → Redis; siguientes accesos: hit → Redis. Actualización/desactivación: primero commit en PostgreSQL, luego `DEL` de clave.

Si Redis está caído, cada operación tiene `socket_connect_timeout=0.25s` y `socket_timeout=0.25s` y lee PostgreSQL. El contador in-memory `fallback` aumenta. El precio de una solicitud de crédito se obtiene de `/internal/productos/{id}/cotizacion`, que **consulta solo PostgreSQL**; así no se elabora un préstamo con un precio antiguo de caché.

**Ventana de inconsistencia:** Si la escritura se confirma pero la invalidación falla, otra consulta pública puede observar un producto antiguo hasta el TTL máximo de 30 s. Es un compromiso aceptado para el catálogo de demostración; NO afecta el monto que guarda Préstamos. Para producción usaría invalidación transaccional por outbox / TTL menor según SLA.

## Medición cuantitativa

Después de instalar y encender Docker, ejecutar desde Python 3 en WSL:

```bash
python scripts/medir_redis.py
```

El script hace 100 consultas HTTP reales, calcula percentil p50/p95 en milisegundos, incremento de hits/misses y tasa de acierto durante esa muestra. Guarda `docs/medicion_redis_local.json`. La velocidad depende de tu equipo, red local y calentamiento; **no se incluyen cifras inventadas** antes de ejecutar la prueba. Complementa con `docker stats` para consumo de CPU/memoria de PostgreSQL, Redis y APIs durante la exposición.

## Fallos

1. Redis vacío: primera consulta = miss; posterior = hit.
2. Tras 31 segundos: expiración; siguiente consulta = miss.
3. Editar precio en administración: invalidación; siguiente consulta obtiene nuevo valor.
4. `docker compose stop redis`: sigue respondiendo desde DB, `fallback` > 0; reanudar con `docker compose start redis`.
5. Base de datos caída: Productos puede dar error; Redis no es base primaria y Préstamos debe rechazar la cotización si no existe fuente de verdad.

**Nota:** las métricas del contador son del proceso de demo, se reinician al reiniciar el servicio. p95 y tasa de hit se entregan como medición de una ejecución concreta, no pronóstico universal.
