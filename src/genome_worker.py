from celery import Celery
import os
import json
import time
import re
import socket
import base64
from typing import Dict, Any

# los usamos para arreglar el tema de los heartbeats
import threading
from celery.signals import worker_process_init


# Importar configs y el logger
from src.config.settings import REDIS_HOST, REDIS_PORT, WORKER_ID, IPC_SOCKET_PATH
from src.utils.logger import setup_logger

# Variable global para control de heartbeats
_last_heartbeat_time = 0

# Configurar el logger para el worker
logger = setup_logger(f'genome_worker_{WORKER_ID}', f'{os.getenv("LOG_DIR", "/app/logs")}/genome_worker_{WORKER_ID}.log')

# Configuración de Celery
# Usamos el broker y backend de Redis definidos en settings.py
app = Celery('genome_tasks',
             # el /0 y /1 hacen que sean distintas bases de datos logicas, dentro de la misma instancia de Redis
             broker=f'redis://{REDIS_HOST}:{REDIS_PORT}/0',   # el broker va a funcionar como cola de tareas para los workers
             backend=f'redis://{REDIS_HOST}:{REDIS_PORT}/1')   # aca se van a almacenar los resultados de las tareas
                                                                

app.conf.update(
    task_acks_late=True,              # CRÍTICO para re-encolado de tareas cuando un worker cae
    task_reject_on_worker_lost=True,  # CRÍTICO para re-encolado de tareas cuando un worker cae
    worker_prefetch_multiplier=2,
    worker_max_tasks_per_child=100
)

# Se inicializa vacio para que cada proceso worker tenga su propia conexión
redis_client = None

    # Obtiene o inicializa el cliente Redis. Esta funcion la va a ejecutar cada proceso worker
def get_redis_client():
    global redis_client
    if redis_client is None:   # si no hay una conexión establecida con Redis
        try:
            # Reutilizamos la conexión a Redis para el backend, que establecimos antes
            # Esto es más robusto que crear una nueva conexión redis.Redis() en cada proceso.
            redis_client = app.backend.client
            logger.info("Cliente Redis inicializado para el worker.", extra={'redis_host': REDIS_HOST, 'redis_port': REDIS_PORT})
        except Exception as e:
            logger.error(f"Error al inicializar el cliente Redis para el worker: {e}")
            raise
    return redis_client


# Variable global para trackear último heartbeat
_last_heartbeat_time = 0

def send_heartbeat_to_agent(tasks_completed: int = 0):
    """
    Envía un heartbeat al agente local via Unix socket.
    Limitado a 1 heartbeat cada 5 segundos para evitar sobrecarga.
    """
    global _last_heartbeat_time
    
    # Limitar frecuencia: solo enviar cada 5 segundos
    current_time = time.time()
    if current_time - _last_heartbeat_time < 5:
        return  # Skip este heartbeat
    
    _last_heartbeat_time = current_time
    
    sock_path = IPC_SOCKET_PATH.format(worker_id=WORKER_ID)
    
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(sock_path)
        
        message = {
            'type': 'heartbeat',
            'timestamp': time.time(),
            'tasks_completed': tasks_completed
        }
        client.send(json.dumps(message).encode('utf-8'))
        client.close()
        logger.debug(f"Heartbeat enviado al agente en {sock_path}", extra={'worker_id': WORKER_ID, 'tasks_completed': tasks_completed})
    except FileNotFoundError:
        logger.warning(f"Socket de agente no encontrado en {sock_path}. El agente podría no estar corriendo aún.", extra={'worker_id': WORKER_ID})
    except ConnectionRefusedError:
        logger.warning(f"Conexión al socket del agente rechazada en {sock_path}. El agente podría no estar listo.", extra={'worker_id': WORKER_ID})
    except Exception as e:
        logger.error(f"Error enviando heartbeat al agente en {sock_path}: {e}", extra={'worker_id': WORKER_ID, 'error': str(e)})
        pass


