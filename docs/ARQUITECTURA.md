# Arquitectura y consistencia

## Diagrama de componentes

```mermaid
flowchart LR
  U[Cliente / Administrador] --> WEB[Frontend Nginx :8080]
  WEB --> P[Productos / FastAPI]
  WEB --> C[Clientes / FastAPI]
  WEB --> L[Préstamos / FastAPI]
  WEB --> I[Inventario / FastAPI]
  L -- "HTTP + token interno" --> C
  L -- "Cotización HTTP fuente de verdad" --> P
  I -- "Validación HTTP" --> P
  P --> DP[(PostgreSQL products_db)]
  C --> DC[(PostgreSQL clients_db)]
  L --> DL[(PostgreSQL loans_db)]
  I --> DI[(PostgreSQL inventory_db)]
  P --> R[(Redis cache-aside)]
  L -. "Outbox => AMQP" .-> MQ{RabbitMQ direct exchange}
  MQ -. "ReservaSolicitada / Liberar / Confirmar" .-> I
  I -. "Outbox => AMQP" .-> MQ
  MQ -. "InventarioReservado / Insuficiente / ..." .-> L
  TRAIN[Entrenamiento offline] --> MF[(MLflow persistente)]
  TRAIN --> MODEL[(model_data: v1/v2 + manifests)]
  MODEL --> L
```

**Líneas continuas:** HTTP / consultas (síncrono) o DB del propio servicio. **Punteadas:** comandos/eventos asíncronos. El navegador NO tiene acceso directo a bases, broker, caché o pipeline.

## Diagrama de secuencia de una solicitud

```mermaid
sequenceDiagram
    actor C as Cliente
    participant W as Frontend
    participant L as Préstamos
    participant CL as Clientes
    participant P as Productos
    participant DB as BD Préstamos
    participant Q as RabbitMQ
    participant I as Inventario
    participant IDB as BD Inventario
    C->>W: Solicitar producto y plazo
    W->>L: POST /prestamos + Idempotency-Key
    L->>CL: GET perfil (token interno)
    CL-->>L: Perfil financiero
    L->>P: GET cotización vigente (DB)
    P-->>L: Precio + versión
    L->>L: Inferencia pipeline exportado + política
    alt Riesgo desfavorable
       L->>DB: Guardar RECHAZADA y versión
       L-->>W: HTTP 202 + id
    else Riesgo favorable
       L->>DB: TX: PENDIENTE_INVENTARIO + outbox
       L-->>W: HTTP 202 + id
       DB-->>Q: Worker publica ReservaSolicitada con confirms
       Q-->>I: Comando con ACK manual
       I->>IDB: TX: reservar con SELECT FOR UPDATE + inbox + outbox
       IDB-->>Q: Worker publica respuesta durable
       Q-->>L: InventarioReservado o InventarioInsuficiente
       L->>DB: TX: actualizar estado + inbox
       W->>L: GET /prestamos/{id} (polling)
       L-->>W: APROBADA o CANCELADA_SIN_STOCK
    end
```

## Máquina de estados

```mermaid
stateDiagram-v2
  [*] --> RECHAZADA: Riesgo desfavorable
  [*] --> PENDIENTE_INVENTARIO: Riesgo favorable, outbox persistido
  PENDIENTE_INVENTARIO --> APROBADA: InventarioReservado
  PENDIENTE_INVENTARIO --> CANCELADA_SIN_STOCK: InventarioInsuficiente
  PENDIENTE_INVENTARIO --> CANCELACION_PENDIENTE: Cancelar
  PENDIENTE_INVENTARIO --> CANCELADA_RESERVA_VENCIDA: InventarioExpirado
  APROBADA --> CANCELACION_PENDIENTE: Cancelar
  APROBADA --> ENTREGA_PENDIENTE: Confirmar entrega
  APROBADA --> CANCELADA_RESERVA_VENCIDA: InventarioExpirado
  ENTREGA_PENDIENTE --> COMPLETADA: InventarioEntregado
  ENTREGA_PENDIENTE --> CANCELADA_RESERVA_VENCIDA: InventarioExpirado
  CANCELACION_PENDIENTE --> CANCELADA: InventarioLiberado / Expirado
  RECHAZADA --> [*]
  CANCELADA_SIN_STOCK --> [*]
  CANCELADA --> [*]
  CANCELADA_RESERVA_VENCIDA --> [*]
  COMPLETADA --> [*]
```

## Integridad y tiempos

- Consistencia fuerte **local**: solicitud/outbox, inventario/inbox/outbox, préstamo/inbox; las bases no comparten transacciones.
- Consistencia eventual **entre servicios** a través de comandos y eventos. El éxito del riesgo **no** equivale a la aprobación del préstamo.
- Idempotencia HTTP: llave por actor + hash de payload normalizado, índice único SQL; mismo contenido devuelve ID existente, distinto devuelve 409. Debe conservarse la misma llave en reintentos.
- Mensajería: ID único por evento, tabla `inbox(event_id)` en la misma transacción del cambio de negocio. `ACK` solo después del commit.
- Inventario: `SELECT FOR UPDATE` sobre `stock`, restricción `reserved <= quantity` y no negatividad. Reserva con TTL de **300 s**; un worker barre cada 10 s.
- Cancelación antes de reservar: registra `TOMBSTONE` de préstamo; al llegar un comando de reserva tardío no lo ejecuta. Si llega un resultado tardío a Préstamos, no puede reactivarse un estado terminal.
- `PENDIENTE_INVENTARIO` no tiene timeout de broker fijo: ante caída del broker se conserva en la BD + outbox y se reintenta indefinidamente. Se debe observar el estado pendiente y alertar si supera **2 minutos**; la reserva, una vez creada, caduca a los 300 s. Para producción implementar alarma y reconciliación automática de comandos perdidos o DLQ.
- RabbitMQ: mensajes durables, confirmación de publicación, entrega al menos una vez, reintentos limitados, DLQ y supervisión manual.

## Seguridad académica

- PBKDF2-HMAC-SHA256 con sal por cuenta y 250.000 iteraciones; token JWT HS256 expira en 8 horas.
- El rol `admin` se verifica **en cada backend**; cliente solo consulta y cancela préstamos con su `client_id` de JWT. Los datos del cuerpo no sustituyen esa identidad.
- Endpoints internos por token X-Internal-Token solo disponible en contenedores; DB privadas por servicio; puertos de bases no publicados al host.
- `.env` y `ACCESOS_LOCALES.txt` se generan fuera de Git. HTTPS, rotación de secretos, observabilidad distribuida y seguridad de redes adicionales serían necesarios en producción.
