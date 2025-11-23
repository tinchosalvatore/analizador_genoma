import asyncio
import os
import json
import socket
import time
import argparse
import redis
from collections import defaultdict

from src.config.settings import (
    COLLECTOR_PORT, MASTER_HOST, MASTER_PORT, REDIS_HOST, REDIS_PORT,
    COLLECTOR_METRICS_TTL, COLLECTOR_WORKER_TIMEOUT, COLLECTOR_MONITOR_INTERVAL,
    COLLECTOR_LISTEN_HOSTS
)

from src.utils.logger import setup_logger
logger = setup_logger('collector_server', log_file=f'{os.getenv("LOG_DIR", "/app/logs")}/collector_server.log')

class CollectorServer:

    # sus valores por defectos sacados de settings.py se pasan por el argparse como default
    def __init__(self, port: int, master_host: str, master_port: int, redis_host: str, redis_port: int,
                 metrics_ttl: int, worker_timeout: int, monitor_interval: int, listen_hosts: list[str]):
        self.port = port
        self.master_host = master_host
        self.master_port = master_port
        self.redis_client = redis.Redis(host=redis_host, port=redis_port, decode_responses=True)
        self.worker_states = defaultdict(dict)
        self.metrics_ttl = metrics_ttl
        self.worker_timeout = worker_timeout
        self.monitor_interval = monitor_interval
        self.listen_hosts = listen_hosts


        
    async def handle_agent(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """
        Recibe métricas de un agente con socket TCP
        """

        # obtemos info del cliente 
        # La tupla de addr tiene 2 elementos para IPv4 (host, port)
        # y 4 elementos para IPv6 (host, port, flowinfo, scopeid)
        addr = writer.get_extra_info('peername')
        logger.info(f"Conexión recibida de {addr}")
        

        data = b""  # b es de bytes
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
            else:  # debe ser un msj erroneo porque al collector solo le enviamos 'metrics'
                logger.warning(f"Mensaje de tipo desconocido recibido de {addr}: {message.get('type')}")

        except json.JSONDecodeError:
            logger.error(f"Error decodificando JSON del agente {addr}.")
        except Exception as e:
            logger.error(f"Error procesando mensaje del agente {addr}: {e}")
        
        finally: # cerramos la conexion
            logger.info(f"Cerrando conexión con {addr}")
            writer.close()
            await writer.wait_closed()



    async def process_metrics(self, metrics: dict):
        """
        Procesa las métricas (CPU y MEM) recibidas del agente y detecta anomalías
        """
        
        worker_id = metrics.get('worker_id') 
        if not worker_id:
            logger.warning("Métrica recibida sin worker_id")
            return

        logger.info(f"Métrica recibida de {worker_id}: CPU {metrics.get('cpu_percent'):.2f}%, MEM {metrics.get('memory_percent'):.2f}%")

        # actualizamos el diccionario de estado del worker
        self.worker_states[worker_id] = {
            'last_update': time.time(),
            'metrics': metrics
        }
        
        # guardamos las meticas en Redis
        self.redis_client.setex(
            f'worker:{worker_id}:metrics',
            self.metrics_ttl,
            json.dumps(metrics)
        )
        
        # Resetear la flag de timeout si el worker vuelve a reportar
        if worker_id in self.worker_states and 'alerted_timeout' in self.worker_states[worker_id]:
            del self.worker_states[worker_id]['alerted_timeout']  # borramos la flag
            logger.info(f"Worker {worker_id} se recuperó del timeout, flag reseteado", extra={'worker_id': worker_id})
        

        # una vez procesada, buscamos anomalias en el reporte con la corrutina definida abajo
        await self.check_anomalies(worker_id, metrics)   


    async def check_anomalies(self, worker_id: str, metrics: dict):
        """
        Detecta si hay anomalías en las métricas y notifica al Master
        """
        
        if metrics.get('status') == 'DEAD':
            alert = {  # creamos la alerta y la enviamos al Master Server
                'severity': 'CRITICAL',
                'worker_id': worker_id,
                'message': f'Worker {worker_id} ha dejado de responder (reportado como DEAD por su agente)',
                'timestamp': time.time()
            }

            # corrutinas para gestionar las alertas de Workers y avisar al Master
            await self.log_alert(alert)
            await self.notify_master(alert)


    async def log_alert(self, alert: dict):
        """
        Loggea la alerta como CRITICAL o WARNING, ya que es la max emergencia del programa
        """

        log_method = logger.critical if alert['severity'] == 'CRITICAL' else logger.warning
        log_method(alert['message'], extra=alert)


    async def notify_master(self, alert: dict):
        """
        Notifica al Master sobre una alerta crítica mediante socket TCP
        """

        if alert['severity'] != 'CRITICAL': # si no es una alerta crítica, no hacemos nada
            return

        logger.info(f"Notificando al Master sobre la alerta de {alert['worker_id']}")
        
        reader, writer = None, None
        try:
            # Obtener todas las direcciones posibles (IPv4 e IPv6)
            addrs = await asyncio.get_event_loop().getaddrinfo(
                self.master_host, self.master_port, socket.AF_UNSPEC, socket.SOCK_STREAM
            )


            connected = False  # flag para saber si se conecto al Master con exito            
            # conectar a cada dirección, al conectarse una se rompe el bucle
            for family, socktype, proto, canonname, sockaddr in addrs:
                try:
                    reader, writer = await asyncio.open_connection(
                        host=sockaddr[0], port=sockaddr[1], family=family
                    )
                    connected = True
                    logger.info(f"Conectado a Master Server en {sockaddr} usando {family}", extra={'sockaddr': sockaddr, 'family': family})
                    break
                except OSError as e:  # fallaron ambas familias Ip
                    logger.warning(f"Fallo al conectar a {sockaddr}: {e}")
                    if writer:
                        writer.close()
                        await writer.wait_closed()
                    reader, writer = None, None
            
            if not connected:
                raise ConnectionRefusedError(f"No se pudo conectar al Master Server en {self.master_host}:{self.master_port}")

            message = {  # creamos el msj de alerta siguiendo el protocolo
                'type': 'worker_down',
                'worker_id': alert['worker_id'],
                'timestamp': alert['timestamp']
            }
            
            # lo mandamos al Master
            writer.write(json.dumps(message).encode())
            await writer.drain()
            logger.info(f"Notificación enviada al Master para {alert['worker_id']}")

        # errores
        except ConnectionRefusedError:
            logger.error(f"No se pudo notificar al Master. Conexión rechazada en {self.master_host}:{self.master_port}")
        except Exception as e:
            logger.error(f"Error inesperado notificando al Master: {e}")

        finally:   # cerramos la conexion
            if writer:
                writer.close()
                await writer.wait_closed()


    async def monitor_timeouts(self):
        """
        Verifica si algún worker ha dejado de reportar métricas
        """
        while True:
            await asyncio.sleep(self.monitor_interval)   # espera el tiempo de intervalo de monitoreo (30 seg)
            current_time = time.time()
            
            for worker_id, state in list(self.worker_states.items()):
                # si en los ultimos 30 seg no se ha reportado, enviamos una alerta
                if 'alerted_timeout' not in state and (current_time - state.get('last_update', 0) > self.worker_timeout):
                    alert = {
                        'severity': 'CRITICAL',
                        'worker_id': worker_id,
                        'message': f'Worker {worker_id} no reporta métricas hace más de {self.worker_timeout} segundos (timeout).',
                        'timestamp': current_time
                    }


            # corrutinas para gestionar las alertas de Workers y avisar al Master
                    self.worker_states[worker_id]['alerted_timeout'] = True
                    await self.log_alert(alert)
                    await self.notify_master(alert)


    # Inicia el servidor collector
    async def run(self):
        # Iniciar el monitor de timeouts en paralelo
        asyncio.create_task(self.monitor_timeouts())
        
        # Usar asyncio.start_server para escuchar en las interfaces configuradas
        server = await asyncio.start_server(
            self.handle_agent,
            self.listen_hosts,
            self.port
        )
        
        # Log all bound addresses
        for sock in server.sockets:
            addr = sock.getsockname()
            family_name = 'IPv6' if sock.family == socket.AF_INET6 else 'IPv4'
            logger.info(f'Collector Server escuchando en {addr} (familia {family_name})')

        async with server:
            await server.serve_forever() 


def main():
    # permitimos algunos argumentos como elegir puerto del collector, indicar el puerto del Master y el de Redis
    parser = argparse.ArgumentParser(description="Servidor Collector para métricas de workers.")
    parser.add_argument('--port', type=int, default=COLLECTOR_PORT, help='Puerto para escuchar a los agentes.')
    parser.add_argument('--master-host', default=MASTER_HOST, help='Host del Master Server.')
    parser.add_argument('--master-port', type=int, default=MASTER_PORT, help='Puerto del Master Server.')
    parser.add_argument('--redis-host', default=REDIS_HOST, help='Host de Redis.')
    parser.add_argument('--redis-port', type=int, default=REDIS_PORT, help='Puerto de Redis.')
    parser.add_argument('--metrics-ttl', type=int, default=COLLECTOR_METRICS_TTL, help='Tiempo de vida (TTL) de las métricas en Redis (segundos).')
    parser.add_argument('--worker-timeout', type=int, default=COLLECTOR_WORKER_TIMEOUT, help='Tiempo en segundos sin reporte para considerar un worker en timeout.')
    parser.add_argument('--monitor-interval', type=int, default=COLLECTOR_MONITOR_INTERVAL, help='Intervalo en segundos para el monitor de timeouts.')
    parser.add_argument('--listen-hosts', type=lambda s: s.split(','), default=COLLECTOR_LISTEN_HOSTS, help='Lista de hosts donde el Collector escuchará (separados por comas, ej: "0.0.0.0,::").')
    args = parser.parse_args()

    # iniciamos el servidor usando sus variables de entorno
    collector = CollectorServer(
        port=args.port,
        master_host=args.master_host,
        master_port=args.master_port,
        redis_host=args.redis_host,
        redis_port=args.redis_port,
        metrics_ttl=args.metrics_ttl,
        worker_timeout=args.worker_timeout,
        monitor_interval=args.monitor_interval,
        listen_hosts=args.listen_hosts
    )
    
    try:
        asyncio.run(collector.run())
    except KeyboardInterrupt: # ctrl+c
        logger.info("Collector Server detenido.")

if __name__ == "__main__":
    main()