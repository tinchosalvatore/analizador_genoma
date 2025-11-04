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
* [6. Cumplimiento de Requisitos](#6-cumplimiento-de-requisitos)
* [7. Stack Tecnológico](#7-stack-tecnológico)
* [8. Despliegue con Docker](#8-despliegue-con-docker)
* [9. Estructura del Repositorio](#9-estructura-del-repositorio)
* [10. Casos de Uso y Escenarios](#10-casos-de-uso-y-escenarios)
* [11. Consideraciones de Implementación](#11-consideraciones-de-implementación)

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
```python
# Pseudo-código
async def main():
    server = await asyncio.start_server(handle_client, '0.0.0.0', 5000)
    await server.serve_forever()

async def handle_client(reader, writer):
    data = await reader.read(8192)
    message = json.loads(data.decode())
    
    # Manejar diferentes tipos de mensajes
    if message['type'] == 'submit_job':
        job_id = message['job_id']
        chunks = divide_file(message['file_data'], message['chunk_size'])
        
        for i, chunk in enumerate(chunks):
            task = tasks.find_pattern.delay(
                chunk, 
                message['pattern'],
                {'job_id': job_id, 'chunk_id': i}
            )
            redis_client.rpush(f'job:{job_id}:tasks', task.id)
        
        response = {'status': 'accepted', 'job_id': job_id}
        writer.write(json.dumps(response).encode())
        await writer.drain()
    
    elif message['type'] == 'worker_down':
        # Alerta recibida del Collector
        await handle_worker_down_alert(message)
    
    elif message['type'] == 'query_status':
        # Consulta de estado del cliente
        await handle_status_query(message, writer)
```

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
```python
from celery import Celery
import re

app = Celery('genome_tasks', broker='redis://redis:6379/0')

@app.task(bind=True)
def find_pattern(self, chunk_data: bytes, pattern: str, metadata: dict):
    """
    Busca todas las ocurrencias de 'pattern' en 'chunk_data'.
    
    Args:
        chunk_data: Bytes del chunk a procesar
        pattern: Patrón de ADN a buscar (ej: "AGGTCCAT")
        metadata: {'job_id': str, 'chunk_id': int}
    
    Returns:
        {
            'chunk_id': int,
            'matches': int,
            'positions': [list of positions],  # Opcional
            'processing_time': float
        }
    """
    import time
    start = time.time()
    
    # Decodificar chunk
    text = chunk_data.decode('utf-8')
    
    # Buscar patrón (usando regex simple, puede optimizarse)
    matches = list(re.finditer(pattern, text))
    
    result = {
        'chunk_id': metadata['chunk_id'],
        'matches': len(matches),
        'positions': [m.start() for m in matches],
        'processing_time': time.time() - start
    }
    
    # Guardar resultado parcial en Redis
    redis_client.rpush(
        f"job:{metadata['job_id']}:results",
        json.dumps(result)
    )
    
    # Enviar heartbeat al Agente local via IPC
    send_heartbeat_to_agent()
    
    return result
```

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
```python
import asyncio
import socket
import psutil
import json
import time

class MonitorAgent:
    def __init__(self, worker_id, collector_host, collector_port):
        self.worker_id = worker_id
        self.collector_host = collector_host
        self.collector_port = collector_port
        self.last_heartbeat = time.time()
        self.status = "ALIVE"
        
        # IPC Socket (Unix Domain Socket)
        self.ipc_socket_path = f"/tmp/worker_{worker_id}.sock"
        
    async def listen_ipc_heartbeat(self):
        """Escucha heartbeats del worker via Unix socket."""
        # Crear server Unix socket
        server = await asyncio.start_unix_server(
            self.handle_worker_heartbeat,
            path=self.ipc_socket_path
        )
        async with server:
            await server.serve_forever()
    
    async def handle_worker_heartbeat(self, reader, writer):
        """Recibe heartbeat del worker."""
        data = await reader.read(100)
        message = json.loads(data.decode())
        
        if message['type'] == 'heartbeat':
            self.last_heartbeat = time.time()
            self.status = "ALIVE"
    
    async def collect_metrics(self):
        """Recolecta métricas del sistema."""
        while True:
            # Verificar si worker sigue vivo
            if time.time() - self.last_heartbeat > 15:
                self.status = "DEAD"
            
            metrics = {
                'worker_id': self.worker_id,
                'timestamp': time.time(),
                'status': self.status,
                'cpu_percent': psutil.cpu_percent(interval=1),
                'memory_mb': psutil.virtual_memory().used / (1024**2),
                'memory_percent': psutil.virtual_memory().percent
            }
            
            await self.send_to_collector(metrics)
            await asyncio.sleep(10)  # Reportar cada 10 seg
    
    async def send_to_collector(self, metrics):
        """Envía métricas al Collector via TCP."""
        try:
            reader, writer = await asyncio.open_connection(
                self.collector_host,
                self.collector_port
            )
            
            message = {
                'type': 'metrics',
                'data': metrics
            }
            
            writer.write(json.dumps(message).encode())
            await writer.drain()
            writer.close()
            await writer.wait_closed()
        except Exception as e:
            print(f"Error enviando al collector: {e}")
    
    async def run(self):
        """Inicia el agente."""
        await asyncio.gather(
            self.listen_ipc_heartbeat(),
            self.collect_metrics()
        )

# Inicio
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--worker-id', required=True)
    parser.add_argument('--collector-host', default='collector')
    parser.add_argument('--collector-port', type=int, default=6000)
    args = parser.parse_args()
    
    agent = MonitorAgent(args.worker_id, args.collector_host, args.collector_port)
    asyncio.run(agent.run())
```

**IPC: Heartbeat desde Worker:**
```python
# En genome_worker.py
def send_heartbeat_to_agent():
    """Envía heartbeat al agente local via Unix socket."""
    import socket
    import json
    import os
    
    worker_id = os.environ.get('WORKER_ID', 'worker1')
    sock_path = f"/tmp/worker_{worker_id}.sock"
    
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(sock_path)
        
        message = {'type': 'heartbeat', 'timestamp': time.time()}
        client.send(json.dumps(message).encode())
        client.close()
    except Exception as e:
        # Si el agente no está disponible, el worker continúa procesando
        print(f"Warning: Error enviando heartbeat: {e}")
```

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
   - CPU > 95% por más de 5 minutos → Alerta
   - Status = "DEAD" → Alerta crítica
   - Memory > 90% → Alerta
   - No recibe métricas de un agente por 30 seg → Alerta

3. **Generación de Alertas:**
   - Encolar tarea en Celery: `tasks.send_alert.delay(alert_data)`
   - Loggear en archivo: `/var/log/alerts.log`
   - Notificar al Master via TCP

4. **Persistencia en Redis:**
   - Guardar último estado de cada worker
   - Guardar historial de alertas

**Estructura del Código:**
```python
import asyncio
import json
import redis
from collections import defaultdict
import time

class CollectorServer:
    def __init__(self, port=6000, master_host='master', master_port=5000):
        self.port = port
        self.master_host = master_host
        self.master_port = master_port
        self.redis_client = redis.Redis(host='redis', port=6379, decode_responses=True)
        self.worker_states = defaultdict(dict)  # {worker_id: {last_update, metrics}}
        
    async def handle_agent(self, reader, writer):
        """Recibe métricas de un agente."""
        try:
            data = await reader.read(4096)
            message = json.loads(data.decode())
            
            if message['type'] == 'metrics':
                await self.process_metrics(message['data'])
            
        except Exception as e:
            print(f"Error procesando mensaje: {e}")
        finally:
            writer.close()
            await writer.wait_closed()
    
    async def process_metrics(self, metrics):
        """Procesa métricas recibidas y detecta anomalías."""
        worker_id = metrics['worker_id']
        
        # Actualizar estado en memoria
        self.worker_states[worker_id] = {
            'last_update': time.time(),
            'metrics': metrics
        }
        
        # Guardar en Redis
        self.redis_client.setex(
            f'worker:{worker_id}:metrics',
            60,  # TTL 60 segundos
            json.dumps(metrics)
        )
        
        # Detectar anomalías
        await self.check_anomalies(worker_id, metrics)
    
    async def check_anomalies(self, worker_id, metrics):
        """Detecta si hay anomalías en las métricas."""
        alerts = []
        
        # Worker muerto
        if metrics['status'] == 'DEAD':
            alerts.append({
                'severity': 'CRITICAL',
                'worker_id': worker_id,
                'message': f'Worker {worker_id} ha dejado de responder (DEAD)',
                'timestamp': time.time()
            })
        
        # CPU alta
        if metrics['cpu_percent'] > 95:
            # Verificar si lleva más de 5 min así
            cpu_high_key = f'worker:{worker_id}:cpu_high_since'
            since = self.redis_client.get(cpu_high_key)
            
            if since is None:
                self.redis_client.set(cpu_high_key, time.time())
            elif time.time() - float(since) > 300:  # 5 minutos
                alerts.append({
                    'severity': 'WARNING',
                    'worker_id': worker_id,
                    'message': f'Worker {worker_id} con CPU >95% por más de 5 minutos',
                    'timestamp': time.time()
                })
        else:
            self.redis_client.delete(f'worker:{worker_id}:cpu_high_since')
        
        # Memoria alta
        if metrics['memory_percent'] > 90:
            alerts.append({
                'severity': 'WARNING',
                'worker_id': worker_id,
                'message': f'Worker {worker_id} con Memoria >90%',
                'timestamp': time.time()
            })
        
        # Enviar alertas
        for alert in alerts:
            await self.send_alert(alert)
            await self.notify_master(alert)
    
    async def send_alert(self, alert):
        """Encola alerta en Celery y loggea."""
        # Loggear
        with open('/var/log/alerts.log', 'a') as f:
            f.write(json.dumps(alert) + '\n')
        
        # Encolar en Celery (tarea asíncrona para enviar email, etc.)
        # tasks.send_alert.delay(alert)
        print(f"[ALERT] {alert}")
    
    async def notify_master(self, alert):
        """Notifica al Master sobre worker caído."""
        if alert['severity'] == 'CRITICAL':
            try:
                reader, writer = await asyncio.open_connection(
                    self.master_host,
                    self.master_port
                )
                
                message = {
                    'type': 'worker_down',
                    'worker_id': alert['worker_id'],
                    'timestamp': alert['timestamp']
                }
                
                writer.write(json.dumps(message).encode())
                await writer.drain()
                writer.close()
                await writer.wait_closed()
            except Exception as e:
                print(f"Error notificando al Master: {e}")
    
    async def monitor_timeouts(self):
        """Detecta workers que dejaron de reportar."""
        while True:
            current_time = time.time()
            
            for worker_id, state in list(self.worker_states.items()):
                if current_time - state['last_update'] > 30:
                    alert = {
                        'severity': 'CRITICAL',
                        'worker_id': worker_id,
                        'message': f'Worker {worker_id} no reporta hace más de 30 seg',
                        'timestamp': current_time
                    }
                    await self.send_alert(alert)
                    await self.notify_master(alert)
            
            await asyncio.sleep(10)
    
    async def run(self):
        """Inicia el servidor collector."""
        server = await asyncio.start_server(
            self.handle_agent,
            '0.0.0.0',
            self.port
        )
        
        print(f"Collector escuchando en puerto {self.port}")
        
        async with server:
            await asyncio.gather(
                server.serve_forever(),
                self.monitor_timeouts()
            )

if __name__ == "__main__":
    collector = CollectorServer()
    asyncio.run(collector.run())
```

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
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
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
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
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

1. **T=0-100s:** Sistema procesando normalmente
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

**Nota sobre re-encolado:** Celery maneja automáticamente el re-encolado de tareas cuando un worker muere antes de completarlas (configurado con `ack_late=True` y `reject_on_worker_lost=True`). El Master solo necesita registrar el evento para auditoría.

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

## 7. Stack Tecnológico

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

## 8. Despliegue con Docker

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

```yaml
version: '3.8'

services:
  redis:
    image: redis:7-alpine
    container_name: genome-redis
    ports:
      - "6379:6379"
    volumes:
      - redis-data:/data
    networks:
      - genome-network
    command: redis-server --appendonly yes

  master:
    build:
      context: .
      dockerfile: docker/Dockerfile.master
    container_name: genome-master
    ports:
      - "5000:5000"
    volumes:
      - ./src:/app/src
      - ./logs:/app/logs
    environment:
      - REDIS_HOST=redis
      - REDIS_PORT=6379
      - MASTER_PORT=5000
    depends_on:
      - redis
    networks:
      - genome-network
    command: python src/master_server.py --port 5000

  collector:
    build:
      context: .
      dockerfile: docker/Dockerfile.collector
    container_name: genome-collector
    ports:
      - "6000:6000"
    volumes:
      - ./src:/app/src
      - ./logs:/app/logs
    environment:
      - REDIS_HOST=redis
      - MASTER_HOST=master
      - MASTER_PORT=5000
      - COLLECTOR_PORT=6000
    depends_on:
      - redis
      - master
    networks:
      - genome-network
    command: python src/collector_server.py --port 6000

  worker1:
    build:
      context: .
      dockerfile: docker/Dockerfile.worker
    container_name: genome-worker1
    volumes:
      - ./src:/app/src
      - /tmp/worker1:/tmp  # Para Unix sockets IPC
    environment:
      - WORKER_ID=worker1
      - REDIS_HOST=redis
      - COLLECTOR_HOST=collector
      - COLLECTOR_PORT=6000
    depends_on:
      - redis
      - collector
    networks:
      - genome-network
    command: >
      sh -c "
        python src/monitor_agent.py --worker-id worker1 --collector-host collector &
        sleep 3
        celery -A src.genome_worker worker --loglevel=info --concurrency=4 --hostname=worker1@%h
      "

  worker2:
    build:
      context: .
      dockerfile: docker/Dockerfile.worker
    container_name: genome-worker2
    volumes:
      - ./src:/app/src
      - /tmp/worker2:/tmp
    environment:
      - WORKER_ID=worker2
      - REDIS_HOST=redis
      - COLLECTOR_HOST=collector
      - COLLECTOR_PORT=6000
    depends_on:
      - redis
      - collector
    networks:
      - genome-network
    command: >
      sh -c "
        python src/monitor_agent.py --worker-id worker2 --collector-host collector &
        sleep 3
        celery -A src.genome_worker worker --loglevel=info --concurrency=4 --hostname=worker2@%h
      "

  worker3:
    build:
      context: .
      dockerfile: docker/Dockerfile.worker
    container_name: genome-worker3
    volumes:
      - ./src:/app/src
      - /tmp/worker3:/tmp
    environment:
      - WORKER_ID=worker3
      - REDIS_HOST=redis
      - COLLECTOR_HOST=collector
      - COLLECTOR_PORT=6000
    depends_on:
      - redis
      - collector
    networks:
      - genome-network
    command: >
      sh -c "
        python src/monitor_agent.py --worker-id worker3 --collector-host collector &
        sleep 3
        celery -A src.genome_worker worker --loglevel=info --concurrency=4 --hostname=worker3@%h
      "

networks:
  genome-network:
    driver: bridge

volumes:
  redis-data:
```

### 8.3 Dockerfiles

**docker/Dockerfile.master:**
```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/

EXPOSE 5000

CMD ["python", "src/master_server.py", "--port", "5000"]
```

**docker/Dockerfile.collector:**
```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/

EXPOSE 6000

CMD ["python", "src/collector_server.py", "--port", "6000"]
```

**docker/Dockerfile.worker:**
```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Instalar psutil y otras deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/

# El comando se especifica en docker-compose.yml para iniciar Agente + Worker
```

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

## 9. Estructura del Repositorio

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
│   └── tasks/
│       ├── __init__.py
│       ├── compute.py       # Tareas de cómputo (find_pattern)
│       └── alerts.py        # Tareas de alertas (send_alert)
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

## 10. Casos de Uso y Escenarios

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
# 1. Sistema funcionando normalmente
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

127.0.0.1:6379> LLEN job:550e8400-e29b-41d4-a716-446655440000:results
(integer) 2048
```

---

## 11. Consideraciones de Implementación

### 11.1 Gestión de Chunks con Overlap

**Problema:** Si un patrón de ADN cae justo en la frontera entre dos chunks, puede no detectarse.

**Solución:** Agregar overlap entre chunks.

```python
# En utils/chunker.py
def divide_file_with_overlap(file_path: str, chunk_size: int, overlap: int = 100):
    """
    Divide archivo en chunks con overlap.
    
    Args:
        file_path: Path al archivo
        chunk_size: Tamaño de cada chunk en bytes (ej: 51200 = 50KB)
        overlap: Bytes de overlap entre chunks (ej: 100)
    
    Yields:
        (chunk_id, data, metadata)
    """
    with open(file_path, 'rb') as f:
        chunk_id = 0
        offset = 0
        
        while True:
            # Leer chunk_size bytes
            f.seek(offset)
            data = f.read(chunk_size + overlap)
            
            if not data:
                break
            
            metadata = {
                'chunk_id': chunk_id,
                'offset': offset,
                'size': len(data),
                'has_overlap': chunk_id > 0
            }
            
            yield chunk_id, data, metadata
            
            # Avanzar (chunk_size, no chunk_size + overlap)
            offset += chunk_size
            chunk_id += 1
```

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

```python
# scripts/generate_genome.py
import random
import argparse

def generate_genome(size_mb: int, output_file: str):
    """Genera archivo de genoma sintético."""
    nucleotides = ['A', 'C', 'G', 'T']
    size_bytes = size_mb * 1024 * 1024
    
    with open(output_file, 'w') as f:
        # Escribir en líneas de 60 caracteres (formato FASTA)
        chars_written = 0
        while chars_written < size_bytes:
            line = ''.join(random.choices(nucleotides, k=60))
            f.write(line + '\n')
            chars_written += 61  # 60 chars + newline
    
    print(f"Archivo generado: {output_file} ({size_mb}MB)")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--size', type=int, required=True, help='Tamaño en MB')
    parser.add_argument('--output', required=True, help='Archivo de salida')
    args = parser.parse_args()
    
    generate_genome(args.size, args.output)
```

### 11.4 Algoritmo de Búsqueda de Patrones

**Opciones:**

1. **Regex simple:** `re.finditer(pattern, text)` - O(n*m) peor caso, pero suficiente para el proyecto
2. **KMP:** O(n+m) - Más eficiente, pero más complejo
3. **Boyer-Moore:** O(n/m) caso promedio - El más rápido para patrones largos

**Decisión:** Usar **regex** por simplicidad. Si se necesita optimizar, implementar KMP.

```python
# En genome_worker.py
import re

def find_pattern_regex(text: str, pattern: str) -> list:
    """Busca pattern en text usando regex."""
    return [m.start() for m in re.finditer(pattern, text)]

def find_pattern_kmp(text: str, pattern: str) -> list:
    """Busca pattern usando algoritmo KMP (opcional, para optimización)."""
    # Implementación KMP aquí si se necesita
    pass
```

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
```python
# En genome_worker.py
@app.task(bind=True, ack_late=True, reject_on_worker_lost=True)
def find_pattern(self, chunk_data, pattern, metadata):
    # Si worker muere aquí, Celery re-encola automáticamente
    # No necesitamos lógica manual de re-encolado
    ...
```

**En el Master:**
```python
async def handle_worker_down_alert(message):
    """Maneja alerta de worker caído del Collector."""
    worker_id = message['worker_id']
    
    # Loggear evento
    logger.warning(f"Worker {worker_id} reportado como caído")
    
    # Marcar en Redis
    redis_client.set(f'worker:{worker_id}:status', 'DEAD')
    redis_client.set(f'worker:{worker_id}:down_at', time.time())
    
    # Celery ya re-encoló las tareas pendientes automáticamente
    # No necesitamos intervención manual
```

**Nota para implementación:** El sistema de re-encolado automático de Celery es robusto y bien probado. Para este proyecto académico, aprovechar estas features es más profesional que implementar lógica custom que puede tener bugs.

### 11.6 Logging Estructurado

**Estándar:** Todos los logs en formato JSON para fácil parsing.

```python
# En utils/logger.py
import logging
import json
from datetime import datetime

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_obj = {
            'timestamp': datetime.utcnow().isoformat(),
            'level': record.levelname,
            'component': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName
        }
        if record.exc_info:
            log_obj['exception'] = self.formatException(record.exc_info)
        return json.dumps(log_obj)

def setup_logger(name: str, log_file: str):
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    
    handler = logging.FileHandler(log_file)
    handler.setFormatter(JSONFormatter())
    
    logger.addHandler(handler)
    return logger
```

**Uso:**
```python
# En master_server.py
from utils.logger import setup_logger

logger = setup_logger('master', '/app/logs/master.log')
logger.info('Master server started', extra={'port': 5000})
```

### 11.7 Seguridad y Validación

**Validaciones Necesarias:**

1. **Tamaño de archivo:** Rechazar archivos > 500MB
2. **Patrón:** Solo caracteres A, C, G, T
3. **Rate limiting:** Max 10 jobs por cliente por minuto
4. **Sanitización:** Validar todos los inputs JSON

```python
# En master_server.py
def validate_job(message: dict) -> tuple[bool, str]:
    """Valida un job recibido."""
    # Validar campos requeridos
    required = ['job_id', 'filename', 'pattern', 'file_size']
    for field in required:
        if field not in message:
            return False, f"Missing field: {field}"
    
    # Validar tamaño
    if message['file_size'] > 500 * 1024 * 1024:  # 500MB
        return False, "File too large (max 500MB)"
    
    # Validar patrón
    if not re.match(r'^[ACGT]+, message['pattern']):
        return False, "Pattern must contain only A, C, G, T"
    
    return True, "OK"
```

---

## 12. Guía para Herramientas IA/LLM

### 12.1 Contexto para Generación de Código

Si eres una herramienta de IA generando código para este proyecto, ten en cuenta:

1. **Python 3.11+:** Usa type hints, async/await moderno
2. **No usar frameworks web:** FastAPI/Flask/Django están prohibidos. Usa `asyncio.start_server()` directamente
3. **Unix Domain Sockets para IPC:** Usa `socket.AF_UNIX`, no `multiprocessing.Queue` (Docker no lo soporta bien)
4. **JSON everywhere:** Todos los mensajes entre componentes en JSON
5. **Error handling:** Siempre usa try-except en operaciones de red/IPC
6. **Logging:** Usa el logger JSON definido en `utils/logger.py`
7. **Celery config:** Broker y backend en Redis, no RabbitMQ

### 12.2 Orden de Implementación Sugerido

Para herramientas de desarrollo iterativo (Cursor, Aider, etc.):

**Fase 1: Infraestructura básica (Día 1-2)**
1. Setup de Docker Compose con Redis
2. Implementar `utils/logger.py` y `utils/protocol.py`
3. Script de generación de genoma (`scripts/generate_genome.py`)

**Fase 2: Sistema A - Grid de Cómputo (Día 3-7)**
1. Implementar `genome_worker.py` (tarea básica de búsqueda)
2. Implementar `utils/chunker.py` (división con overlap)
3. Implementar `master_server.py` (servidor asyncio + división + encolado)
4. Implementar `submit_job.py` (cliente CLI)
5. Implementar `query_job.py` (consulta de estado)
6. Testing end-to-end del Sistema A

**Fase 3: Sistema B - Monitoreo (Día 8-12)**
1. Implementar `monitor_agent.py` (IPC + métricas)
2. Modificar `genome_worker.py` para enviar heartbeats
3. Implementar `collector_server.py` (recepción + detección)
4. Implementar comunicación Collector → Master
5. Testing de detección de fallos

**Fase 4: Integración y Polish (Día 13-15)**
1. Integrar todo en Docker Compose
2. Testing de escenarios completos
3. Documentación final
4. Optimizaciones de performance

**Fase 5: Features Extra (Día 16-18)**
1. Re-encolado automático mejorado
2. Dashboard simple (opcional)
3. Métricas adicionales

### 12.3 Comandos de Testing Rápido

```bash
# Test individual de componentes
python -m pytest tests/test_master.py -v
python -m pytest tests/test_worker.py -v
python -m pytest tests/test_agent.py -v

# Test de integración completo
python -m pytest tests/test_integration.py -v

# Test manual con archivo pequeño (10MB)
python scripts/generate_genome.py --size 10 --output data/test_small.txt
python src/submit_job.py --file data/test_small.txt --pattern "AGGTCCAT"

# Monitorear logs en tiempo real de todos los componentes
docker-compose logs -f --tail=100
```

### 12.4 Variables de Entorno Importantes

```bash
# Master
REDIS_HOST=redis
REDIS_PORT=6379
MASTER_PORT=5000
LOG_LEVEL=INFO

# Collector
COLLECTOR_PORT=6000
MASTER_HOST=master
MASTER_PORT=5000
ALERT_THRESHOLD_CPU=95
ALERT_THRESHOLD_MEMORY=90

# Worker
WORKER_ID=worker1  # worker2, worker3, etc.
CELERY_BROKER=redis://redis:6379/0
CELERY_BACKEND=redis://redis:6379/1
COLLECTOR_HOST=collector
COLLECTOR_PORT=6000

# Agente
AGENT_REPORT_INTERVAL=10  # segundos
HEARTBEAT_TIMEOUT=15  # segundos
IPC_SOCKET_PATH=/tmp/worker_{id}.sock
```

### 12.5 Debugging Tips

**Si el Master no recibe trabajos:**
```bash
# Verificar que está escuchando
docker exec genome-master netstat -tlnp | grep 5000

# Probar conexión desde host
telnet localhost 5000

# Ver logs detallados
docker-compose logs master --tail=50
```

**Si los Workers no procesan tareas:**
```bash
# Verificar conexión a Redis
docker exec genome-worker1 redis-cli -h redis ping

# Ver cola de Celery
docker exec genome-redis redis-cli LLEN celery

# Ver workers activos en Celery
docker exec genome-worker1 celery -A src.genome_worker inspect active
```

**Si el Agente no reporta al Collector:**
```bash
# Verificar que el Agente está corriendo
docker exec genome-worker1 ps aux | grep monitor_agent

# Verificar Unix socket
docker exec genome-worker1 ls -la /tmp/*.sock

# Test manual de conexión al Collector
docker exec genome-worker1 python -c "
import socket
s = socket.socket()
s.connect(('collector', 6000))
print('Conectado!')
"
```

---

## 13. Métricas de Performance Esperadas

### 13.1 Benchmarks Objetivo

Con la configuración de 3 workers (4 cores cada uno):

| Métrica | Valor Esperado |
|---------|---------------|
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

```python
# scripts/benchmark.py
import time
import subprocess
import json

def run_benchmark(file_size_mb, pattern, num_workers):
    """Ejecuta benchmark y retorna métricas."""
    
    # Generar archivo
    subprocess.run([
        'python', 'scripts/generate_genome.py',
        '--size', str(file_size_mb),
        '--output', 'data/benchmark.txt'
    ])
    
    # Enviar job y medir tiempo
    start = time.time()
    
    result = subprocess.run([
        'python', 'src/submit_job.py',
        '--file', 'data/benchmark.txt',
        '--pattern', pattern
    ], capture_output=True, text=True)
    
    job_id = json.loads(result.stdout)['job_id']
    
    # Esperar a que termine
    while True:
        result = subprocess.run([
            'python', 'src/query_job.py',
            '--job-id', job_id
        ], capture_output=True, text=True)
        
        status = json.loads(result.stdout)
        if status['status'] == 'COMPLETED':
            break
        
        time.sleep(5)
    
    end = time.time()
    
    return {
        'file_size_mb': file_size_mb,
        'processing_time': end - start,
        'throughput_mbps': file_size_mb / (end - start),
        'workers': num_workers
    }
```

---

## 14. Extensiones Futuras (TODO.md)

### 14.1 Features Nice-to-Have

1. **Dashboard Web (opcional):**
   - Visualización en tiempo real de workers y métricas
   - Gráficos de CPU/RAM con Chart.js
   - Ver jobs en progreso
   - **Tech:** Flask simple + WebSockets (pero solo para dashboard, no para core)

2. **Re-encolado Inteligente:**
   - Cuando un worker cae, detectar qué chunks estaba procesando
   - Re-asignar a workers con menos carga
   - Priorizar chunks cercanos a completar el job

3. **Compresión de Chunks:**
   - Comprimir chunks antes de enviar a Redis
   - Reducir uso de memoria de Redis
   - Usar `gzip` o `lz4`

4. **Persistencia de Jobs:**
   - Guardar estado de jobs en disco (SQLite o archivos JSON)
   - Permitir reanudar jobs si el Master se reinicia

5. **Autoscaling de Workers:**
   - Detectar cuando hay muchos jobs encolados
   - Lanzar más contenedores de workers automáticamente
   - Usar Docker API o Kubernetes

6. **Múltiples Patrones:**
   - Buscar varios patrones en una sola pasada
   - Optimización: compilar todos los patrones en un solo regex

7. **Soporte para FASTA:**
   - Parsear formato FASTA real (con headers)
   - Ignorar líneas de comentarios
   - Procesar múltiples secuencias en un archivo

### 14.2 Optimizaciones de Performance

1. **Usar Boyer-Moore en lugar de regex**
2. **Pipeline de chunks:** Mientras se procesan chunks, ir enviando los siguientes
3. **Caché de resultados:** Si se busca el mismo patrón dos veces, retornar del cache
4. **Paralelización intra-chunk:** Dividir chunks grandes en sub-chunks

### 14.3 Mejoras de Monitoreo

1. **Métricas de red:** Latencia, throughput, paquetes perdidos
2. **Métricas de disco:** I/O, espacio disponible
3. **Historial de métricas:** Guardar en TimeSeries DB (InfluxDB, Prometheus)
4. **Alertas avanzadas:** Machine learning para detectar anomalías
5. **Notificaciones:** Email, Slack, Telegram cuando hay alertas

---

## 15. Troubleshooting

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
```python
# Verificar imports en genome_worker.py
from celery import Celery

# Asegurarse de que el app de Celery tiene el nombre correcto
app = Celery('genome_tasks', broker='redis://redis:6379/0')

# Y que la tarea está decorada correctamente
@app.task(bind=True)
def find_pattern(self, chunk_data, pattern, metadata):
    ...
```

---

**Problema:** Master no puede dividir archivo grande
```
Error: MemoryError: Unable to allocate array
```
**Solución:**
```python
# No cargar todo el archivo en memoria
# Usar streaming en chunker.py:
def divide_file_streaming(file_path, chunk_size):
    with open(file_path, 'rb') as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            yield chunk
```

---

**Problema:** Collector recibe métricas duplicadas
```
Warning: Received metrics from worker_1 twice in 1 second
```
**Solución:**
```python
# En monitor_agent.py, usar un lock para evitar envíos concurrentes:
self.send_lock = asyncio.Lock()

async def send_to_collector(self, metrics):
    async with self.send_lock:
        # Enviar métricas
        ...
```

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

## 16. Criterios de Evaluación (Para Profesores)

### 16.1 Rubrica Esperada

| Categoría | Peso | Criterios |
|-----------|------|-----------|
| **Funcionalidad** | 40% | Sistema completa el análisis genómico correctamente. Workers procesan en paralelo. Resultados son correctos. |
| **Arquitectura** | 25% | Uso correcto de sockets, asyncio, Celery, IPC. Separación clara de responsabilidades. Diseño modular. |
| **Monitoreo** | 15% | Detección de fallos funciona. Métricas se reportan correctamente. Alertas se generan apropiadamente. |
| **Documentación** | 10% | README completo. Código comentado. Justificación de decisiones técnicas. |
| **Docker** | 5% | Sistema se levanta con `docker-compose up`. Configuración correcta de contenedores. |
| **Extras** | 5% | Re-encolado, base de datos, dashboard, optimizaciones. |

### 16.2 Demostración Sugerida para el Final

**Guión de Demo (15 minutos):**

1. **Intro (2 min):** Explicar arquitectura con diagrama
2. **Caso Normal (5 min):** 
   - Levantar sistema
   - Enviar job de 200MB
   - Mostrar workers procesando
   - Mostrar métricas en Redis
   - Mostrar resultado final
3. **Caso de Fallo (5 min):**
   - Durante procesamiento, matar un worker
   - Mostrar detección en Collector
   - Mostrar alerta en logs
   - Mostrar que el job se completa igual
4. **Arquitectura Técnica (3 min):**
   - Explicar uso de sockets (mostrar código)
   - Explicar asyncio (mostrar código)
   - Explicar IPC (mostrar Unix socket)
   - Explicar Celery (mostrar cola de Redis)

---

## 17. Contacto y Contribuciones

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
KEYS celery-task-meta-*  # Resultados de tareas

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
