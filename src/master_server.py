import argparse
import os
import asyncio
import json
import base64
import time
import re
import struct
from typing import Dict, Any

import redis.asyncio as aioredis # Usar la versión async de Redis
from celery import Celery

from src.config.settings import MASTER_PORT, REDIS_HOST, REDIS_PORT, CELERY_BROKER, CELERY_BACKEND
from src.utils.logger import setup_logger
from src.utils.protocol import validate_message
from src.utils.chunker import divide_file_with_overlap # Importar la función que divide desde un archivo



# Configurar el logger para el master
logger = setup_logger('master_server', f"{os.getenv('LOG_DIR', 'logs')}/master_server.log")

# Configuración de Celery para el Master (solo para encolar tareas)
celery_app = Celery('master_tasks', broker=CELERY_BROKER, backend=CELERY_BACKEND)

# Cliente Redis asíncrono (inicializado en None)
redis_client: aioredis.Redis | None = None

# Obtiene o inicializa el cliente Redis asíncrono
async def get_redis_client() -> aioredis.Redis:
    global redis_client
    if redis_client is None:
        try:
            redis_client = aioredis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=1, decode_responses=True)
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


    import struct

# ... (el resto de las importaciones) ...

# ... (código anterior) ...

    # Maneja las conexiones entrantes de los clientes de manera asincrona
    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        addr = writer.get_extra_info('peername')
        logger.info(f"Conexión aceptada de {addr}")
        response = None
        try:
            # 1. Leer el encabezado de 4 bytes para obtener la longitud del mensaje
            header_data = await reader.readexactly(4)
            if not header_data:
                logger.warning(f"Cliente {addr} cerró la conexión prematuramente (sin encabezado).")
                return

            message_length = struct.unpack('!I', header_data)[0]

            # 2. Leer exactamente la cantidad de bytes especificada en el encabezado
            data = await reader.readexactly(message_length)
            if not data:
                logger.warning(f"Cliente {addr} cerró la conexión prematuramente (sin datos después del encabezado).")
                return

            message_str = data.decode('utf-8')
            message = json.loads(message_str)

            msg_type = message.get('type')
            is_valid, error_msg = validate_message(message, msg_type)

            if not is_valid:
                logger.warning(f"Mensaje inválido de {addr}: {error_msg}", extra={'full_message': message})
                response = {"status": "error", "message": error_msg}
            elif msg_type == 'submit_job':
                response = await self._handle_submit_job(message)
            elif msg_type == 'query_status':
                response = await self._handle_query_status(message)
            elif msg_type == 'worker_down':
                response = await self._handle_worker_down(message)
            else:
                logger.warning(f"Tipo de mensaje desconocido de {addr}: {msg_type}", extra={'full_message': message})
                response = {"status": "error", "message": f"Tipo de mensaje desconocido: {msg_type}"}

        except asyncio.IncompleteReadError:
            logger.warning(f"Cliente {addr} cerró la conexión inesperadamente mientras se leía el mensaje.")
            return # No se puede enviar respuesta si la conexión está rota
        except json.JSONDecodeError:
            logger.error(f"Error de decodificación JSON de {addr}", exc_info=True)
            response = {"status": "error", "message": "Formato JSON inválido."}
        except Exception as e:
            logger.error(f"Error manejando cliente {addr}: {e}", exc_info=True)
            response = {"status": "error", "message": f"Error interno del servidor: {e}"}
        finally:
            if response:
                # Implementar protocolo de respuesta simétrico: [header de 4 bytes] + [payload]
                response_data = json.dumps(response).encode('utf-8')
                header = struct.pack('!I', len(response_data))
                
                writer.write(header)
                writer.write(response_data)
                await writer.drain()
            
            logger.info(f"Cerrando conexión con {addr}")
            writer.close()
            await writer.wait_closed()

# ... (resto del código) ...



