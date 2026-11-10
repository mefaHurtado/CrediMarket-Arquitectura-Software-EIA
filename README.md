# CrediMarket â€” ImplementaciÃ³n final Â· Universidad EIA

**AutorÃ­a acadÃ©mica:** Stefany Hurtado MarÃ­n. Si tu grupo incluye mÃ¡s integrantes, completa sus nombres y responsabilidades antes de publicar el repositorio. No inventes contribuciones de Git.

> **IMPORTANTE:** todo el crÃ©dito, las solicitudes y los datos son **sintÃ©ticos y ficticios**. El modelo de riesgo no debe aplicarse a personas ni a decisiones financieras reales.

## 1. Inicio directo en Windows (recomendado)

Necesitas **Docker Desktop con WSL2** iniciado, conexiÃ³n para descargar imÃ¡genes la primera vez, **8 GB de RAM disponibles** recomendados y espacio libre para los contenedores. No se necesita PostgreSQL, RabbitMQ ni Python instalados en Windows.

1. **Descomprime el ZIP** en una carpeta sin caracteres extraÃ±os, por ejemplo `C:\CrediMarket`.
2. **Abre Docker Desktop** y espera a que indique que el motor estÃ¡ funcionando.
3. En la carpeta del proyecto haz clic derecho â†’ **Abrir en Terminal** (PowerShell).
4. Haz doble clic en **`INICIAR_CREDIMARKET.bat`**; como alternativa, ejecuta exactamente:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\iniciar_windows.ps1
   ```

   El script genera claves privadas en `.env` (excluido de Git), cuentas de prueba en `ACCESOS_LOCALES.txt`, construye imÃ¡genes y ejecuta los servicios. La primera ejecuciÃ³n entrena automÃ¡ticamente el modelo y registra las 8 corridas en MLflow.

5. Abre **http://127.0.0.1:8081**. Lee los usuarios y contraseÃ±as generados en **`ACCESOS_LOCALES.txt`**. Selecciona `cliente_demo` para prÃ©stamos normales y `admin` para gestionar productos, inventario, modelos y entregas.
6. Para exponer la aplicaciÃ³n ante el profesor, deja Docker Desktop y los contenedores encendidos. Abre MLflow en **http://localhost:5000** y RabbitMQ en **http://localhost:15672** (cuenta y clave en `ACCESOS_LOCALES.txt`).

### Comandos Ãºtiles

```powershell
docker compose ps                       # Contenedores y estados
docker compose logs -f loans-worker    # MensajerÃ­a y procesamiento
docker compose logs -f inventory-worker
docker compose logs -f train           # Experimentos y entrenamiento
docker compose down                     # Detener sin borrar los datos
docker compose up -d                    # Reanudar
docker compose down -v                  # DESTRUCTIVO: borra BD, MLflow, modelos y colas
```

**No ejecutes `down -v`** si quieres conservar la evidencia, los datos y los experimentos de MLflow. El script no sustituye las contraseÃ±as si `.env` ya existe: se conserva el estado entre arranques.

### Inicio desde WSL2 / Linux

```bash
chmod +x iniciar_linux.sh
./iniciar_linux.sh
```

## 2. QuÃ© se implementÃ³

| Componente | Puerto interno | Funciones |
|---|---:|---|
| Frontend Nginx | **http://127.0.0.1:8081** | Login, catÃ¡logo, clientes, prÃ©stamo, seguimiento, inventario, monitor de modelo |
| Productos (FastAPI) | 8000 | CRUD, versiones, consulta desde Redis, cotizaciÃ³n autoritativa |
| Clientes (FastAPI) | 8000 | Usuarios/roles, perfil financiero, CSV sin duplicaciÃ³n |
| PrÃ©stamos (FastAPI) | 8000 | Riesgo con pipeline exportado, idempotencia HTTP, eventos y estados |
| Inventario (FastAPI) | 8000 | Stock, reserva atÃ³mica, liberar, entrega, vencimiento, movimientos |
| PostgreSQL 16 | 5432, privado | 4 bases / 4 usuarios restringidos |
| Redis 7 | 6379, privado | Cache-aside TTL 30s y fallback DB |
| RabbitMQ 3.13 | 5672, privado | Comandos/eventos durables, reintentos, DLQ |
| RabbitMQ Management | **http://localhost:15672** | Exchanges, colas y mensajes |
| MLflow 2.22 | **http://localhost:5000** | 8 experimentos, mÃ©tricas, artefactos persistidos |

**Los cuatro servicios tienen bases aisladas**. `inventory-worker` y `loans-worker` son procesos trabajadores de los servicios existentes, **no un quinto microservicio**. `train` es un job offline, no recibe solicitudes de negocio.

## 3. Flujo demostrado

1. El cliente inicia sesiÃ³n con usuario/contraseÃ±a de prueba.
2. `POST /prestamos` recibe `Idempotency-Key` y obtiene el perfil y el precio vigente mediante APIs internas.
3. PrÃ©stamos construye las 11 variables de entrada del pipeline, calcula riesgo y persiste la decisiÃ³n/modelo/versiÃ³n de precio.
4. Si el riesgo ficticio es favorable, inserta el prÃ©stamo `PENDIENTE_INVENTARIO` y `ReservaSolicitada` **en la misma transacciÃ³n local** (outbox); responde **HTTP 202**.
5. Un worker publica el outbox con publisher confirms; Inventario consume el comando mediante RabbitMQ.
6. Inventario bloquea la fila de stock (`FOR UPDATE`), reserva con restricciÃ³n SQL de no-negatividad e inserta un evento de respuesta en su outbox.
7. PrÃ©stamos consume `InventarioReservado` â†’ `APROBADA` o `InventarioInsuficiente` â†’ `CANCELADA_SIN_STOCK`.
8. Admin puede entregar; un cliente puede solicitar cancelaciÃ³n. Los cambios de inventario solo se confirman **por evento**.
9. Cada efecto entrante registra `event_id` en la bandeja `inbox` junto con la operaciÃ³n en la misma transacciÃ³n, tolerando reentregas.

La API no aprueba cuando el modelo arroja riesgo favorable: **solo aprueba tras la reserva confirmada**. En caso de caÃ­da del broker, el outbox queda pendiente para reintentar tras su recuperaciÃ³n.

## 4. DemostraciÃ³n sugerida (orden)

Consulta tambiÃ©n [`docs/GUIA_DEMO.md`](docs/GUIA_DEMO.md). Resumen:

- Ingresar con `cliente_demo`, hacer un prÃ©stamo y observar `PENDIENTE_INVENTARIO` â†’ `APROBADA`.
- Ingresar con `admin`, ir a Solicitudes y confirmar la entrega â†’ `COMPLETADA`.
- Ingresar con `cliente_riesgo` y crear una solicitud para observar una **decisiÃ³n de riesgo desfavorable** (datos sintÃ©ticos).
- En admin crear un producto, registrar una unidad y usar dos clientes para competir por ella (solo uno obtiene la reserva).
- Importar `data/solicitudes_nuevas.csv` dos veces y verificar el conteo de actualizados, sin duplicados.
- Modificar un precio y consultar `/modelo/info`; usar el botÃ³n de versiÃ³n v2 y regresar a v1.
- Revisar MLflow y las colas de RabbitMQ; usar los scripts para latencias y pruebas de aceptaciÃ³n.

## 5. Datos y MLOps

Los dos CSV originales del enunciado estÃ¡n incluidos, sin modificaciones. `ml/train.py` valida y divide los 12.000 registros en **60/20/20**, estratificados con semilla 42. Excluye identificadores, etiqueta y tasa constante. ImputaciÃ³n, codificaciÃ³n y escalado se ajustan solo en entrenamiento. Compara **baseline + 7 candidatos** y selecciona por **average precision de validaciÃ³n** (desempate por Brier). Ajusta umbral en validaciÃ³n mediante costos ficticios explÃ­citos (5 y 1). La prueba se reserva para evaluaciÃ³n final.

Se exportan `v1.joblib`, `v2.joblib`, manifiestos con SHA-256, particiones, mÃ©tricas, matriz y ejemplos; tambiÃ©n se generan las **200 inferencias** de `solicitudes_nuevas.csv` sin etiquetas ni mÃ©tricas de clasificaciÃ³n. El servicio no entrena por peticiÃ³n. Una promociÃ³n cambia la versiÃ³n **explÃ­citamente**; el botÃ³n de v1/v2 muestra promociÃ³n/rollback. Para rehacer los experimentos despuÃ©s de una ejecuciÃ³n, **no** borres los volÃºmenes y ejecuta `docker compose run --rm train` (se aÃ±aden corridas).

- MLflow: http://localhost:5000
- API documentaciÃ³n (dentro de Docker o mediante proxy `http://127.0.0.1:8081/api/prestamos/docs`): FastAPI `/docs`.
- Monitoreo de media de predicciones: botÃ³n Modelo; alerta descriptiva a partir de 10 observaciones y diferencia de medias mayor de 0,15. No estima desempeÃ±o sin etiquetas.

