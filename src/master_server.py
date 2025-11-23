import argparse
import os
import asyncio
import json
import base64
import time
import re
import socket
from typing import Dict, Any

import redis.asyncio as aioredis # Usar la versión async de Redis
from celery import Celery

from src.config.settings import MASTER_PORT, REDIS_HOST, REDIS_PORT, CELERY_BROKER, CELERY_BACKEND, DEFAULT_CHUNK_SIZE
from src.utils.logger import setup_logger
from src.utils.protocol import validate_message
from src.utils.chunker import divide_data_with_overlap # divide el archivo completo



# Configurar el logger para el master
logger = setup_logger('master_server', f'{os.getenv("LOG_DIR", "/app/logs")}/master_server.log')

# Configuración de Celery para el Master (solo para encolar las tareas)
celery_app = Celery('master_tasks', broker=CELERY_BROKER, backend=CELERY_BACKEND)

# Cliente Redis asíncrono (inicializado en None)
redis_client: aioredis.Redis | None = None

# Obtiene o inicializa el cliente Redis asíncrono
# En src/master_server.py

async def get_redis_client() -> aioredis.Redis:
    global redis_client
    if redis_client is None:
        try:
            # Forzamos al Master a usar la DB 1
            redis_client = aioredis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=1, decode_responses=True)
            await redis_client.ping() # Verificar conexión
            logger.info("Cliente Redis asíncrono inicializado para el Master (DB 1).", extra={'redis_host': REDIS_HOST, 'redis_port': REDIS_PORT})
        except Exception as e:
            logger.error(f"Error al inicializar el cliente Redis asíncrono para el Master (DB 1): {e}")
            raise
    return redis_client

