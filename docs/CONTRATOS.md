# Contratos HTTP y mensajes · v1

## REST

Todos los endpoints externos pasan por `http://localhost:8080/api/{servicio}/...`, donde `{servicio}` es `productos`, `clientes`, `prestamos`, `inventario`. Los permisos se verifican en cada API. Endpoints internos `/internal/*` exigen `X-Internal-Token`, únicamente en red Docker.

| Método | Ruta interna | Rol | Descripción |
|---|---|---|---|
| POST | `/auth/login` (Clientes) | público | `username`, `password` → token JWT |
| GET | `/auth/me` | autenticado | perfil de sesión |
| GET, POST, PUT, DELETE | `/productos`, `/productos/{id}` | GET público; cambios admin | Precio en COP y `version` |
| GET | `/internal/productos/{id}/cotizacion` | interno | precio **directo de DB** |
| GET, POST, PUT | `/clientes`, `/clientes/{id}` | admin o propietario | datos financieros/laborales |
| POST | `/clientes/importar` | admin | formulario multipart con archivo `file` CSV |
| POST | `/prestamos` | autenticado | `{producto_id,cantidad,plazo_meses,cliente_id?}` + header `Idempotency-Key` → HTTP **202** |
| GET | `/prestamos` `/prestamos/{id}` | admin o propietario | consulta/polling |
| POST | `/prestamos/{id}/cancelar` | admin o propietario | iniciar liberación |
| POST | `/prestamos/{id}/entregar` | admin | solicitar confirmación de salida |
| POST | `/riesgo/predict` | admin | JSON con las 11 variables sin identificadores ni objetivo |
| GET | `/modelo/info` `/modelo/monitor` | admin | versión, métricas, drift descriptivo |
| POST | `/modelo/activar` | admin | `{ "version":"v1" }` o `v2` |
| GET | `/health`, `/ready` (Préstamos) | health público | disponibilidad del servicio, modelo y BD |
| GET | `/inventario`, `/inventario/reservas`, `/inventario/movimientos` | admin | stock y trazabilidad |
| POST | `/inventario/entradas` | admin | `{product_id,units}` |
| GET | `/metrics/cache` (Productos) | admin | hit, miss, fallback, invalidations |

La UI transmite JWT por header `Authorization: Bearer ...`. No se acepta monto ni precio desde el cliente. El préstamo guarda precio unitario, versión de producto y modelo/umbral.

## Contrato JSON de mensajes v1.0

Cualquier comando/evento AMQP porta `event_id`, `type`, `schema_version`, `occurred_at`, `correlation_id`, `prestamo_id`, `payload`. No incluye datos financieros. Ejemplo:

```json
{
  "event_id": "6fd61e02-4f5a-4c6b-89c3-19ca27b1ff55",
  "type": "ReservaSolicitada",
  "schema_version": "1.0",
  "occurred_at": "2026-11-08T17:10:20+00:00",
  "correlation_id": "7ad58508-4930-4b09-a289-81513c66b722",
  "prestamo_id": "7ad58508-4930-4b09-a289-81513c66b722",
  "payload": {"producto_id": "45cd...", "cantidad": 1}
}
```

| `type` | Productor | Routing key | Consumidor | Payload mínimo |
|---|---|---|---|---|
| `ReservaSolicitada` | Préstamos | `reserva.solicitada` | Inventario | `producto_id`, `cantidad` |
| `ReservaLiberacionSolicitada` | Préstamos | `reserva.liberar` | Inventario | `producto_id` |
| `ReservaConfirmacionSolicitada` | Préstamos | `reserva.confirmar` | Inventario | `producto_id` |
| `InventarioReservado` | Inventario | `inventario.reservado` | Préstamos | `producto_id`, `cantidad` |
| `InventarioInsuficiente` | Inventario | `inventario.insuficiente` | Préstamos | `producto_id`, `cantidad` |
| `InventarioLiberado` | Inventario | `inventario.liberado` | Préstamos | `motivo` |
| `InventarioEntregado` | Inventario | `inventario.entregado` | Préstamos | `producto_id`, `cantidad` |
| `InventarioExpirado` | Inventario | `inventario.expirado` | Préstamos | `producto_id` o `motivo` |

Una carga inválida no debe producir cambio parcial. Los consumers almacenan `event_id` en inbox; las reentregas solo producen un ACK. El contrato es extensible mediante `schema_version`.
