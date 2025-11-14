# Proyecto Final: Sistema Distribuido de Cómputo y Monitoreo

**Estado:** 🚀 Documento Definitivo de Arquitectura v2.0

Este repositorio contiene el proyecto final para la materia Computación II. Es un sistema distribuido desarrollado en Python que implementa dos subsistemas paralelos e interconectados:

1. **Sistema A - Grid de Cómputo:** Procesa tareas CPU-bound (análisis genómico) de forma paralela y distribuida.
2. **Sistema B - Sistema de Monitoreo:** Vigila la salud de los nodos del grid en tiempo real.

**Objetivo Académico:** Aplicar y demostrar dominio de herramientas de bajo/medio nivel (sockets, IPC, asyncio, colas de tareas) para construir un sistema robusto, concurrente y escalable sin frameworks de alto nivel para comunicación de red.

---

## 📖 Índice

* [1. Visión General del Proyecto](#1-visión-general-del-proyecto)
* [2. Arquitectura del Sistema](#2-arquitectura-del-sistema)
* [3. Componentes Detallados](#3-componentes-detallados)
* [4. Protocolos de Comunicación](#4-protocolos-de-comunicación)
* [5. Flujo de Datos Completo](#5-flujo-de-datos-completo)
* [6. Stack Tecnológico](#6-stack-tecnológico)
* [7. Despliegue con Docker](#7-despliegue-con-docker)
* [8. Estructura del Repositorio](#8-estructura-del-repositorio)
* [9. Casos de Uso y Escenarios](#9-casos-de-uso-y-escenarios)
* [10. Consideraciones de Implementación](#10-consideraciones-de-implementación)
* [11. Métricas de Performance Esperadas](#11-métricas-de-performance-esperadas)
* [12. Troubleshooting](#12-troubleshooting)
* [13. Contacto y Contribuciones](#13-contacto-y-contribuciones)

---

## 1. Visión General del Proyecto

### 1.1 El Concepto: "El Director y El Vigilante"

El proyecto consiste en dos sistemas distribuidos que operan simultáneamente:

**🎼 El Director (Sistema A - Grid de Cómputo)**
- **Rol:** Coordinar la ejecución paralela de tareas computacionales pesadas
- **Responsabilidad:** Garantizar que el *trabajo* se complete correctamente
- **Ejemplo:** Analizar un genoma de 200MB buscando patrones específicos

**👁️ El Vigilante (Sistema B - Monitoreo)**
- **Rol:** Supervisar la salud e infraestructura de los nodos de cómputo
- **Responsabilidad:** Garantizar que los *workers* estén operativos y saludables
- **Ejemplo:** Detectar cuando un worker cae, se cuelga o consume recursos anormales

### 1.2 Caso de Uso Principal: Análisis Genómico

**Problema:** Buscar todas las ocurrencias de un patrón de ADN (ej: `AGGTCCAT`) en un archivo de secuencia genómica de 200MB.

**Solución Distribuida:**
1. Dividir el archivo en ~2000-4000 chunks de ~50KB-100KB cada uno
2. Distribuir los chunks a múltiples workers para procesamiento paralelo
3. Mientras procesan, monitorear su estado de salud en tiempo real
4. Agregar los resultados parciales en un resultado final
5. Persistir el resultado y estadísticas en Redis

**Por qué este caso de uso:**
- Es CPU-bound (justifica paralelización)
- Es divisible (justifica grid computing)
- Es realista (bioinformática es un dominio real)
- Exige recursos (demuestra necesidad de monitoreo)

---

## 2. Arquitectura del Sistema

### 2.1 Diagrama de Alto Nivel

```
                              ┌─────────────────┐
                              │   Cliente CLI   │
                              │  (submit_job)   │
                              └────────┬────────┘
                                       │ TCP Socket (JSON)
                                       ▼
                    ┌──────────────────────────────────┐
                    │     Servidor Master (A)          │
                    │   - Recibe trabajos              │
                    │   - Divide en chunks             │
                    │   - Encola tareas                │
                    │   - Agrega resultados            │
                    │   - Consulta estado workers      │◄─────┐
                    └──────┬───────────────────────────┘      │
                           │ Publica tareas                    │
                           ▼                                   │
                    ┌─────────────────┐                       │ TCP Socket
                    │   Redis Server   │                       │ (Notificaciones)
                    │  - Cola Celery   │                       │
                    │  - Resultados    │                       │
                    │  - Estado        │                       │
                    └─────────┬────────┘                       │
                              │                                │
                ┌─────────────┴─────────────┐                 │
                │ Consume tareas            │                 │
                ▼                           ▼                 │
    ┌─────────────────────┐   ┌─────────────────────┐        │
    │   Worker Node 1     │   │   Worker Node N     │        │
    │ ┌─────────────────┐ │   │ ┌─────────────────┐ │        │
    │ │ Celery Worker   │ │   │ │ Celery Worker   │ │        │
    │ │ (procesa chunks)│ │   │ │ (procesa chunks)│ │        │
    │ └────────┬────────┘ │   │ └────────┬────────┘ │        │
    │          │ Unix     │   │          │ Unix     │        │
    │          │ Socket   │   │          │ Socket   │        │
    │          │ (IPC)    │   │          │ (IPC)    │        │
    │          ▼          │   │          ▼          │        │
    │ ┌─────────────────┐ │   │ ┌─────────────────┐ │        │
    │ │ Agente Monitor  │ │   │ │ Agente Monitor  │ │        │
    │ │ - Lee métricas  │─┼───┼─│ - Lee métricas  │─┼────────┘
    │ │ - Reporta CPU   │ │   │ │ - Reporta CPU   │ │
    │ │ - Heartbeat     │ │   │ │ - Heartbeat     │ │
    │ └─────────────────┘ │   │ └─────────────────┘ │
    └─────────────────────┘   └─────────────────────┘
                │                         │
                │ TCP Socket (JSON)       │
                └────────────┬────────────┘
                             ▼
                  ┌──────────────────────┐
                  │  Servidor Collector  │
                  │       (B)            │
                  │ - Recibe métricas    │
                  │ - Detecta anomalías  │
                  │ - Genera alertas     │
                  │ - Notifica a Master  │
                  └──────────────────────┘
```

### 2.2 Topología de Red

**Conexiones TCP (Sockets):**
1. `Cliente CLI` ↔ `Master` (puerto 5000)
2. `Agentes` → `Collector` (puerto 6000)
3. `Collector` → `Master` (puerto 5000)

**Conexiones IPC (Unix Domain Sockets):**
- `Worker` ↔ `Agente` (mismo contenedor/host)

**Redis:**
- `Master`, `Workers` → Redis (puerto 6379)

### 2.3 Flujo de Información

**Comunicación Local (IPC - dentro del mismo contenedor):**
- Worker ↔ Agente: Unix Domain Socket para heartbeats
- Procesos Celery internos: `multiprocessing.Queue` y `Lock` (solo dentro de cada Worker)

**Comunicación Distribuida (TCP - entre contenedores):**
- Cliente → Master: Sockets TCP (envío de trabajos)
- Agente → Collector: Sockets TCP (reporte de métricas)
- Collector → Master: Sockets TCP (notificaciones de alertas)

**Comunicación vía Redis:**
- Master → Workers: Celery Queue (distribución de chunks)
- Workers → Redis: Almacenamiento de resultados parciales

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
  --chunk-size 51200  # 50KB por chunk (opcional)
```

**Protocolo de Comunicación:**
```json
// REQUEST (Cliente -> Master)
{
  "type": "submit_job",
  "job_id": "uuid-generado-por-cliente",
  "filename": "genome.txt",
  "pattern": "AGGTCCAT",
  "chunk_size": 51200,
  "file_size": 209715200,
  "file_data_b64": "base64_encoded_data..."  // Archivo codificado en base64
}

// RESPONSE (Master -> Cliente)
{
  "status": "accepted",
  "job_id": "uuid-generado-por-cliente",
  "total_chunks": 4096,
  "estimated_time": 120  // segundos
}
```

**Nota sobre envío de archivos grandes:**
Para la demo del proyecto, el archivo de 200MB se envía codificado en base64 dentro del JSON (~267MB). Esto es funcional para el alcance académico del proyecto. En un sistema de producción, se implementaría streaming por chunks o upload HTTP multiparte para mayor eficiencia.

**Funcionalidades:**
- Validar que el archivo existe
- Calcular tamaño y estimar chunks
- Enviar archivo al Master (puede hacerse por chunks si es muy grande)
- Recibir confirmación con `job_id`
- (Opcional) Consultar progreso: `python query_job.py --job-id <uuid>`

---

### 3.2 Servidor Master (`master_server.py`)

**Propósito:** Orquestador central del sistema de cómputo.

**Tecnologías:**
- `asyncio` para servidor asíncrono
- `sockets` (via `asyncio.start_server`) para conexiones TCP
- `celery` para encolar tareas
- `redis` (librería python) para persistencia

**Responsabilidades:**

1. **Recepción de Trabajos:**
   - Escuchar en puerto 5000
   - Aceptar múltiples clientes concurrentemente
   - Validar formato JSON del trabajo

2. **División en Chunks:**
   - Dividir archivo en bloques de ~50KB
   - Agregar overlap de N bytes entre chunks (para patrones en fronteras)
   - Generar metadatos por chunk (índice, offset, size)

3. **Encolado en Celery:**
   - Por cada chunk, publicar tarea: `tasks.find_pattern.delay(chunk_data, pattern, metadata)`
   - Guardar mapping `job_id -> [task_ids]` en Redis

4. **Agregación de Resultados:**
   - Escuchar resultados de workers (via Redis o callbacks)
   - Agregar conteo de ocurrencias
   - Guardar resultado final en Redis: `result:{job_id}`

5. **Comunicación con Collector:**
   - Recibir notificaciones de workers caídos
   - (Futuro) Re-encolar tareas de workers fallidos

**Estructura del Código:**

**Persistencia en Redis:**
```
job:{job_id}:tasks -> lista de task_ids
job:{job_id}:status -> "pending" | "processing" | "completed" | "failed"
job:{job_id}:result -> JSON con resultado final
job:{job_id}:stats -> {"total_matches": 42, "chunks_processed": 4096, ...}
```

---

### 3.3 Celery Worker (`genome_worker.py`)

**Propósito:** Procesar chunks de datos (CPU-bound).

**Tecnologías:**
- `celery` como framework de workers
- Algoritmo de búsqueda de patrones (ej: KMP, Boyer-Moore, o regex)

**Tarea Principal:**

**Configuración:**
- Concurrencia: 2-4 procesos por worker (depende de CPUs)
- Prefetch: 2 (no acaparar tareas)
- Ack_late: True (reencolar si worker cae antes de completar)

**Comando de inicio:**
```bash
celery -A genome_worker worker \
  --loglevel=info \
  --concurrency=4 \
  --hostname=worker1@%h
```

---

### 3.4 Agente Monitor (`monitor_agent.py`)

**Propósito:** Monitorear la salud del worker en su misma máquina/contenedor.

**Tecnologías:**
- `psutil` para métricas del sistema
- `socket` (Unix Domain Socket) para IPC con Worker
- `socket` (TCP) para reportar al Collector
- `asyncio` para loop principal

**Responsabilidades:**

1. **Recolección de Métricas:**
   - CPU usage (%)
   - RAM usage (MB y %)
   - Número de tareas procesadas (leer de IPC)

2. **Comunicación IPC con Worker:**
   - Crear Unix Domain Socket: `/tmp/worker_{id}.sock`
   - Escuchar heartbeats del worker cada 5 segundos
   - Si no recibe heartbeat en 15 segundos → DEAD

3. **Reporte al Collector:**
   - Cada 10 segundos enviar métricas
   - Si detecta estado DEAD, enviar alerta inmediata

**Estructura del Código:**

**IPC: Heartbeat desde Worker:**

**Nota importante:** El Worker de Celery con `--concurrency=4` lanza 4 procesos hijos. Cada uno puede enviar heartbeats al mismo Unix socket. El Agente, usando `asyncio.start_unix_server()`, acepta múltiples conexiones concurrentes sin problema.

---

### 3.5 Servidor Collector (`collector_server.py`)

**Propósito:** Centralizar monitoreo de todos los workers y generar alertas.

**Tecnologías:**
- `asyncio` para servidor asíncrono
- `sockets` para recibir métricas de agentes
- `celery` para encolar tareas de alerta
- `redis` para guardar estado de workers

**Responsabilidades:**

1. **Recepción de Métricas:**
   - Escuchar en puerto 6000
   - Aceptar conexiones de múltiples agentes
   - Parsear JSON de métricas

2. **Detección de Anomalías:**
   - Status = "DEAD" (reportado por el agente) → Alerta crítica
   - No recibe métricas de un agente por 30 seg (timeout) → Alerta crítica

3. **Generación de Alertas:**
   - Loggear la alerta (actualmente imprime en consola)
   - Notificar al Master vía TCP

4. **Persistencia en Redis:**
   - Guardar último estado de cada worker
   - Guardar historial de alertas

**Estructura del Código:**

---

## 4. Protocolos de Comunicación

### 4.1 Formato de Mensajes JSON

Todos los mensajes entre componentes usan JSON con la siguiente estructura base:

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
    "total_chunks": 4096,
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

## 5. Flujo de Datos Completo

### 5.1 Escenario Normal (Happy Path)

1. **T=0s:** Usuario ejecuta `python submit_job.py --file genome.txt --pattern AGGTCCAT`
2. **T=1s:** Cliente se conecta al Master vía TCP, envía JSON con el trabajo
3. **T=2s:** Master recibe, valida y divide archivo en 4096 chunks de 50KB
4. **T=3s:** Master encola 4096 tareas en Celery/Redis
5. **T=4s:** Los 3 Workers comienzan a consumir tareas de la cola
6. **T=5s:** Cada Worker procesa chunks, envía heartbeat a su Agente local cada 5s
7. **T=10s:** Agentes reportan métricas al Collector: CPU 95%, Status ALIVE
8. **T=15s:** Collector recibe métricas, valida, guarda en Redis, no detecta anomalías
9. **T=300s:** Workers completan todas las tareas
10. **T=301s:** Master agrega resultados de Redis, genera resultado final
11. **T=302s:** Master guarda en Redis: `result:{job_id} = {"total_matches": 142, ...}`
12. **T=303s:** Cliente puede consultar resultado con `query_job.py`

### 5.2 Escenario de Fallo (Worker Caído)

1. **T=0-100s:** Sistema procesando normally
2. **T=100s:** Worker_2 sufre segfault y muere procesando chunk #1537
3. **T=105s:** Agente_2 intenta leer heartbeat via IPC, no recibe respuesta
4. **T=115s:** Agente_2 marca status = DEAD (15s sin heartbeat)
5. **T=120s:** Agente_2 reporta al Collector: Status DEAD
6. **T=121s:** Collector detecta anomalía crítica, genera alerta
7. **T=122s:** Collector notifica al Master: `worker_down` con worker_id=worker_2
8. **T=123s:** Master loggea el evento: "Worker 2 detectado como caído"
9. **T=124s:** Celery, gracias a `ack_late=True`, automáticamente re-encola las tareas que worker_2 no completó
10. **T=125s:** Workers 1 y 3 (aún vivos) toman las tareas re-encoladas
11. **T=200s:** Sistema completa procesamiento con 2 workers

**Nota sobre re-encolado:** Celery maneja automáticamente el re-encolado de tareas cuando un worker cae antes de completarlas (configurado con `ack_late=True` y `reject_on_worker_lost=True`). El Master solo necesita registrar el evento para auditoría.

### 5.3 Diagrama de Secuencia (Submit Job)

```
Cliente          Master          Redis           Worker          Agente          Collector
  |                |               |               |               |               |
  |--submit_job--->|               |               |               |               |
  |                |--divide------>|               |               |               |
  |                |--enqueue----->|               |               |               |
  |<--accepted-----|               |               |               |               |
  |                |               |<--get_task----|               |               |
  |                |               |--task-------->|               |               |
  |                |               |               |--heartbeat--->|               |
  |                |               |               |   (IPC)       |               |
  |                |               |               |               |--metrics----->|
  |                |               |               |               |               |--validate-->
  |                |               |<--result------|               |               |
  |                |<--aggregate---|               |               |               |
  |--query-------->|               |               |               |               |
  |<--status-------|               |               |               |               |
```

---

## 6. Cumplimiento de Requisitos

### 6.1 Requisitos Obligatorios de la Cátedra

| Requisito | Implementación | Justificación |
|-----------|----------------|---------------|
| **Sockets con múltiples clientes** | `asyncio.start_server()` en Master y Collector | Master maneja N clientes CLI concurrentemente. Collector maneja N agentes. No se usa framework web, sino sockets directos. |
| **Asincronismo I/O** | `asyncio` con `async/await` | Crítico para que Master y Collector manejen cientos de conexiones sin bloquearse. Permite I/O concurrente eficiente. |
| **Cola de tareas distribuidas** | `Celery + Redis` | (1) Workers procesan chunks CPU-bound. (2) Collector encola alertas I/O-bound. Demuestra versatilidad del patrón. |
| **Mecanismos IPC** | Unix Domain Sockets | Worker y Agente (procesos distintos, mismo host) se comunican vía socket Unix para heartbeats. Es IPC puro, no red. |
| **Parseo de argumentos CLI** | `argparse` | Cliente, Master, Collector, Worker, Agente: todos usan `argparse` para configuración (--port, --host, --worker-id, etc.). |

### 6.2 Requisitos Adicionales Implementados

- **Docker/Docker Compose:** Despliegue completo con 6 contenedores
- **Persistencia:** Redis para resultados, estado de jobs, métricas
- **Logging estructurado:** Logs en JSON para análisis
- **Manejo de errores:** Try-except en todas las operaciones de red/IPC
- **Métricas del sistema:** `psutil` para CPU, RAM
- **Protocolo JSON:** Todos los mensajes son JSON bien documentados

---

## 6. Stack Tecnológico

### 7.1 Tecnologías Core

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

### 7.2 Librerías Python (requirements.txt)

```txt
# Core
celery==5.3.4
redis==5.0.1
psutil==5.9.6

# Opcional (para testing/desarrollo)
pytest==7.4.3
pytest-asyncio==0.21.1
```

### 7.3 Árbol de Dependencias

```
asyncio (stdlib)
├── sockets (stdlib)
└── json (stdlib)

Celery
└── Redis (broker + backend)

psutil
└── (sin dependencias extras)

IPC
└── socket (stdlib, AF_UNIX)
```

---

## 7. Despliegue con Docker

### 8.1 Arquitectura de Contenedores

```
┌─────────────────────────────────────────────────────┐
│                   Docker Network                    │
│                  (genome-network)                   │
│                                                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────┐ │
│  │  Master  │  │Collector │  │      Redis       │ │
│  │ :5000    │  │ :6000    │  │     :6379        │ │
│  └──────────┘  └──────────┘  └──────────────────┘ │
│       │             │                  │           │
│       └─────────────┴──────────────────┘           │
│                     │                              │
│       ┌─────────────┴─────────────┐                │
│       │                           │                │
│  ┌────▼────┐  ┌──────────┐  ┌───▼──────┐          │
│  │Worker 1 │  │Worker 2  │  │Worker 3  │          │
│  │         │  │          │  │          │          │
│  │┌───────┐│  │┌───────┐ │  │┌───────┐ │          │
│  ││Agente ││  ││Agente │ │  ││Agente │ │          │
│  │└───────┘│  │└───────┘ │  │└───────┘ │          │
│  └─────────┘  └──────────┘  └──────────┘          │
│                                                     │
└─────────────────────────────────────────────────────┘
```

### 8.2 docker-compose.yml

### 8.3 Dockerfiles

**docker/Dockerfile.master:**

**docker/Dockerfile.collector:**

**docker/Dockerfile.worker:**

### 8.4 Comandos de Despliegue

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

## 8. Estructura del Repositorio

```
final/
│
├── README.md                 # Este documento (guía principal)
├── INSTALL.md               # Instrucciones de instalación detalladas
├── INFO.md                  # Justificaciones de diseño técnico
├── TODO.md                  # Mejoras futuras y features pendientes
│
├── requirements.txt         # Dependencias Python
│
├── docker/
│   ├── Dockerfile.master
│   ├── Dockerfile.collector
│   └── Dockerfile.worker
│
├── docker-compose.yml       # Orquestación de contenedores
│
├── src/                     # Código fuente
│   ├── __init__.py
│   │
│   ├── master_server.py     # Servidor Master (Sistema A)
│   ├── collector_server.py  # Servidor Collector (Sistema B)
│   ├── genome_worker.py     # Celery Worker (CPU-bound)
│   ├── monitor_agent.py     # Agente Monitor (IPC + Métricas)
│   ├── submit_job.py        # Cliente CLI para enviar trabajos
│   ├── query_job.py         # Cliente CLI para consultar estado
│   │
│   ├── utils/
│   │   ├── __init__.py
│   │   ├── chunker.py       # Lógica de división en chunks
│   │   ├── protocol.py      # Definición de mensajes JSON
│   │   └── logger.py        # Configuración de logging
│   │

│
├── tests/                   # Tests unitarios e integración
│   ├── test_master.py
│   ├── test_collector.py
│   ├── test_worker.py
│   ├── test_agent.py
│   └── test_integration.py
│
├── data/                    # Datos de ejemplo
│   ├── genome_sample.txt    # Genoma de ejemplo (200MB)
│   └── patterns.txt         # Patrones de búsqueda
│
├── logs/                    # Directorio de logs (gitignored)
│   ├── master.log
│   ├── collector.log
│   ├── workers.log
│   └── alerts.log
│
└── docs/                    # Documentación adicional
    ├── diagrams/
    │   ├── architecture.png
    │   └── sequence.png
    ├── performance.md       # Análisis de performance
    └── troubleshooting.md   # Guía de resolución de problemas
```

---

## 9. Casos de Uso y Escenarios

### 10.1 Caso de Uso 1: Análisis Genómico Simple

**Objetivo:** Buscar patrón `AGGTCCAT` en genoma de 200MB.

**Pasos:**
```bash
# 1. Levantar sistema
docker-compose up -d

# 2. Esperar a que todos los servicios estén listos (~10 segundos)
docker-compose ps

# 3. Enviar trabajo
python src/submit_job.py \
  --server localhost \
  --port 5000 \
  --file data/genome_sample.txt \
  --pattern "AGGTCCAT"

# Output:
# Job submitted successfully!
# Job ID: 550e8400-e29b-41d4-a716-446655440000
# Total chunks: 4096
# Estimated time: ~120 seconds

# 4. Consultar progreso
python src/query_job.py \
  --server localhost \
  --port 5000 \
  --job-id 550e8400-e29b-41d4-a716-446655440000

# Output:
# Job Status: PROCESSING
# Progress: 2048/4096 chunks (50.00%)
# Matches found so far: 87
# Active workers: 3

# 5. Esperar a que termine
# (repetir comando anterior hasta ver Status: COMPLETED)

# 6. Ver resultado final
python src/query_job.py \
  --server localhost \
  --port 5000 \
  --job-id 550e8400-e29b-41d4-a716-446655440000 \
  --show-results

# Output:
# Job Status: COMPLETED
# Total matches: 142
# Processing time: 118.5 seconds
# Average time per chunk: 0.029 seconds
# Workers used: 3
```

### 10.2 Caso de Uso 2: Simulación de Fallo de Worker

**Objetivo:** Demostrar que el sistema detecta y reporta cuando un worker cae.

**Pasos:**
```bash
# 1. Sistema funcionando normally
docker-compose up -d

# 2. Enviar trabajo grande
python src/submit_job.py --file data/genome_sample.txt --pattern "AGGTCCAT"

# 3. Mientras procesa, matar un worker
docker kill genome-worker2

# 4. Observar logs del Collector
docker-compose logs -f collector

# Output esperado:
# [2024-10-30 12:34:56] WARNING: Worker worker2 no reporta hace 15 segundos
# [2024-10-30 12:35:11] CRITICAL: Worker worker2 Status=DEAD
# [2024-10-30 12:35:12] INFO: Alerta enviada al Master
# [2024-10-30 12:35:12] INFO: Tareas de worker2 re-encoladas

# 5. Observar logs del Master
docker-compose logs -f master

# Output esperado:
# [2024-10-30 12:35:12] WARNING: Recibida notificación de worker_down: worker2
# [2024-10-30 12:35:13] INFO: Encontradas 47 tareas pendientes de worker2
# [2024-10-30 12:35:14] INFO: Re-encolando tareas...
# [2024-10-30 12:35:15] INFO: 47 tareas re-encoladas exitosamente

# 6. Verificar que el trabajo se completa con los workers restantes
python src/query_job.py --job-id <uuid>
# Status: COMPLETED (con solo 2 workers activos)
```

### 10.3 Caso de Uso 3: Monitoreo de Métricas en Tiempo Real

**Objetivo:** Ver métricas de los workers mientras procesan.

**Pasos:**
```bash
# 1. Conectarse a Redis para ver métricas
docker exec -it genome-redis redis-cli

# 2. Ver estado de todos los workers
127.0.0.1:6379> KEYS worker:*:metrics
1) "worker:worker1:metrics"
2) "worker:worker2:metrics"
3) "worker:worker3:metrics"

# 3. Ver métricas de un worker específico
127.0.0.1:6379> GET worker:worker1:metrics
"{\"worker_id\": \"worker1\", \"cpu_percent\": 95.2, \"memory_percent\": 42.1, \"status\": \"ALIVE\"}"

# 4. Ver alertas generadas
127.0.0.1:6379> LRANGE alerts:history 0 -1

# 5. Ver estado de un job
127.0.0.1:6379> GET job:550e8400-e29b-41d4-a716-446655440000:status
"processing"

127.0.0.1:6379> LLEN job:550e8400-e29b-41d4-a716-446655440000:tasks
(integer) 4096

127.0.0.1:4096> LLEN job:550e8400-e29b-41d4-a716-446655440000:results
(integer) 2048
```

---

## 10. Consideraciones de Implementación

### 11.1 Gestión de Chunks con Overlap

**Problema:** Si un patrón de ADN cae justo en la frontera entre dos chunks, puede no detectarse.

**Solución:** Agregar overlap entre chunks.

**Post-procesamiento:** Al agregar resultados, eliminar duplicados en zonas de overlap usando las posiciones absolutas.

### 11.2 Manejo de Conexiones Persistentes vs Efímeras

**Decisión de Diseño:**

- **Cliente → Master:** Conexión efímera (1 request = 1 conexión)
- **Agente → Collector:** Conexión efímera pero frecuente (cada 10 segundos)
- **Collector → Master:** Conexión efímera solo cuando hay alerta
- **Worker ↔ Agente (IPC):** Socket persistente (el Agente escucha, Worker conecta cuando necesita)

**Justificación:** Para I/O-bound con asyncio, conexiones efímeras son suficientes y más simples. No necesitamos WebSockets ni conexiones persistentes para este proyecto.

### 11.3 Formato de Archivo Genoma

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

### 11.4 Algoritmo de Búsqueda de Patrones

**Opciones:**

1. **Regex simple:** `re.finditer(pattern, text)` - O(n*m) peor caso, pero suficiente para el proyecto
2. **KMP:** O(n+m) - Más eficiente, pero más complejo
3. **Boyer-Moore:** O(n/m) caso promedio - El más rápido para patrones largos

**Decisión:** Usar **regex** por simplicidad. Si se necesita optimizar, implementar KMP.

### 11.5 Estrategia de Re-encolado

**Situación:** Worker cae con tareas asignadas pero no completadas.

**Estrategia (Aprovechando features de Celery):**

Celery proporciona mecanismos automáticos de re-encolado cuando se configura correctamente:

1. **`ack_late=True`**: Worker confirma tarea DESPUÉS de completarla (no antes)
2. **`reject_on_worker_lost=True`**: Si worker cae, Celery automáticamente re-encola la tarea
3. El Master solo necesita:
   - Recibir notificación del Collector cuando un worker cae
   - Loggear el evento para auditoría
   - Opcionalmente, marcar en Redis: `worker:{id}:status = DEAD`

**Implementación:**

**En el Master:**

**Nota para implementación:** El sistema de re-encolado automático de Celery es robusto y bien probado. Para este proyecto académico, aprovechar estas features es más profesional que implementar lógica custom que puede tener bugs.

### 11.6 Logging Estructurado

**Estándar:** Todos los logs en formato JSON para fácil parsing.

**Uso:**

### 11.7 Seguridad y Validación

**Validaciones Necesarias:**

1. **Tamaño de archivo:** Rechazar archivos > 500MB
2. **Patrón:** Solo caracteres A, C, G, T
3. **Rate limiting:** Max 10 jobs por cliente por minuto
4. **Sanitización:** Validar todos los inputs JSON

---

## 11. Métricas de Performance Esperadas

### 13.1 Benchmarks Objetivo

Con la configuración de 3 workers (4 cores cada uno):

| Métrica | Valor Esperado |
|------------|---------------|
| **Tiempo de procesamiento (200MB)** | 90-150 segundos |
| **Throughput** | ~1.5-2 MB/s |
| **Chunks por segundo** | ~30-40 |
| **Latencia de heartbeat (IPC)** | < 10ms |
| **Latencia de reporte de métricas** | < 100ms |
| **Tiempo de detección de fallo** | 15-20 segundos |
| **Overhead de monitoring** | < 5% CPU por agente |

### 13.2 Factores que Afectan Performance

1. **Tamaño de chunk:** 50KB es óptimo (más pequeño → overhead, más grande → desbalance)
2. **Overlap:** 100 bytes es suficiente (patrones de ADN típicos < 50 bases)
3. **Concurrencia de Celery:** 4 procesos por worker es óptimo para CPUs de 4 cores
4. **Algoritmo de búsqueda:** Regex es O(n*m), KMP sería O(n+m) pero más complejo

### 13.3 Cómo Medir Performance

---

## 12. Troubleshooting

### 15.1 Problemas Comunes

**Problema:** Workers no pueden conectarse a Redis
```
Error: ConnectionError: Error 111 connecting to redis:6379
```
**Solución:**
```bash
# Verificar que Redis está corriendo
docker-compose ps redis

# Verificar red de Docker
docker network inspect genome-network

# Restart de Redis
docker-compose restart redis
```

---

**Problema:** IPC socket no existe
```
Error: [Errno 2] No such file or directory: '/tmp/worker_1.sock'
```
**Solución:**
```bash
# Verificar que el Agente está corriendo antes que el Worker
# En docker-compose.yml, el Agente debe iniciar primero:
command: >
  sh -c "
    python src/monitor_agent.py ... & 
    sleep 2  # Esperar a que Agente cree el socket
    celery -A src.genome_worker worker ...
  "
```

---

**Problema:** Celery no encuentra las tareas
```
Error: Received unregistered task of type 'tasks.find_pattern'
```
**Solución:**

---

**Problema:** Master no puede dividir archivo grande
```
Error: MemoryError: Unable to allocate array
```
**Solución:**

---

**Problema:** Collector recibe métricas duplicadas
```
Warning: Received metrics from worker_1 twice in 1 second
```
**Solución:**

### 15.2 Logs de Debugging

**Habilitar logs detallados:**
```bash
# En docker-compose.yml, agregar:
environment:
  - LOG_LEVEL=DEBUG
  - CELERY_LOG_LEVEL=DEBUG
```

**Ver logs estructurados:**
```bash
# Filtrar logs JSON por nivel
docker-compose logs master | jq 'select(.level=="ERROR")'

# Ver solo mensajes
docker-compose logs collector | jq '.message'

# Contar alertas por worker
docker-compose logs collector | jq 'select(.message | contains("ALERT"))' | jq -r '.worker_id' | sort | uniq -c
```

---

## 13. Contacto y Contribuciones

**Autor:** [Tu Nombre]  
**Materia:** Computación II - [Universidad]  
**Fecha:** Octubre 2025

**Para consultas sobre el proyecto:**
- Email: [tu-email]
- GitHub: [tu-repo]

---

## Apéndices

### Apéndice A: Comandos Útiles de Docker

```bash
# Ver uso de recursos de contenedores
docker stats

# Ejecutar comando en contenedor
docker exec -it genome-master bash

# Ver variables de entorno
docker exec genome-worker1 env

# Inspeccionar red
docker network inspect genome-network

# Ver volúmenes
docker volume ls
docker volume inspect genome_redis-data

# Limpiar todo (cuidado!)
docker-compose down -v
docker system prune -a
```

### Apéndice B: Comandos Útiles de Redis

```bash
# Conectarse a Redis
docker exec -it genome-redis redis-cli

# Ver todas las keys
KEYS *

# Ver tamaño de una key
MEMORY USAGE job:uuid:tasks

# Ver info de Redis
INFO

# Ver estadísticas de Celery
LLEN celery  # Tareas pendientes
KEYS celery-task-meta-*

# Limpiar todo (cuidado!)
FLUSHALL
```

### Apéndice C: Comandos Útiles de Celery

```bash
# Ver workers activos
celery -A src.genome_worker inspect active

# Ver estadísticas
celery -A src.genome_worker inspect stats

# Ver tareas registradas
celery -A src.genome_worker inspect registered

# Purgar todas las tareas
celery -A src.genome_worker purge

# Ver workers conectados
celery -A src.genome_worker inspect ping
```

### Apéndice D: Glosario de Términos

- **Chunk:** Fragmento del archivo genoma (típicamente 50KB)
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
```