class MasterServer:
# constructor principal, para levantar el servidor
    def __init__(self, host: str | list[str] | None = None, port: int = MASTER_PORT):
        self.host = host if host is not None else ['0.0.0.0', '::'] # Listen on all IPv4 and IPv6 interfaces
        self.port = port
        self.redis_client: aioredis.Redis | None = None
        logger.info(f"MasterServer inicializado en {self.host}:{self.port}")

        
    # <=========== HANDLERS ===========>

    # Maneja las conexiones entrantes de los clientes de manera asincrona
    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        
        # Obtenemos la información de la conexion del cliente
        addr = writer.get_extra_info('peername')
        
        # La tupla de addr tiene 2 elementos para IPv4 (host, port)
        # y 4 elementos para IPv6 (host, port, flowinfo, scopeid)
        ip_familia = "IPv4" if len(addr) == 2 else "IPv6"
        ip_cliente, puerto_cliente = addr[0], addr[1]
        
        # logger que indica quien esta conectado al master!  (para demostrar que trabaja IPv6 o IPv4 segun se solicita)
        logger.info(
            "Nueva conexión recibida",
            extra={
                'client_ip': ip_cliente,
                'client_port': puerto_cliente,
                'ip_family': ip_familia,
                'full_addr': str(addr)
            }
        )

        try:
            # 1. Bucle de lectura de datos
            data_chunks = []
            while True:
                chunk = await reader.read(65536) # Leer en chunks de 64KB
                if not chunk:
                    # EOF (End-of-File), el cliente notificó que terminó de enviar
                    break
                data_chunks.append(chunk)
            
            data = b"".join(data_chunks)

            if not data:
                logger.warning(f"No se recibieron datos de {addr}")
                return

            # 2. Ahora que tenemos TODOS los datos, decodificamos y convertimos a JSON
            message_str = data.decode('utf-8')
            message = json.loads(message_str)

            # 3. Procesamos el mensaje y lo validos siguiendo los protocolos
            msg_type = message.get('type')
            is_valid, error_msg = validate_message(message, msg_type) 

            if not is_valid:
                logger.warning(f"Mensaje inválido de {addr}: {error_msg}", extra={'message': message})
                response = {"status": "error", "message": error_msg}
            

            # llamamos a la corrutina correspondiente al tipo de solicitud que llego al server
            elif msg_type == 'submit_job':
                response = await self._handle_submit_job(message)
            elif msg_type == 'query_status':
                response = await self._handle_query_status(message)
            elif msg_type == 'worker_down':
                response = await self._handle_worker_down(message)
            
            else:
                logger.warning(f"Tipo de mensaje desconocido de {addr}: {msg_type}", extra={'message': message})
                response = {"status": "error", "message": f"Tipo de mensaje desconocido: {msg_type}"}

            # 4. Enviamos la respuesta
            writer.write(json.dumps(response).encode('utf-8'))
            await writer.drain()


        # 5. Manejo de errores
        except json.JSONDecodeError:
            logger.error(f"Error de decodificación JSON de {addr}. El JSON recibido estaba mal formado o incompleto.", exc_info=True)
            response = {"status": "error", "message": "Formato JSON inválido."}
            if not writer.is_closing():
                writer.write(json.dumps(response).encode('utf-8'))
                await writer.drain()
        except Exception as e:
            logger.error(f"Error manejando cliente {addr}: {e}", exc_info=True)
            response = {"status": "error", "message": f"Error interno del servidor: {e}"}
            if not writer.is_closing():
                try:
                    writer.write(json.dumps(response).encode('utf-8'))
                    await writer.drain()
                except Exception as e2:
                    logger.error(f"Error enviando mensaje de error al cliente {addr}: {e2}")

        # 6. Cierre final
        finally:
            logger.info(f"Cerrando conexión con {addr}")
            writer.close()
            await writer.wait_closed()




    #Procesa una peticion de trabajo de análisis genómico por parte del cliente
    async def _handle_submit_job(self, message: Dict[str, Any]) -> Dict[str, Any]:
        job_id = message['job_id']
        filename = message['filename']
        pattern = message['pattern']
        file_size = message['file_size']
        chunk_size = message.get('chunk_size', DEFAULT_CHUNK_SIZE)

        logger.info(f"Job {job_id} recibido: {filename}, patrón: {pattern}", extra={'job_id': job_id, 'job_filename': filename, 'pattern': pattern, 'file_size': file_size})

        # --- VALIDACIONES RÁPIDAS ---

        if not re.match(r'^[ACGT]+$', pattern): # Si el archivo no esta compuesto por A, C, G, T
            logger.error(f"Patrón inválido recibido para job {job_id}: {pattern}", extra={'job_id': job_id, 'pattern': pattern})
            return {
                "status": "error",
                "message": f"Patrón inválido. Solo se permiten caracteres A, C, G, T. Patrón recibido: {pattern}"
            }
        if len(pattern) < 2:  # si el patron es demasiado corto
            logger.error(f"Patrón demasiado corto para job {job_id}: {len(pattern)} caracteres", extra={'job_id': job_id})
            return {
                "status": "error",
                "message": f"El patrón debe tener al menos 2 caracteres. Longitud actual: {len(pattern)}"
            }
        if len(pattern) > 100:   # si el patron es demasiado largo
            logger.error(f"Patrón demasiado largo para job {job_id}: {len(pattern)} caracteres", extra={'job_id': job_id})
            return {
                "status": "error",
                "message": f"El patrón no puede exceder 100 caracteres. Longitud actual: {len(pattern)}"
            }
        # --- FIN DE VALIDACIONES ---

        
        total_chunks_estimate = (file_size // chunk_size) + 1

        try:
            # Guardar estado INICIAL del job en Redis (marcarlo como "encolando")
            # con un hash del Job_ID que lo identifica
            await self.redis.hset(f"job:{job_id}", mapping={
                "status": "queuing", # "queuing" (encolando) es el nuevo estado inicial
                "filename": filename,
                "pattern": pattern,
                "total_chunks": total_chunks_estimate, # Se actualizará en background
                "processed_chunks": 0,
                "total_matches": 0,
                "start_time": time.time(),
                "file_size": file_size,
                "chunk_size": chunk_size
            })

            await self.redis.expire(f"job:{job_id}", 3600 * 24)   # ttl, se limpia el archivo despues de 24 horas

            # Lanzamos el procesamiento pesado de fondo, no esperamos con el cliente a un await
            asyncio.create_task(self._process_job_background(message))

            # Tiempo estimado de ejecucion
            estimated_time = (total_chunks_estimate * 0.0013)

            logger.info(f"Job {job_id} aceptado para encolado en background.", extra={'job_id': job_id})
            
            # Devolvemos la respuesta INMEDIATAMENTE al cliente
            return {
                "status": "accepted",
                "job_id": job_id,
                "total_chunks": total_chunks_estimate, 
                "estimated_time": round(estimated_time, 2)
            }
        
        except Exception as e:
            logger.error(f"Error procesando submit_job (fase inicial) para {job_id}: {e}", exc_info=True, extra={'job_id': job_id})
            return {"status": "error", "message": f"Fallo al aceptar el trabajo: {e}"}
        


    # Esta corrutina se ejecuta en segundo plano para no bloquear al cliente mientras se procesan los chunks
    async def _process_job_background(self, message: Dict[str, Any]):
        job_id = message['job_id']
        pattern = message['pattern']
        chunk_size = message.get('chunk_size', DEFAULT_CHUNK_SIZE)
        file_data_b64 = message['file_data_b64']
        
        try:
            # 1. Actualizar estado en Redis (rápido, no bloquea)
            await self.redis.hset(f"job:{job_id}", "status", "processing")

            # 2. Ejecutamos la función bloqueante en un hilo separado.
            # El 'await' aquí solo espera a que el hilo termine,
            # pero el event loop principal (servidor) sigue LIBRE.
            total_chunks, task_ids = await asyncio.to_thread(
                self._blocking_enqueue_work,   # mandamos como hilo la tarea de encolado de chunks
                job_id,
                pattern,
                chunk_size,
                file_data_b64
            )
            
            if total_chunks == -1: # significa que hubo un error  (ver return de excepcion de _blocking_enqueue_work)
                raise Exception("Falló el _blocking_enqueue_work")

            # 3. Actualizar Redis con la info final 
            if task_ids: # actualiza agregando los task_ids (uno por chunk)
                await self.redis.rpush(f"job:{job_id}:task_ids", *task_ids)  
                await self.redis.expire(f"job:{job_id}:task_ids", 3600 * 24)  # ttl, expira en 24 horas

            logger.info(f"Encolado en background (async) completado para job {job_id}. Total chunks: {total_chunks}", extra={'job_id': job_id, 'total_chunks': total_chunks})

        except Exception as e:
            logger.error(f"Error en el procesamiento en background del job {job_id}: {e}", exc_info=True, extra={'job_id': job_id})
            # Marcar el job como fallido en Redis
            await self.redis.hset(f"job:{job_id}", "status", "failed")
            await self.redis.hset(f"job:{job_id}", "error_message", str(e))


    def _blocking_enqueue_work(self, job_id: str, pattern: str, chunk_size: int, file_data_b64: str) -> int:
        """
        Función síncrona que hace todo el trabajo pesado de CPU
        (decodificar, dividir, encolar) para ser ejecutada en un hilo separado.
        """
        try:
            # 2. Decodificar y dividir en chunks con overlap (esto tarda)
            logger.info(f"Iniciando decodificación (bloqueante) para job {job_id}", extra={'job_id': job_id})
            file_data = base64.b64decode(file_data_b64)  # decodifica el archivo
            chunks_generator = divide_data_with_overlap(file_data, chunk_size=chunk_size) # funcion de chunker.py
            
            total_chunks = 0
            task_ids = []

            # 3. El bucle de encolado de los chunks
            logger.info(f"Iniciando bucle de encolado (bloqueante) para job {job_id}", extra={'job_id': job_id})
            for chunk_id, chunk_data, metadata in chunks_generator:
                chunk_data_b64_for_celery = base64.b64encode(chunk_data).decode('utf-8')  # codifica los chunks
                
                # Pasamos el job_id al worker
                metadata['job_id'] = job_id
                
                task = celery_app.send_task(
                    'src.genome_worker.find_pattern',
                    args=[chunk_data_b64_for_celery, pattern, metadata]
                )
                task_ids.append(task.id)
                total_chunks += 1
            
            logger.info(f"Encolado bloqueante completado para job {job_id}. Total chunks: {total_chunks}", extra={'job_id': job_id, 'total_chunks': total_chunks})
            
            return total_chunks, task_ids

        except Exception as e:
            logger.error(f"Error en _blocking_enqueue_work para job {job_id}: {e}", exc_info=True, extra={'job_id': job_id})
            # Devolvemos -1 para indicar error
            return -1, []



# consultas sobre el estado de la tarea por parte del cliente
    async def _handle_query_status(self, message: Dict[str, Any]) -> Dict[str, Any]:
        job_id = message['job_id']
        logger.info(f"Consulta de estado para job {job_id}", extra={'job_id': job_id})

# hgetall devuelve un diccionario con todos los jobs encolados (es como un select all de Redis)
        job_info = await self.redis.hgetall(f"job:{job_id}")    
        if not job_info:
            return {"status": "error", "message": "Job ID no encontrado."}

        current_status = job_info.get("status", "unknown")
        total_chunks = int(job_info.get("total_chunks", 0))
        
        # Leer directamente del hash (mas rapido)
        processed_chunks = int(job_info.get("processed_chunks", 0))   
        

        # Calcular porcentaje de chunks procesados sobre el total
        percentage = (processed_chunks / total_chunks * 100) if total_chunks > 0 else 0     


        # Este bloque sirve para calcular el total de matches con el patron que buscamos
        # Leer contador atómico de matches
        total_matches = int(job_info.get("total_matches", 0))

        # Si todos los chunks han sido procesados y el estado no es "completed" (por bug), actualizarlo
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

    async def _handle_worker_down(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """
        Maneja la notificación de un worker caído que manda el Collecto Server.
        """
        
        worker_id = message['worker_id']
        timestamp = message['timestamp']
        
        logger.warning(f"Notificación de worker caído recibida: {worker_id} a las {timestamp}", extra={'worker_id': worker_id, 'timestamp': timestamp})
        
        
        # Marcamos el worker como caído en Redis para que quede registro de que ha dejado de responder 
        # de todas maneras del reencolamiento se encarga Celery con el "ack_late = True"
        await self.redis.hset(f"worker_status:{worker_id}", "status", "DEAD")
        await self.redis.hset(f"worker_status:{worker_id}", "last_down_timestamp", timestamp)
        
        return {"status": "acknowledged", "message": f"Alerta de worker {worker_id} recibida."}

    async def cleanup_old_jobs(self):
        """
        Limpia jobs completados después de 1 hora para liberar espacio en Redis.
        Se ejecuta como tarea en background cada hora.
        """
        while True:
            await asyncio.sleep(3600)  # 3600 seg = 1 hora
            
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
        self.redis = await get_redis_client()   # esperamos a obtener el cliente Redis
        
        # Iniciar tarea de limpieza en background
        logger.info("Iniciando tarea de limpieza de jobs antiguos")
        asyncio.create_task(self.cleanup_old_jobs())
        
        server = await asyncio.start_server(self.handle_client, self.host, self.port)
        
        for sock in server.sockets:
            addr = sock.getsockname()
            family_name = 'IPv6' if sock.family == socket.AF_INET6 else 'IPv4'
            logger.info(f"MasterServer escuchando en {addr} (familia {family_name})")

        async with server:
            await server.serve_forever()


if __name__ == "__main__":

    # permitimos elegir puerto con argparse
    parser = argparse.ArgumentParser(description="Master Server for Genome Analysis.")
    parser.add_argument('--port', type=int, default=MASTER_PORT, help='Port to listen on.')
    args = parser.parse_args()

    master_server = MasterServer(port=args.port)
    
    try:
        asyncio.run(master_server.run())
    except KeyboardInterrupt:  # Ctrl+C
        logger.info("MasterServer detenido por el usuario.")
    except Exception as e:   # error inesperado
        logger.critical(f"MasterServer ha terminado con un error crítico: {e}", exc_info=True)