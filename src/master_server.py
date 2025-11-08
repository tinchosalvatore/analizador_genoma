import os
import asyncio
import json
import base64
import time
from typing import Dict, Any

import redis.asyncio as aioredis # Usar la versión async de Redis
from celery import Celery

from src.config.settings import MASTER_PORT, REDIS_HOST, REDIS_PORT, CELERY_BROKER, CELERY_BACKEND
from src.utils.logger import setup_logger
from src.utils.protocol import validate_message
from src.utils.chunker import divide_data_with_overlap # Importar la función que divide el archivo completo
from src.genome_worker import find_pattern


# Configurar el logger para el master
logger = setup_logger('master_server', f'{os.getenv('LOG_DIR', '/app/logs')}/master_server.log')

# Configuración de Celery para el Master (solo para encolar tareas)
celery_app = Celery('master_tasks', broker=CELERY_BROKER, backend=CELERY_BACKEND)

# Cliente Redis asíncrono (inicializado en None)
redis_client: aioredis.Redis | None = None

# Obtiene o inicializa el cliente Redis asíncrono
async def get_redis_client() -> aioredis.Redis:
    global redis_client
    if redis_client is None:
        try:
            redis_client = aioredis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
            await redis_client.ping() # Verificar conexión
            logger.info("Cliente Redis asíncrono inicializado para el Master.", extra={'redis_host': REDIS_HOST, 'redis_port': REDIS_PORT})
        except Exception as e:
            logger.error(f"Error al inicializar el cliente Redis asíncrono para el Master: {e}")
            raise
    return redis_client

class MasterServer:
# constructor principal, para levantar el servidor
    def __init__(self, host: str = '0.0.0.0', port: int = MASTER_PORT):
        self.host = host
        self.port = port
        self.redis_client: aioredis.Redis | None = None
        logger.info(f"MasterServer inicializado en {self.host}:{self.port}")


        # Maneja las conexiones entrantes de los clientes de manera asincrona
    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        addr = writer.get_extra_info('peername')
        logger.info(f"Conexión aceptada de {addr}")

        try:
            # Leemos el archivo de entrada del cliente y lo decodificamos
            data = await reader.read(1024 * 1024 * 300) # Leer hasta 300MB (para el archivo base64 de 200MB)
            message_str = data.decode('utf-8')
            message = json.loads(message_str)

            msg_type = message.get('type')
            # validamos el mensaje haciendo uso de nuestros protocolos
            is_valid, error_msg = validate_message(message, msg_type)

            if not is_valid:
                logger.warning(f"Mensaje inválido de {addr}: {error_msg}", extra={'message': message})
                response = {"status": "error", "message": error_msg}
            
            # si el mensaje es valido, puede ser cualquiera de estos casos, voy a tener un handler para cada uno
            elif msg_type == 'submit_job':
                response = await self._handle_submit_job(message)
            elif msg_type == 'query_status':
                response = await self._handle_query_status(message)
            elif msg_type == 'worker_down':
                response = await self._handle_worker_down(message)
            
            # error desconocido
            else:
                logger.warning(f"Tipo de mensaje desconocido de {addr}: {msg_type}", extra={'message': message})
                response = {"status": "error", "message": f"Tipo de mensaje desconocido: {msg_type}"}

            writer.write(json.dumps(response).encode('utf-8'))   # envia la rta correspondiente en formato JSON
            await writer.drain()   # Envia la respuesta al cliente 


        # manejo de errores posibles
        except json.JSONDecodeError:
            logger.error(f"Error de decodificación JSON de {addr}", exc_info=True)
            response = {"status": "error", "message": "Formato JSON inválido."}
            writer.write(json.dumps(response).encode('utf-8'))
            await writer.drain()
        except Exception as e:
            logger.error(f"Error manejando cliente {addr}: {e}", exc_info=True)
            response = {"status": "error", "message": f"Error interno del servidor: {e}"}
            writer.write(json.dumps(response).encode('utf-8'))
            await writer.drain()

        # cierra la conexion con el cliente
        finally:
            logger.info(f"Cerrando conexión con {addr}")
            writer.close()
            await writer.wait_closed()