# para que el heartbeat se mande todo el tiempo, inclusive cuando no se ejcuta una tarea, usamos hilos
def _heartbeat_thread():
    """
    Un hilo que corre en segundo plano y envía un heartbeat cada 5 segundos.
    Esto mantiene al monitor_agent informado de que el proceso worker está vivo,
    incluso si está ocioso.
    """
    while True:
        try:
            # Enviamos un heartbeat con 0 tareas completadas (solo es liveness)
            # La función 'send_heartbeat_to_agent' ya tiene un rate-limit
            # interno de 5s, pero dormir aquí es más limpio.
            send_heartbeat_to_agent(0)
        except Exception as e:
            # Loggear, pero nunca dejar que el hilo muera
            logger.error(f"Error en el hilo de heartbeat: {e}")
        
        # Esperar 5 segundos para el próximo latido
        time.sleep(5)

# esta es la señal que se dispara cuando se inicia un proceso worker, mandando con hilos los heartbeats constantemente
@worker_process_init.connect
def on_worker_process_init(**kwargs):
    """
    Se ejecuta una vez por cada proceso worker de Celery que se inicia.
    Aquí es donde lanzamos nuestro hilo de heartbeat.
    """
    logger.info("Proceso worker inicializado. Iniciando hilo de heartbeat...")
    
    # Iniciar el hilo como 'daemon' para que muera automáticamente
    # cuando el proceso principal del worker muera.
    t = threading.Thread(target=_heartbeat_thread, daemon=True)
    t.start()

# creamos una tarea de Celery   (@app = Celery())
@app.task(bind=True, ack_late=True, reject_on_worker_lost=True)   # mismos parametros que antes, que ayudan a la reencolación de la tarea
def find_pattern(self, chunk_data_b64: str, pattern: str, metadata: Dict[str, Any]):
    """
    Busca todas las ocurrencias de 'pattern' en 'chunk_data'.
    
    Args:
        chunk_data_b64: Bytes del chunk codificados en base64 a procesar.
        pattern: Patrón de ADN a buscar (ej: "AGGTCCAT").
        metadata: {'job_id': str, 'chunk_id': int, 'offset': int, 'size': int}.
    
    Returns:
        {
            'chunk_id': int,
            'matches': int,      # cantidad de veces que se encontro el patrón
            'positions': [list of positions],  # Posiciones absolutas en el archivo original COMPLETO
            'processing_time': float
        }
    """
    start_time = time.time()   # para luego restarle el tiempo cuando termine
    job_id = metadata.get('job_id', 'unknown_job')
    chunk_id = metadata.get('chunk_id', -1)
    offset = metadata.get('offset', 0)   # Posicion absoluta en el archivo original

    logger.info(f"Iniciando procesamiento de chunk {chunk_id} para job {job_id}", extra={'job_id': job_id, 'chunk_id': chunk_id, 'offset': offset})

    try:
        # Decodificar chunk de base64 a bytes a string
        chunk_data = base64.b64decode(chunk_data_b64)
        text = chunk_data.decode('utf-8')   
        
        # Busca el patrón (usando regex simple)
        matches = list(re.finditer(pattern, text))
        
        result = {
            'chunk_id': chunk_id,
            'matches': len(matches),
            'positions': [m.start() + offset for m in matches], # Posiciones absolutas en el archivo original
            'processing_time': time.time() - start_time,
            'worker_id': WORKER_ID
        }
        
        # Guardar resultado parcial en Redis
        r_client = get_redis_client()
        if r_client:
            r_client.rpush(
                f"job:{job_id}:results",
                json.dumps(result)
            )
            logger.info(f"Resultado parcial guardado para job {job_id}, chunk {chunk_id}", extra={'job_id': job_id, 'chunk_id': chunk_id, 'matches': len(matches)})
            # Incrementar contador atómico de chunks procesados
            r_client.hincrby(f"job:{job_id}", "processed_chunks", 1)
            # Incrementar contador atómico de matches encontrados
            r_client.hincrby(f"job:{job_id}", "total_matches", len(matches))
        else:
            logger.error(f"No se pudo guardar el resultado parcial para job {job_id}, chunk {chunk_id}. Cliente Redis no disponible.")

        # Enviar heartbeat al Agent local via Unix socket
        send_heartbeat_to_agent(tasks_completed=1) # Reportar 1 tarea completada
        
        return result

    # Excepciones generales.
    except Exception as e:
        logger.error(f"Error procesando chunk {chunk_id} para job {job_id}: {e}", extra={'job_id': job_id, 'chunk_id': chunk_id, 'error': str(e)}, exc_info=True)
        # Re-lanzar la excepción para que Celery la marque como fallida
        raise