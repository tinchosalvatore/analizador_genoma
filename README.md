# Proyecto Final: 🧬 Analisis de Genoma Humano 🧬

**Estado:**  Documento Definitivo de Arquitectura v2.0

Este repositorio contiene el proyecto final para la materia Computación II. Es un sistema distribuido desarrollado en Python que implementa dos subsistemas paralelos e interconectados:

1. **Sistema A - Grid de Cómputo:** Procesa tareas CPU-bound (análisis genómico) de forma paralela y distribuida.
2. **Sistema B - Sistema de Monitoreo:** Vigila la salud de los nodos del grid en tiempo real.

---

## 📖 Índice

* [1. Visión General del Proyecto](#1-visión-general-del-proyecto)
* [2. Arquitectura del Sistema](#2-arquitectura-del-sistema)
* [3. Componentes Detallados](#3-componentes-detallados)
* [4. Protocolos de Comunicación](#4-protocolos-de-comunicación)
* [5. Cumplimiento de Requisitos](#5-cumplimiento-de-requisitos)
* [6. Core del Stack Tecnológico](#6-core-del-stack-tecnológico)
* [7. Despliegue con Docker 🐳](#7-despliegue-con-docker-)
* [8. Consideraciones de Implementación](#8-consideraciones-de-implementación)
* [9. Scripts de Utilidad](#9-scripts-de-utilidad)
* [10. Contacto y Contribuciones](#10-contacto-y-contribuciones)

## Glosario de Términos 🤓

- **Chunk:** Fragmento del archivo genoma (típicamente 1MB)
- **Overlap:** Bytes duplicados entre chunks consecutivos
- **Heartbeat:** Señal periódica que indica que un proceso está vivo
- **IPC:** Inter-Process Communication (comunicación entre procesos)
- **Unix Domain Socket:** Socket para IPC en la misma máquina
- **Celery:** Framework de colas de tareas distribuidas
- **Broker:** Servidor que maneja la cola de mensajes (Redis)
- **Worker:** Proceso que consume y ejecuta tareas
- **Master:** Servidor coordinador del grid de cómputo
- **Collector:** Servidor que recolecta métricas de monitoreo
- **Agente:** Proceso que monitorea un worker local

---

## 1. Visión General del Proyecto

### 1.1 El Concepto: "El Director y El Vigilante"

El proyecto consiste en dos sistemas distribuidos que operan simultáneamente:

**🎼 El Director (Sistema A - Grid de Cómputo)**
- **Rol:** Coordinar la ejecución paralela de tareas computacionales pesadas
- **Responsabilidad:** Garantizar que el *trabajo* se complete correctamente
- **Ejemplo:** Analizar Genoma Humano, buscando patrones específicos

**👁️ El Vigilante (Sistema B - Monitoreo)**
- **Rol:** Supervisar la salud e infraestructura de los nodos de cómputo
- **Responsabilidad:** Garantizar que los *workers* estén operativos y saludables
- **Ejemplo:** Detectar cuando un worker cae, se cuelga o consume recursos anormales

### 1.2 Caso de Uso Principal: Análisis Genómico

**Problema:** Buscar todas las ocurrencias de un patrón de ADN (ej: `AGGTCCAT`) en un archivo de secuencia genómica de 200MB.

**Solución Distribuida:**
1. Dividir el archivo en ~200 chunks de ~1MB cada uno
2. Distribuir los chunks a múltiples workers (5 por defecto) para procesamiento paralelo
3. Mientras procesan, monitorear su estado de salud en tiempo real
4. Agregar los resultados parciales en un resultado final
5. Persistir el resultado y estadísticas en Redis

**Por qué este caso de uso:**
- Es CPU-bound (justifica paralelización)
- Es divisible (justifica grid computing)
- Exige recursos (demuestra necesidad de monitoreo)

---
## 2. Arquitectura del Sistema

### 2.1 Diagramas de Arquitectura

Para una comprensión visual de la arquitectura, consulte los siguientes diagramas:

*   **Arquitectura General:** [Diagrama del Sistema Distribuido](docs/diagramas/diagrama-logico.png)
*   **Arquitectura de Contenedores (Docker):** [Diagrama de Contenedores](#71-arquitectura-de-contenedores)

### 2.2 Topología de Red

**Conexiones TCP (Sockets):**
1. `Cliente CLI` ↔ `Master` (puerto 5000)
2. `Agentes` → `Collector` (puerto 6000)
3. `Collector` → `Master` (puerto 5000)

**Conexiones IPC (Unix Domain Sockets):**
- `Worker` ↔ `Agente` (mismo contenedor/host)

**Redis:**
- `Master`, `Workers` → Redis (puerto 6379)

### 2.3 Flujo de la Información

**Comunicación Local (IPC - dentro del mismo contenedor):**
- Worker ↔ Agente: Unix Domain Socket para heartbeats constantes (no solo durante ejecucion)
- Procesos Celery internos: `multiprocessing.Queue` y `Lock` (solo dentro de cada Worker)

**Comunicación Distribuida (TCP - entre contenedores):**
- Cliente → Master: Sockets TCP (envío de trabajos)
- Agente → Collector: Sockets TCP (reporte de métricas)
- Collector → Master: Sockets TCP (notificaciones de alertas)

**Comunicación vía Redis:**
- Master → Workers: Celery Queue. DB I (distribución de chunks)
- Workers → Redis: Almacenamiento de resultados parciales. DB II

```
[Cliente] ---(TCP)---> [Master] ---(Redis)---> [Workers]
                          ▲                        │
                          │                        │ (IPC local)
                          │                        ▼
                          │                   [Agentes]
                          │                        │
                          │                        │ (TCP)
                          │                        ▼
                          └──(TCP alerta)──── [Collector]
```

---

## 3. Componentes Detallados

### 3.1 Cliente CLI (`submit_job.py`)

**Propósito:** Interfaz de línea de comandos para enviar trabajos al grid.

**Tecnologías:**
- `argparse` para parseo de argumentos
- `socket` para conexión TCP al Master
- `json` para serialización de mensajes

**Argumentos:**
```bash
python submit_job.py \
  --server localhost \
  --port 5000 \
  --file genome.txt \
  --pattern "AGGTCCAT" \
```

**Protocolo de Comunicación:**
```json
// REQUEST (Cliente -> Master)
{
  "type": "submit_job",
  "job_id": "uuid-generado-por-cliente",
  "filename": "genome.txt",
  "pattern": "AGGTCCAT",
  "chunk_size": 1048576,
  "file_size": 209715200,
  "file_data_b64": "base64_encoded_data..."  // Archivo codificado en base64
}

// RESPONSE (Master -> Cliente)
{
  "status": "accepted",
  "job_id": "uuid-generado-por-cliente",
  "total_chunks": 200,
  "estimated_time": 120  // segundos
}
```

**Funcionalidades:**
- Validar que el archivo existe
- Calcular tamaño y estimar chunks
- Enviar archivo al Master
- Recibir confirmación con `job_id`

---

### 3.2 Cliente CLI (`query_job.py`)

**Propósito:** Interfaz de línea de comandos para consultar el estado de un trabajo en el grid.

**Tecnologías:**
- `argparse` para parseo de argumentos
- `socket` para conexión TCP al Master
- `json` para serialización de mensajes

**Argumentos:**
```bash
python src/query_job.py \
  --server localhost \
  --port 5000 \
  --job-id "uuid-del-trabajo" \
  --show-results \
  --output-html "reporte.html"
```

**Protocolo de Comunicación:**
El request y response para la consulta de estado ya están definidos en la sección `4.2 Mensajes Cliente ↔ Master`.

**Funcionalidades:**
- Consultar el estado de un trabajo mediante su `job_id`.
- Mostrar el progreso del trabajo en la consola.
- Opcionalmente, mostrar los resultados finales si el trabajo ha sido completado.
- Opcionalmente, generar un reporte HTML con el estado detallado del trabajo.

---

### 3.3 Servidor Master (`master_server.py`)

**Propósito:** Orquestador central del sistema de cómputo.

**Tecnologías:**
- `asyncio` para servidor asíncrono
- `sockets` (via `asyncio.start_server`) para conexiones TCP
- `celery` para encolar tareas en Redis (DB I)
- `redis` (librería de gestion con python) para persistencia de datos

**Responsabilidades:**

1.  **Recepción de Trabajos:**
    *   Escucha en el puerto 5000.
    *   Acepta múltiples clientes concurrentemente.
    *   Valida el formato JSON del trabajo.

2.  **Creación y Encolado del Trabajo:**
    *   Crea un hash en Redis para almacenar toda la información y el estado del trabajo (`job:{job_id}`).
    *   Divide el archivo en bloques de **1MB** (configurable en `settings.py`).
    *   Agrega un solapamiento (overlap) entre chunks para no perder patrones en las fronteras.
    *   Por cada chunk, encola una tarea en Celery: `tasks.find_pattern.delay(...)`.

3.  **Consulta de Estado:**
    *   Responde a las peticiones del cliente (`query_job.py`) sobre el estado de un trabajo, leyendo la información directamente del hash de Redis.

4.  **Comunicación con Collector:**
    *   Recibe notificaciones de workers caídos y las registra. El re-encolado de tareas es gestionado automáticamente por Celery.

**Estructura del Código:**

**Persistencia en Redis:**
El Master crea un **único hash por trabajo** que centraliza toda la información. Los workers actualizan este hash de forma atómica.

```
# Hash principal del trabajo
job:{job_id} (HASH)
  - "status": "processing" | "completed" | "failed"
  - "total_chunks": 200,
  - "processed_chunks": 0 (incrementado por los workers)
  - "matches_found": 0 (incrementado por los workers)
  - "filename": "genome.txt"
  - ... (otros metadatos)

# Lista de resultados detallados (actualmente no utilizada por el cliente)
job:{job_id}:results (LIST) -> [json_result_chunk_1, json_result_chunk_2, ...]
```

---

### 3.4 Celery Worker (`genome_worker.py`)

**Propósito:** Procesar chunks de datos (CPU-bound).

**Tecnologías:**
- `celery` como framework de workers
- `re` expresion regular para búsqueda de patrones (funcion: `re.finditer`)
- `redis` para actualización de estado

**Responsabilidades:**
1.  **Procesamiento de Chunks:**
    *   Recibe un chunk de datos y un patrón a buscar.
    *   Encuentra todas las ocurrencias del patrón en el chunk.
2.  **Actualización Atómica en Redis:**
    *   Usa `HINCRBY` para incrementar atómicamente los contadores `processed_chunks` y `matches_found` en el hash `job:{job_id}`.
    *   Esto asegura que el progreso se actualiza de forma concurrente y sin generar bloqueos.
3.  **Comunicación con Agente:**
    *   Inicia un hilo en segundo plano para enviar un `heartbeat` al Agente Monitor local cada 5 segundos vía Unix Socket.


**Configuración:**
- Concurrencia: 5 procesos por worker 
- Prefetch: 2 (no acaparar tareas)
- Ack_late: True (reencolar si worker cae antes de completar tarea)

**Comando de inicio:**
```bash
celery -A genome_worker worker \
  --loglevel=info \
  --concurrency=4 \
  --hostname=worker1@%h
```

---

### 3.5 Agente Monitor (`monitor_agent.py`)

**Propósito:** Monitorear la salud del worker en su misma máquina/contenedor.

**Tecnologías:**
- `psutil` para métricas del sistema
- `socket` (*Unix* Domain Socket) para IPC con Worker
- `socket` (*TCP*) para reportar al Collector
- `asyncio` para loop principal

**Responsabilidades:**

1. **Recolección de Métricas:**
   - CPU usage (`cpu_percent`)
   - Memory usage (`memory_percent`)

2. **Comunicación IPC con Worker:**
   - Crear Unix Domain Socket: `/tmp/worker_{id}.sock`
   - Escuchar heartbeats del worker cada 5 segundos
   - Si no recibe heartbeat en 15 segundos → reportar como **DEAD** al Worker

3. **Reporte al Collector:**
   - Cada 10 segundos enviar métricas
   - Si detecta estado DEAD, enviar *alerta inmediata*

**Nota importante:** El Worker de Celery con `--concurrency=4` lanza 4 procesos hijos. Cada uno puede enviar heartbeats al mismo Unix socket. El Agente, usando `asyncio.start_unix_server()`, acepta múltiples conexiones concurrentes sin problema.

---

### 3.6 Servidor Collector (`collector_server.py`)

**Propósito:** Centralizar monitoreo de todos los workers y generar alertas.

**Tecnologías:**
- `asyncio` para servidor asíncrono
- `sockets` *TCP* para recibir métricas de Agentes y enviar alertas al Master

**Responsabilidades:**

1.  **Recepción de Métricas:**
    *   Escucha en el puerto 6000 y acepta conexiones de múltiples agentes.
    *   Mantiene un registro en memoria del último `heartbeat` recibido de cada worker.

2.  **Detección de Anomalías:**
    *   Si un agente reporta `status = "DEAD"`, se considera una alerta crítica.
    *   Inicia un monitor en segundo plano que comprueba cada 15 segundos si algún worker ha dejado de enviar métricas (timeout de 30 segundos).

3.  **Generación de Alertas:**
    *   Ante una anomalía crítica, registra el evento en los logs.
    *   Notifica directamente al Master Server vía TCP para que registre el incidente.

---

## 4. Protocolos de Comunicación

### 4.1 Formato de Mensajes JSON

Todos los mensajes entre componentes usan **JSON** con **protocolos** definidos en `protocol.py`.
Estos protocolos siguen la siguiente estructura base:

```json
{
  "type": "message_type",
  "timestamp": 1234567890.123,
  "data": { ... }
}
```

### 4.2 Mensajes Cliente ↔ Master

**Submit Job:**
```json
{
  "type": "submit_job",
  "job_id": "uuid-generado-por-cliente",
  "filename": "genome.txt",
  "pattern": "AGGTCCAT",
  "chunk_size": 51200,
  "file_size": 209715200,
  "file_data_b64": "..."
}
```

**Job Status Query:**
```json
{
  "type": "query_status",
  "job_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

**Response:**
```json
{
  "status": "processing",
  "job_id": "uuid-generado-por-cliente",
  "progress": {
    "total_chunks": 200,
    "processed_chunks": 2048,
    "percentage": 50.0
  },
  "partial_results": {
    "matches_found": 42
  }
}
```

### 4.3 Mensajes Agente → Collector

**Metrics Report:**
```json
{
  "type": "metrics",
  "data": {
    "worker_id": "worker_1",
    "timestamp": 1234567890.123,
    "status": "ALIVE",
    "cpu_percent": 87.5,
    "memory_mb": 1024.5,
    "memory_percent": 45.2,
    "tasks_processed": 128
  }
}
```

### 4.4 Mensajes Collector → Master

**Worker Down Notification:**
```json
{
  "type": "worker_down",
  "worker_id": "worker_3",
  "timestamp": 1234567890.123,
  "last_task_id": "abc123-task-id"
}
```

### 4.5 IPC Worker ↔ Agente (Unix Socket)

**Heartbeat:**
```json
{
  "type": "heartbeat",
  "timestamp": 1234567890.123,
  "tasks_completed": 10
}
```

---

## 5. Cumplimiento de Requisitos

### 5.1 Requisitos Obligatorios de la Cátedra

| Requisito | Implementación | Justificación |
|-----------|----------------|---------------|
| **Sockets con múltiples clientes** | `asyncio.start_server()` en Master y Collector | Master maneja N clientes CLI concurrentemente. Collector maneja N agentes. No se usa framework web, sino sockets directos. |
| **Asincronismo I/O** | `asyncio` con `async/await` | Crítico para que Master y Collector manejen cientos de conexiones sin bloquearse. Permite I/O concurrente eficiente. |
| **Cola de tareas distribuidas** | `Celery + Redis` | (1) Workers procesan chunks CPU-bound. (2) Collector encola alertas I/O-bound. Demuestra versatilidad del patrón. |
| **Mecanismos IPC** | Unix Domain Sockets | Worker y Agente (procesos distintos, mismo host) se comunican vía socket Unix para heartbeats. Es IPC puro, no red. |
| **Parseo de argumentos CLI** | `argparse` | Cliente, Master, Collector, Worker, Agente: todos usan `argparse` para configuración (--port, --host, --worker-id, etc.). |
| **Soporte Dual-Stack (IPv4/IPv6)** | `socket.getaddrinfo` | Los clientes y servidores utilizan `getaddrinfo` para resolver un hostname a una lista de posibles direcciones (IPv4 e IPv6) e intentan conectarse a la primera que funcione, garantizando compatibilidad en distintas configuraciones de red. |

### 5.2 Requisitos Adicionales Implementados

- **Docker/Docker Compose:** Despliegue completo y orquestado de todo el sistema, garantizando un entorno de ejecución consistente y facilitando la escalabilidad.
- **Persistencia con Redis:** Uso de Redis no solo como broker de Celery, sino como una base de datos clave-valor para almacenar el estado, progreso y resultados de los trabajos.
- **Logging Estructurado (JSON):** Todos los componentes generan logs en formato JSON, lo que facilita el análisis, la búsqueda y la integración con sistemas de monitoreo centralizado.
- **Manejo Robusto de Errores:** Implementación de bloques `try-except` en todas las operaciones de red e IPC para evitar caídas inesperadas y registrar información útil para el debugging.
- **Métricas del Sistema con `psutil`:** Recolección de métricas de uso de CPU y memoria en tiempo real para el monitoreo de la salud de los nodos de cómputo.
- **Protocolo JSON Validado:** Todos los mensajes intercambiados entre componentes siguen un protocolo estricto definido y validado con `protocol.py`, asegurando la integridad de la comunicación.
- **Tolerancia a Fallos y Alta Disponibilidad:** El sistema es resiliente a la caída de workers. Gracias a la configuración de Celery (`ack_late=True`), las tareas no confirmadas se re-encolan automáticamente para ser procesadas por otros workers disponibles.
- **Escalabilidad Horizontal:** La arquitectura permite escalar fácilmente el poder de cómputo añadiendo más instancias de workers
- **Actualizaciones de Estado Atómicas:** Los workers actualizan el progreso de los trabajos en Redis usando operaciones atómicas (`HINCRBY`), lo que previene condiciones de carrera y garantiza la consistencia de los datos sin necesidad de bloqueos.

---

## 6. Core del Stack Tecnológico

| Componente | Versión | Uso |
|------------|---------|-----|
| **Python** | 3.11+ | Lenguaje principal |
| **asyncio** | stdlib | Servidores asíncronos (Master, Collector) |
| **sockets** | stdlib | Comunicación de red de bajo nivel |
| **Celery** | 5.3+ | Cola de tareas distribuidas |
| **Redis** | 7.0+ | (1) Broker Celery, (2) Persistencia, (3) Estado |
| **multiprocessing** | stdlib | IPC con Unix Domain Sockets |
| **argparse** | stdlib | CLI parsing |
| **psutil** | 5.9+ | Métricas del sistema |
| **Docker** | 24+ | Contenedorización |

Mas info en `requirements.txt`

---

## 7. Despliegue con Docker 🐳

El sistema está completamente dockerizado para garantizar la portabilidad y facilitar el despliegue. Se utiliza Docker Compose para orquestar los diferentes servicios (Master, Collector, Workers, Redis).

Para una explicación detallada de las decisiones de diseño, la configuración de la red, los volúmenes y los comandos específicos de cada servicio, consulte el documento [**Explicación de Docker en el Proyecto (`docs/DOCKER_EXPLAIN.md`)**](docs/DOCKER_EXPLAIN.md).

### 7.1 Arquitectura de Contenedores

El siguiente diagrama ilustra cómo los diferentes servicios interactúan como contenedores dentro de la red de Docker:

![Diagrama de Contenedores Docker](docs/diagramas/diagrama%20contenedores.png)

### 7.2 Comandos de Despliegue

```bash
# Build de todas las imágenes
docker-compose build

# Levantar todo el sistema
docker-compose up -d

# Ver logs en tiempo real
docker-compose logs -f

# Ver logs de un componente específico
docker-compose logs -f master
docker-compose logs -f worker1

# Escalar workers (agregar más)
docker-compose up -d --scale worker=5

# Detener todo
docker-compose down

# Detener y limpiar volúmenes
docker-compose down -v
```

---

## 8. Consideraciones de Implementación

### 8.1 Gestión de Chunks con Overlap

**Problema:** Si un patrón de ADN cae justo en la frontera entre dos chunks, puede no detectarse.

**Solución:** Agregar overlap entre chunks.

**Post-procesamiento:** Al agregar resultados, eliminar duplicados en zonas de overlap usando las posiciones absolutas.

### 8.2 Manejo de Conexiones Persistentes vs Efímeras

**Decisión de Diseño:**

- **Cliente → Master:** Conexión efímera (1 request = 1 conexión)
- **Agente → Collector:** Conexión efímera pero frecuente (cada 10 segundos)
- **Collector → Master:** Conexión efímera solo cuando hay alerta
- **Worker ↔ Agente (IPC):** Socket persistente (el Agente escucha, Worker conecta cuando necesita)

**Justificación:** Para I/O-bound con asyncio, conexiones efímeras son suficientes y más simples. No necesitamos WebSockets ni conexiones persistentes para este proyecto.

### 8.3 Formato de Archivo Genoma

**Formato esperado:** Texto plano ASCII con caracteres `A`, `C`, `G`, `T` (nucleótidos).

```
# Ejemplo: data/genome_sample.txt
AGGTCCATAGCTAGCTAGCTACGATCGATCGTAGCTAGCTAGCTACGATCGATCGATCG
TAGCTAGCTAGCTAGCTAGCTAGCTAGCTAGCTAGCTAGCTAGCTAGCTAGCTAGCTAGC
AGGTCCATAGCTAGCTAGCTACGATCGATCGTAGCTAGCTAGCTACGATCGATCGATCG
...
```

**Generación del archivo de 200MB:**
```bash
# Script para generar genoma sintético
python scripts/generate_genome.py --size 200 --output data/genome_sample.txt
```

### 8.4 Algoritmo de Búsqueda de Patrones

**Opciones:**

1. **Regex simple:** `re.finditer(pattern, text)` - O(n*m) peor caso, pero suficiente para el proyecto
2. **KMP:** O(n+m) - Más eficiente, pero más complejo
3. **Boyer-Moore:** O(n/m) caso promedio - El más rápido para patrones largos

**Decisión:** Usar **regex** por simplicidad. Si se necesita optimizar, implementar KMP.

### 8.5 Estrategia de Re-encolado

**Situación:** Worker cae con tareas asignadas pero no completadas.

**Estrategia (Aprovechando features de Celery):**

Celery proporciona mecanismos automáticos de re-encolado cuando se configura correctamente:

1. **`ack_late=True`**: Worker confirma tarea DESPUÉS de completarla (no antes)
2. **`reject_on_worker_lost=True`**: Si worker cae, Celery automáticamente re-encola la tarea
3. El Master solo necesita:
   - Recibir notificación del Collector cuando un worker cae
   - Loggear el evento para auditoría
   - Opcionalmente, marcar en Redis: `worker:{id}:status = DEAD`

### 8.6 Logging Estructurado

**Estándar:** Todos los logs en formato JSON para fácil parsing e interpretacion.

### 8.7 Seguridad y Validación

**Validaciones Necesarias:**

1. **Tamaño de archivo:** Rechazar archivos > 500MB
2. **Patrón:** Solo caracteres A, C, G, T
3. **Rate limiting:** Max 10 jobs por cliente por minuto
4. **Sanitización:** Validar todos los inputs JSON

### 8.8 Troubleshooting y Debugging
Pueden habilitarse logs mas detallados para realizar un debugging

**Habilitar logs detallados:**
```bash
# En docker-compose.yml, agregar:
environment:
  - LOG_LEVEL=DEBUG
  - CELERY_LOG_LEVEL=DEBUG
```

---

## 9. Scripts de Utilidad

Para facilitar el desarrollo, las pruebas y el despliegue, el proyecto incluye varios scripts de utilidad en el directorio `scripts/`.

### 9.1 Script de Ejecución de Prueba (`scripts/ejecucionCLI.sh`)

Este script automatiza un flujo de trabajo completo para probar la funcionalidad principal del sistema:
1.  Envía un nuevo trabajo de análisis genómico usando `submit_job.py`.
2.  Captura el `job_id` devuelto por el servidor.
3.  Consulta el estado de ese trabajo en un bucle usando `query_job.py` hasta que se completa.
4.  Una vez completado, genera un reporte final en formato HTML.

**Uso:**
```bash
./scripts/ejecucionCLI.sh
```

### 9.2 Script de Limpieza de Docker (`scripts/restart_docker_clean.sh`)

Este es un script de utilidad para desarrolladores que **limpia completamente el entorno de Docker**. Es útil cuando se necesita un reinicio total del sistema para evitar problemas de caché.

**¡Advertencia!** Este script es destructivo. Eliminará:
- Todos los contenedores (en ejecución y detenidos).
- Todas las imágenes de Docker.
- Todos los volúmenes no utilizados (incluyendo el de Redis si no está en uso).
- Todas las redes personalizadas.

Después de la limpieza, reconstruye y levanta el sistema con `docker compose up -d --build`.

**Uso:**
```bash
./scripts/restart_docker_clean.sh
```

### 9.3 Script de Instalación de Dependencias (`scripts/install_requirements.sh`)

Este script facilita la configuración de un entorno de desarrollo local **sin usar Docker**.
1.  Crea un entorno virtual de Python en `venv/`.
2.  Activa el entorno virtual.
3.  Instala todas las dependencias listadas en `requirements.txt`.

**Uso:**
```bash
./scripts/install_requirements.sh
```

---

## 10. Contacto y Contribuciones

**Autor:** Martin Salvatore
**Materia:** Computación II - Universidad de Mendoza  
**Fecha:** Noviembre 2025

**Para consultas sobre el proyecto:**
- Email: martingsalvatore@gmail.com