# <=========== HANDLERS ===========>


    #Procesa una peticion de trabajo de análisis genómico por parte del cliente
    async def _handle_submit_job(self, message: Dict[str, Any]) -> Dict[str, Any]:
        job_id = message['job_id']
        filename = message['filename']
        pattern = message['pattern']
        chunk_size = message.get('chunk_size', 51200) # Default 50KB
        file_size = message['file_size']
        file_data_b64 = message['file_data_b64']

        logger.info(f"Job {job_id} recibido: {filename}, patrón: {pattern}", extra={'job_id': job_id, 'filename': filename, 'pattern': pattern, 'file_size': file_size})

        try:
            file_data = base64.b64decode(file_data_b64)
            
            # Usar la nueva función divide_data_with_overlap
            chunks_generator = divide_data_with_overlap(file_data, chunk_size=chunk_size)
            
            total_chunks = 0
            task_ids = []

            # Guardar estado inicial del job en Redis
            await self.redis.hset(f"job:{job_id}", mapping={
                "status": "processing",
                "filename": filename,
                "pattern": pattern,
                "total_chunks": 0, # Se actualizará
                "processed_chunks": 0,
                "start_time": time.time(),
                "file_size": file_size,
                "chunk_size": chunk_size
            })

            await self.redis.expire(f"job:{job_id}", 3600 * 24)   # La tarea se elimina de Redis en 24 horas

            for chunk_id, chunk_data, metadata in chunks_generator:
                # Codificar el chunk de nuevo a base64 para reencolar las tareas
                chunk_data_b64_for_celery = base64.b64encode(chunk_data).decode('utf-8')
                
                # Encolamos la tarea con Celery, usando de broker a Redis, para que consuman los workers las tareas de ahi
                
                # Usamos la tarea directamente de genome worker para evitar problemas de serialización  (find_pattern es del worker)
                task = find_pattern.delay(chunk_data_b64_for_celery, pattern, metadata) # usamos delay para encolar la tarea
                task_ids.append(task.id)
                total_chunks += 1
                logger.debug(f"Chunk {chunk_id} encolado para job {job_id}", extra={'job_id': job_id, 'chunk_id': chunk_id, 'task_id': task.id})

            # Actualizar el número total de chunks en Redis
            await self.redis.hset(f"job:{job_id}", "total_chunks", total_chunks)
            
            # Guardar la lista de IDs de tareas en Redis mas su tiempo de expiración
            if task_ids:
                await self.redis.rpush(f"job:{job_id}:task_ids", *task_ids)
                await self.redis.expire(f"job:{job_id}:task_ids", 3600 * 24) # Expira en 24 horas

            # Estimación de tiempo de ejecucion, basada en promedio de ejecucion de cada chunk
            estimated_time = (total_chunks * 0.03) if total_chunks > 0 else 0 # 0.03s por chunk

            logger.info(f"Job {job_id} aceptado. Total chunks: {total_chunks}", extra={'job_id': job_id, 'total_chunks': total_chunks})
            return {   # return de que el trabajo de subio correctamente
                "status": "accepted",
                "job_id": job_id,
                "total_chunks": total_chunks,
                "estimated_time": round(estimated_time, 2)
            }
        except Exception as e:
            logger.error(f"Error procesando submit_job para {job_id}: {e}", exc_info=True, extra={'job_id': job_id})
            # Limpiar Redis si hubo un error
            await self.redis.delete(f"job:{job_id}", f"job:{job_id}:task_ids", f"job:{job_id}:results")
            return {"status": "error", "message": f"Fallo al procesar el trabajo: {e}"}

# consultas sobre el estado de la tarea por parte del cliente
    async def _handle_query_status(self, message: Dict[str, Any]) -> Dict[str, Any]:
        job_id = message['job_id']
        logger.info(f"Consulta de estado para job {job_id}", extra={'job_id': job_id})

        job_info = await self.redis.hgetall(f"job:{job_id}")
        if not job_info:
            return {"status": "error", "message": "Job ID no encontrado."}

        current_status = job_info.get("status", "unknown")
        total_chunks = int(job_info.get("total_chunks", 0))
        
        # Contar resultados parciales ya guardados
        processed_chunks = await self.redis.llen(f"job:{job_id}:results")
        
        percentage = (processed_chunks / total_chunks * 100) if total_chunks > 0 else 0

        # Calcular resultados parciales (conteo de matches)
        total_matches = 0
        # Esto podría ser costoso para muchos resultados, se podría optimizar guardando un contador en Redis
        # Por ahora, leemos todos los resultados y los sumamos
        raw_results = await self.redis.lrange(f"job:{job_id}:results", 0, -1)
        for res_str in raw_results:
            try:
                res = json.loads(res_str)
                total_matches += res.get('matches', 0)
            except json.JSONDecodeError:
                logger.warning(f"Resultado parcial corrupto para job {job_id}", extra={'job_id': job_id, 'raw_result': res_str})

        # Si todos los chunks han sido procesados y el estado no es "completed", actualizarlo
        if processed_chunks >= total_chunks and total_chunks > 0 and current_status == "processing":
            current_status = "completed"
            await self.redis.hset(f"job:{job_id}", "status", "completed")
            logger.info(f"Job {job_id} marcado como completado.", extra={'job_id': job_id})

        return {
            "status": current_status,
            "job_id": job_id,
            "progress": {
                "total_chunks": total_chunks,
                "processed_chunks": processed_chunks,
                "percentage": round(percentage, 2)
            },
            "partial_results": {
                "matches_found": total_matches
            }
        }

    async def _handle_worker_down(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Maneja la notificación de un worker caído del Collector."""
        worker_id = message['worker_id']
        timestamp = message['timestamp']
        
        logger.warning(f"Notificación de worker caído recibida: {worker_id} a las {timestamp}", extra={'worker_id': worker_id, 'timestamp': timestamp})
        
        # Aquí el Master podría implementar lógica adicional si Celery no re-encolara automáticamente
        # Por ahora, solo loggeamos y actualizamos el estado del worker en Redis si lo tuviéramos
        # (El Collector ya se encarga de marcarlo como DEAD en su propia lógica)
        
        # Opcional: Marcar el worker como caído en Redis para que el Master lo sepa
        await self.redis.hset(f"worker_status:{worker_id}", "status", "DEAD")
        await self.redis.hset(f"worker_status:{worker_id}", "last_down_timestamp", timestamp)
        
        return {"status": "acknowledged", "message": f"Alerta de worker {worker_id} recibida."}

    async def run(self):
        """Inicia el servidor Master."""
        self.redis = await get_redis_client()
        server = await asyncio.start_server(self.handle_client, self.host, self.port)
        addr = server.sockets[0].getsockname()
        logger.info(f"MasterServer escuchando en {addr}")

        async with server:
            await server.serve_forever()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Master Server for Genome Analysis.")
    parser.add_argument('--port', type=int, default=MASTER_PORT, help='Port to listen on.')
    args = parser.parse_args()

    master_server = MasterServer(port=args.port)
    try:
        asyncio.run(master_server.run())
    except KeyboardInterrupt:
        logger.info("MasterServer detenido por el usuario.")
    except Exception as e:
        logger.critical(f"MasterServer ha terminado con un error crítico: {e}", exc_info=True)
