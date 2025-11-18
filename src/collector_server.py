import asyncio
import os
import json
import socket
import time
import argparse
import redis
from collections import defaultdict

from src.utils.logger import setup_logger

logger = setup_logger('collector_server', log_file=f'{os.getenv("LOG_DIR", "/app/logs")}/collector_server.log')

class CollectorServer:
    def __init__(self, port: int, master_host: str, master_port: int, redis_host: str, redis_port: int):
        self.port = port
        self.master_host = master_host
        self.master_port = master_port
        self.redis_client = redis.Redis(host=redis_host, port=redis_port, decode_responses=True)
        self.worker_states = defaultdict(dict)   # vamos a guardar el estado de los workers en un diccionario


        
        # Recibe métricas de un agente con socket TCP
    async def handle_agent(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        addr = writer.get_extra_info('peername')
        logger.info(f"Conexión recibida de {addr}")
        
        data = b""
        try:
            # Leemos los datos en chunks para manejar mensajes grandes
            while True:
                chunk = await reader.read(4096)
                if not chunk:
                    break
                data += chunk

            if not data:
                logger.warning(f"No se recibieron datos de {addr}")
                return

            message = json.loads(data.decode())

            if message.get('type') == 'metrics':
                await self.process_metrics(message['data'])
            else:
                logger.warning(f"Mensaje de tipo desconocido recibido de {addr}: {message.get('type')}")

        except json.JSONDecodeError:
            logger.error(f"Error decodificando JSON del agente {addr}.")
        except Exception as e:
            logger.error(f"Error procesando mensaje del agente {addr}: {e}")
        finally:
            logger.info(f"Cerrando conexión con {addr}")
            writer.close()
            await writer.wait_closed()


        # Procesa las métricas y detecta anomalías
    async def process_metrics(self, metrics: dict):
        
        worker_id = metrics.get('worker_id') 
        if not worker_id:
            logger.warning("Métrica recibida sin worker_id")
            return

        # analizamos metricas y detectamos anomalias
        logger.info(f"Métrica recibida de {worker_id}: CPU {metrics.get('cpu_percent'):.2f}%, MEM {metrics.get('memory_percent'):.2f}%")

        # actualizamos el estado del worker
        self.worker_states[worker_id] = {
            'last_update': time.time(),
            'metrics': metrics
        }
        
        # guardamos las meticas en Redis
        self.redis_client.setex(
            f'worker:{worker_id}:metrics',
            60,   # cada metrica dura 60s y se borra, osea, 6 ciclos de reportes de los Agents (son cada 10s)
            json.dumps(metrics)
        )
        
        # Resetear flag de timeout si el worker vuelve a reportar
        if worker_id in self.worker_states and 'alerted_timeout' in self.worker_states[worker_id]:
            del self.worker_states[worker_id]['alerted_timeout']
            logger.info(f"Worker {worker_id} se recuperó del timeout, flag reseteado", extra={'worker_id': worker_id})
        
        await self.check_anomalies(worker_id, metrics)   # una vez procesada, buscamos anomalias en el reporte


        # Detecta si hay anomalías en las métricas y notifica al Master
    async def check_anomalies(self, worker_id: str, metrics: dict):
        if metrics.get('status') == 'DEAD':
            alert = {
                'severity': 'CRITICAL',
                'worker_id': worker_id,
                'message': f'Worker {worker_id} ha dejado de responder (reportado como DEAD por su agente)',
                'timestamp': time.time()
            }
            await self.send_alert(alert)
            await self.notify_master(alert)


        # Loggea la alerta como CRITICAL o WARNING, ya que es la max emergencia del programa
    async def send_alert(self, alert: dict):
        log_method = logger.critical if alert['severity'] == 'CRITICAL' else logger.warning
        log_method(alert['message'], extra=alert)


        # Notifica al Master sobre una alerta crítica
    async def notify_master(self, alert: dict):
        if alert['severity'] != 'CRITICAL': # si no es una alerta crítica, no hacemos nada
            return

        logger.info(f"Notificando al Master sobre la alerta de {alert['worker_id']}")
        
        reader, writer = None, None
        try:
            # Obtener todas las direcciones posibles (IPv4 e IPv6)
            addrs = await asyncio.get_event_loop().getaddrinfo(
                self.master_host, self.master_port, socket.AF_UNSPEC, socket.SOCK_STREAM
            )

            # Intentar conectar a cada dirección hasta que una funcione
            connected = False
            for family, socktype, proto, canonname, sockaddr in addrs:
                try:
                    reader, writer = await asyncio.open_connection(
                        host=sockaddr[0], port=sockaddr[1], family=family
                    )
                    connected = True
                    logger.info(f"Conectado a Master Server en {sockaddr} usando {family}", extra={'sockaddr': sockaddr, 'family': family})
                    break
                except OSError as e:
                    logger.warning(f"Fallo al conectar a {sockaddr}: {e}")
                    if writer:
                        writer.close()
                        await writer.wait_closed()
                    reader, writer = None, None
            
            if not connected:
                raise ConnectionRefusedError(f"No se pudo conectar al Master Server en {self.master_host}:{self.master_port}")

            message = {
                'type': 'worker_down',
                'worker_id': alert['worker_id'],
                'timestamp': alert['timestamp']
            }
            
            writer.write(json.dumps(message).encode())
            await writer.drain()
            logger.info(f"Notificación enviada al Master para {alert['worker_id']}")

        except ConnectionRefusedError:
            logger.error(f"No se pudo notificar al Master. Conexión rechazada en {self.master_host}:{self.master_port}")
        except Exception as e:
            logger.error(f"Error inesperado notificando al Master: {e}")
        finally:
            if writer:
                writer.close()
                await writer.wait_closed()


    # Verifica si algún worker ha dejado de reportar métricas
    async def monitor_timeouts(self):
        while True:
            await asyncio.sleep(10)   # espera los 10 seg que tarda en reportar un Agent
            current_time = time.time()
            
            for worker_id, state in list(self.worker_states.items()):
                # si en los ultimos 30 seg no se ha reportado, enviamos una alerta
                if 'alerted_timeout' not in state and (current_time - state.get('last_update', 0) > 30):
                    alert = {
                        'severity': 'CRITICAL',
                        'worker_id': worker_id,
                        'message': f'Worker {worker_id} no reporta métricas hace más de 30 segundos (timeout).',
                        'timestamp': current_time
                    }

                    # marcamos la alerta como enviada y la enviamos
                    self.worker_states[worker_id]['alerted_timeout'] = True
                    await self.send_alert(alert)
                    await self.notify_master(alert)


    # Inicia el servidor collector
    async def run(self):
        # Iniciar el monitor de timeouts en paralelo
        asyncio.create_task(self.monitor_timeouts())
        
        # Usar asyncio.start_server para escuchar en todas las interfaces (IPv4 e IPv6)
        server = await asyncio.start_server(
            self.handle_agent,
            ['0.0.0.0', '::'],  # Dual-Stack: IPv4 + IPv6
            self.port
        )
        
        # Log all bound addresses
        for sock in server.sockets:
            addr = sock.getsockname()
            logger.info(f'Collector Server escuchando en {addr}')

        async with server:
            await server.serve_forever() 


def main():
    # permitimos algunos argumentos como elegir puerto del collector, indicar el puerto del Master y el de Redis
    parser = argparse.ArgumentParser(description="Servidor Collector para métricas de workers.")
    parser.add_argument('--port', type=int, default=6000, help='Puerto para escuchar a los agentes.')
    parser.add_argument('--master-host', default='localhost', help='Host del Master Server.')
    parser.add_argument('--master-port', type=int, default=5000, help='Puerto del Master Server.')
    parser.add_argument('--redis-host', default='localhost', help='Host de Redis.')
    parser.add_argument('--redis-port', type=int, default=6379, help='Puerto de Redis.')
    args = parser.parse_args()

    # iniciamos el servidor usando sus variables de entorno
    collector = CollectorServer(
        port=args.port,
        master_host=args.master_host,
        master_port=args.master_port,
        redis_host=args.redis_host,
        redis_port=args.redis_port
    )
    
    try:
        asyncio.run(collector.run())
    except KeyboardInterrupt:
        logger.info("Collector Server detenido.")

if __name__ == "__main__":
    main()