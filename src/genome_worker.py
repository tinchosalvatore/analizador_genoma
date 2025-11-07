from celery import Celery
import os
import json
import time
import re
import socket
import base64
from typing import Dict, Any

# Importar configuración y logger
from src.config.settings import REDIS_HOST, REDIS_PORT, WORKER_ID, IPC_SOCKET_PATH
from src.utils.logger import setup_logger

# Configurar el logger para el worker
logger = setup_logger(f'genome_worker_{WORKER_ID}', f'{os.getenv('LOG_DIR', '/app/logs')}/genome_worker_{WORKER_ID}.log')

# Configuración de Celery
# Usamos el broker y backend de Redis definidos en settings.py
app = Celery('genome_tasks',
             broker=f'redis://{REDIS_HOST}:{REDIS_PORT}/0',
             backend=f'redis://{REDIS_HOST}:{REDIS_PORT}/1')

app.conf.update(
    task_acks_late=True,              # CRÍTICO para re-encolado
    task_reject_on_worker_lost=True,  # CRÍTICO para re-encolado
    worker_prefetch_multiplier=2,
    worker_max_tasks_per_child=100
)

# Cliente Redis para guardar resultados parciales
# Se inicializa aquí para que cada proceso worker tenga su propia conexión
redis_client = None

def get_redis_client():
    """Obtiene o inicializa el cliente Redis."""
    global redis_client
    if redis_client is None:
        try:
            # Celery ya establece una conexión a Redis para el backend, la reutilizamos.
            # Esto es más robusto que crear una nueva conexión redis.Redis() en cada proceso.
            redis_client = app.backend.client
            logger.info("Cliente Redis inicializado para el worker.", extra={'redis_host': REDIS_HOST, 'redis_port': REDIS_PORT})
        except Exception as e:
            logger.error(f"Error al inicializar el cliente Redis para el worker: {e}")
            raise
    return redis_client

def send_heartbeat_to_agent(tasks_completed: int = 0):
    """
    Envía un heartbeat al agente local via Unix socket.
    El WORKER_ID se obtiene de las variables de entorno.
    """
    sock_path = IPC_SOCKET_PATH.format(worker_id=WORKER_ID) # Usar el path del settings
    
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
        pass  # El worker debe continuar procesando aunque el agente no esté disponible

@app.task(bind=True, ack_late=True, reject_on_worker_lost=True)
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
            'matches': int,
            'positions': [list of positions],  # Posiciones absolutas en el archivo original
            'processing_time': float
        }
    """
    start_time = time.time()
    job_id = metadata.get('job_id', 'unknown_job')
    chunk_id = metadata.get('chunk_id', -1)
    offset = metadata.get('offset', 0)

    logger.info(f"Iniciando procesamiento de chunk {chunk_id} para job {job_id}", extra={'job_id': job_id, 'chunk_id': chunk_id, 'offset': offset})

    try:
        # Decodificar chunk de base64
        chunk_data = base64.b64decode(chunk_data_b64)
        text = chunk_data.decode('utf-8')
        
        # Buscar patrón (usando regex simple)
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
        else:
            logger.error(f"No se pudo guardar el resultado parcial para job {job_id}, chunk {chunk_id}. Cliente Redis no disponible.")

        # Enviar heartbeat al Agente local via IPC
        send_heartbeat_to_agent(tasks_completed=1) # Reportar 1 tarea completada
        
        return result

    except Exception as e:
        logger.error(f"Error procesando chunk {chunk_id} para job {job_id}: {e}", extra={'job_id': job_id, 'chunk_id': chunk_id, 'error': str(e)}, exc_info=True)
        # Re-lanzar la excepción para que Celery la marque como fallida
        raise