# <=========== HANDLERS ===========>


    #Procesa una peticion de trabajo de análisis genómico por parte del cliente
    async def _handle_submit_job(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """
        Maneja la petición inicial de 'submit_job'.
        Valida, crea un estado inicial en Redis y responde inmediatamente.
        El trabajo pesado se delega a una tarea en segundo plano.
        """
        job_id = message['job_id']
        file_path_relative = message['file_path']
        pattern = message['pattern']

        logger.info(f"Petición de job {job_id} recibida para archivo: {file_path_relative}", extra={'job_id': job_id})

        # --- Validaciones rápidas ---
        file_path_in_container = f"/app/{file_path_relative}"
        if not os.path.exists(file_path_in_container):
            logger.error(f"Archivo no encontrado para job {job_id}: {file_path_in_container}", extra={'job_id': job_id})
            return {"status": "error", "message": f"Archivo no encontrado en el servidor: {file_path_relative}"}

        if not re.match(r'^[ACGT]+$', pattern) or not (2 <= len(pattern) <= 100):
            logger.error(f"Patrón inválido para job {job_id}: {pattern}", extra={'job_id': job_id})
            return {"status": "error", "message": "Patrón inválido. Debe contener solo A,C,G,T y tener entre 2 y 100 caracteres."}

        # --- Creación del estado inicial en Redis ---
        try:
            file_size = os.path.getsize(file_path_in_container)
            await self.redis.hset(f"job:{job_id}", mapping={
                "status": "queuing",  # Nuevo estado: "encolando"
                "filename": file_path_relative,
                "pattern": pattern,
                "total_chunks": 0,
                "processed_chunks": 0,
                "total_matches": 0,
                "start_time": time.time(),
                "file_size": file_size,
            })
            await self.redis.expire(f"job:{job_id}", 3600 * 24)
        except Exception as e:
            logger.error(f"Error al crear estado inicial en Redis para job {job_id}: {e}", exc_info=True)
            return {"status": "error", "message": "Error interno al inicializar el job."}

        # --- Lanzar tarea de fondo y responder ---
        logger.info(f"Job {job_id} validado. Encolando chunks en segundo plano.", extra={'job_id': job_id})
        asyncio.create_task(self._process_and_enqueue_job(job_id, file_path_in_container, pattern))

        return {
            "status": "accepted",
            "job_id": job_id,
            "message": "Job aceptado y está siendo preparado para procesamiento."
        }

    async def _process_and_enqueue_job(self, job_id: str, file_path: str, pattern: str, chunk_size: int = 51200):
        """
        Ejecuta el trabajo pesado (lectura de archivo, encolado) en un
        hilo separado para no bloquear el bucle de eventos de asyncio.
        """
        loop = asyncio.get_running_loop()
        
        def blocking_code():
            """
            Esta función contiene todo el código bloqueante.
            Se ejecutará en un hilo del executor.
            """
            # Necesitamos un cliente de Redis síncrono aquí, ya que aioredis no es thread-safe.
            import redis
            sync_redis = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=1, decode_responses=True)
            
            try:
                logger.info(f"Iniciando procesamiento de archivo para job {job_id} en hilo separado.", extra={'job_id': job_id})
                sync_redis.hset(f"job:{job_id}", "status", "processing")

                chunks_generator = divide_file_with_overlap(file_path, chunk_size=chunk_size)
                
                total_chunks = 0
                task_ids = []
                for chunk_id, chunk_data, metadata in chunks_generator:
                    metadata['job_id'] = job_id
                    chunk_data_b64 = base64.b64encode(chunk_data).decode('utf-8')
                    
                    # send_task es bloqueante, por eso está aquí.
                    task = celery_app.send_task(
                        'src.genome_worker.find_pattern',
                        args=[chunk_data_b64, pattern, metadata]
                    )
                    task_ids.append(task.id)
                    total_chunks += 1

                # Actualizar Redis con la información final
                sync_redis.hset(f"job:{job_id}", "total_chunks", total_chunks)
                if task_ids:
                    sync_redis.rpush(f"job:{job_id}:task_ids", *task_ids)
                    sync_redis.expire(f"job:{job_id}:task_ids", 3600 * 24)

                logger.info(f"Todos los {total_chunks} chunks para el job {job_id} han sido encolados.", extra={'job_id': job_id, 'total_chunks': total_chunks})

            except Exception as e:
                logger.error(f"Error en el hilo de procesamiento para job {job_id}: {e}", exc_info=True)
                sync_redis.hset(f"job:{job_id}", "status", "failed")
                sync_redis.hset(f"job:{job_id}", "error_message", str(e))

        try:
            # Ejecutar la función bloqueante en el executor por defecto (un ThreadPoolExecutor)
            await loop.run_in_executor(None, blocking_code)
        except Exception as e:
            # Este error se captura si la propia tarea de `run_in_executor` falla.
            logger.error(f"Error al lanzar la tarea de fondo para el job {job_id}: {e}", exc_info=True)
            await self.redis.hset(f"job:{job_id}", "status", "failed")
            await self.redis.hset(f"job:{job_id}", "error_message", f"Failed to start processing task: {e}")