## 6. DocumentaciÃ³n del repositorio

- [`docs/ARQUITECTURA.md`](docs/ARQUITECTURA.md): diagramas de arquitectura, secuencia, estado y consistencia.
- [`docs/DECISION_MENSAJERIA.md`](docs/DECISION_MENSAJERIA.md): RabbitMQ frente a Kafka, seis puntos de anÃ¡lisis y limitaciones.
- [`docs/CONTRATOS.md`](docs/CONTRATOS.md): rutas REST, tipos de mensaje, ejemplos JSON.
- [`docs/GUIA_DEMO.md`](docs/GUIA_DEMO.md): demostraciones, pruebas de fallos, recuperaciÃ³n.
- [`docs/REDIS_Y_RENDIMIENTO.md`](docs/REDIS_Y_RENDIMIENTO.md): TTL, invalidaciÃ³n, resiliencia y mediciones.
- `model_artifacts/`: modelos y manifiestos iniciales, generados con la versiÃ³n de scikit-learn instalada en el entorno de prueba local; **en Docker** se reentrena con dependencias fijadas para garantizar compatibilidad.
- [`docs/MLOPS.md`](docs/MLOPS.md): particiones, modelos, validaciÃ³n, umbral y exportaciÃ³n de 200 inferencias.

## 7. Entrega en Git

Se recomienda un Ãºnico repositorio Git con **este contenido**, menos `.env`, `ACCESOS_LOCALES.txt` y volÃºmenes (excluidos de Git). En la sustentaciÃ³n se muestra la ejecuciÃ³n desde el repositorio y el historial REAL de cambios.

| Integrante | Responsabilidad |
|---|---|
| Stefany Hurtado MarÃ­n | IntegraciÃ³n general, revisiÃ³n del flujo y sustentaciÃ³n (ajustar a participaciÃ³n real) |
| Integrante 2 (completar) | Por asignar |
| Integrante 3 (completar) | Por asignar |
| Integrante 4 (completar) | Por asignar |

**LimitaciÃ³n honesta:** este paquete se validÃ³ mediante anÃ¡lisis de cÃ³digo y pruebas locales de entrenamiento; no se ha podido ejecutar Docker Engine en este entorno de creaciÃ³n. La validaciÃ³n integrada en tu equipo se realiza mediante los pasos y pruebas del repositorio. La app es una **demostraciÃ³n acadÃ©mica**, no estÃ¡ endurecida para producciÃ³n.