# consultas sobre el estado de la tarea por parte del cliente
    async def _handle_query_status(self, message: Dict[str, Any]) -> Dict[str, Any]:
        job_id = message['job_id']
        logger.info(f"Consulta de estado para job {job_id}", extra={'job_id': job_id})

        job_info = await self.redis.hgetall(f"job:{job_id}")    # hgetall devuelve un diccionario con todos los jobs encolados
        if not job_info:
            return {"status": "error", "message": "Job ID no encontrado."}

        current_status = job_info.get("status", "unknown")
        total_chunks = int(job_info.get("total_chunks", 0))
        
        # Leer directamente del hash (ya es atómico)
        processed_chunks = int(job_info.get("processed_chunks", 0))   
        

        # Calcular porcentaje de chunks procesados sobre el total
        percentage = (processed_chunks / total_chunks * 100) if total_chunks > 0 else 0     


        # Este bloque sirve para calcular el total de matches con el patron que buscamos
        # IMPORTANTE: deberiamos poner un contador dentro del Redis para no tener que recorrer la lista cada vez        
        # Leer contador atómico de matches
        total_matches = int(job_info.get("total_matches", 0))

        # Si todos los chunks han sido procesados y el estado no es "completed", actualizarlo
        if processed_chunks >= total_chunks and total_chunks > 0 and current_status == "processing":
            current_status = "completed"
            await self.redis.hset(f"job:{job_id}", "status", "completed")
            logger.info(f"Job {job_id} marcado como completado.", extra={'job_id': job_id})
 
        # respuesta sobre el estado de la tarea
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

    # Maneja la notificación de un worker caído que manda el Collector.
    async def _handle_worker_down(self, message: Dict[str, Any]) -> Dict[str, Any]:
        
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

    async def cleanup_old_jobs(self):
        """
        Limpia jobs completados después de 1 hora para liberar espacio en Redis.
        Se ejecuta como tarea en background cada hora.
        """
        while True:
            await asyncio.sleep(3600)  # Cada hora
            
            try:
                logger.info("Iniciando limpieza de jobs antiguos en Redis")
                
                # Buscar todos los jobs
                job_keys = await self.redis.keys("job:*")
                cleaned_count = 0
                
                for key in job_keys:
                    # Ignorar sub-keys (tasks, results, task_ids)
                    if ':' not in key or key.endswith(':tasks') or key.endswith(':results') or key.endswith(':task_ids'):
                        continue
                    
                    try:
                        job_info = await self.redis.hgetall(key)
                        
                        # Solo limpiar jobs completados
                        if job_info.get('status') == 'completed':
                            start_time = float(job_info.get('start_time', 0))
                            
                            # Si tiene más de 1 hora de completado
                            if time.time() - start_time > 3600:
                                job_id = key.split(':')[1]
                                
                                # Eliminar todas las keys relacionadas
                                await self.redis.delete(
                                    f"job:{job_id}",
                                    f"job:{job_id}:tasks",
                                    f"job:{job_id}:results",
                                    f"job:{job_id}:task_ids"
                                )
                                
                                cleaned_count += 1
                                logger.info(f"Job {job_id} limpiado de Redis (completado hace >1h)", extra={'job_id': job_id})
                    
                    except Exception as e:
                        logger.error(f"Error limpiando job {key}: {e}", extra={'key': key})
                
                logger.info(f"Limpieza completada. Jobs eliminados: {cleaned_count}", extra={'cleaned_count': cleaned_count})
            
            except Exception as e:
                logger.error(f"Error en tarea de limpieza de jobs: {e}", exc_info=True)

        # levantar el servidor Master
    async def run(self):
        self.redis = await get_redis_client()
        
        # Iniciar tarea de limpieza en background
        logger.info("Iniciando tarea de limpieza de jobs antiguos")
        asyncio.create_task(self.cleanup_old_jobs())
        
        server = await asyncio.start_server(self.handle_client, self.host, self.port)
        addr = server.sockets[0].getsockname()   # obtener la dirección del socket TCP del servidor
        logger.info(f"MasterServer escuchando en {addr}")

        async with server:
            await server.serve_forever()


if __name__ == "__main__":

    # permitimos elegir puerto con argparse
    parser = argparse.ArgumentParser(description="Master Server for Genome Analysis.")
    parser.add_argument('--port', type=int, default=MASTER_PORT, help='Port to listen on.')
    parser.add_argument('--redis-host', type=str, default=REDIS_HOST, help='Redis host.')
    parser.add_argument('--redis-port', type=int, default=REDIS_PORT, help='Redis port.')
    args = parser.parse_args()

    # Aquí deberíamos pasar los args al constructor, pero por ahora la configuración global funciona.
    # Lo ideal sería refactorizar MasterServer para que acepte redis_host y redis_port.
    master_server = MasterServer(port=args.port)
    try:
        asyncio.run(master_server.run())
    except KeyboardInterrupt:  # Ctrl+C
        logger.info("MasterServer detenido por el usuario.")
    except Exception as e:   # error inesperado
        logger.critical(f"MasterServer ha terminado con un error crítico: {e}", exc_info=True)