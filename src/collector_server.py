import asyncio
import os
import json
import socket
import time
import argparse
import redis
import struct  # Necesario para el empaquetado de encabezados
from collections import defaultdict

from src.utils.logger import setup_logger

logger = setup_logger('collector_server', log_file=f"{os.getenv('LOG_DIR', 'logs')}/collector_server.log")

class CollectorServer:
    def __init__(self, port: int, master_host: str, master_port: int, redis_host: str, redis_port: int):
        self.port = port
        self.master_host = master_host
        self.master_port = master_port
        self.redis_client = redis.Redis(host=redis_host, port=redis_port, decode_responses=True)
        self.worker_states = defaultdict(dict)   # vamos a guardar el estado de los workers en un diccionario


        
        # Recibe métricas de un agente con socket TCP
    async def handle_agent(self, conn: socket.socket, addr: tuple):
        logger.info(f"Conexión recibida de {addr}")
        loop = asyncio.get_running_loop()
        try:
            # Leer encabezado de 4 bytes para obtener la longitud del mensaje
            header_data = b''
            while len(header_data) < 4:
                packet = await loop.sock_recv(conn, 4 - len(header_data))
                if not packet:
                    raise ConnectionError("Conexión cerrada prematuramente por el agente.")
                header_data += packet
            
            message_length = struct.unpack('!I', header_data)[0]

            # Leer el cuerpo del mensaje completo
            data = b''
            while len(data) < message_length:
                packet = await loop.sock_recv(conn, message_length - len(data))
                if not packet:
                    raise ConnectionError("Conexión perdida mientras se recibía el mensaje del agente.")
                data += packet
            
            message = json.loads(data.decode('utf-8'))

            # Asumiendo que el tipo de mensaje siempre es 'metrics' desde el agente
            # El agente enviará el diccionario de métricas directamente, no anidado en 'data'
            await self.process_metrics(message)

        except json.JSONDecodeError:
            logger.error(f"Error decodificando JSON del agente {addr}.")
        except Exception as e:
            logger.error(f"Error procesando mensaje del agente {addr}: {e}", exc_info=True)
        finally:
            logger.info(f"Cerrando conexión con {addr}")
            conn.close()


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
                'alert_message': f'Worker {worker_id} ha dejado de responder (reportado como DEAD por su agente)',
                'timestamp': time.time()
            }
            await self.send_alert(alert)
            await self.notify_master(alert)


    async def send_alert(self, alert: dict):
        """Loggea la alerta como CRITICAL o WARNING, ya que es la max emergencia del programa"""
        log_method = logger.critical if alert['severity'] == 'CRITICAL' else logger.warning
        
        # Crear una copia para no modificar el diccionario original
        extra_data = alert.copy()
        # El mensaje principal ya se pasa como primer argumento, lo eliminamos de 'extra'
        del extra_data['alert_message']
        
        log_method(alert['alert_message'], extra=extra_data)


        # Notifica al Master sobre una alerta crítica
    async def notify_master(self, alert: dict):
        if alert['severity'] != 'CRITICAL':
            return

        logger.info(f"Notificando al Master sobre la alerta de {alert['worker_id']}")
        
        message = {
            'type': 'worker_down',
            'worker_id': alert['worker_id'],
            'timestamp': alert['timestamp']
        }
        
        try:
            # Usar asyncio.open_connection para una API más moderna y simple
            reader, writer = await asyncio.open_connection(self.master_host, self.master_port)
            
            # Convertir mensaje a bytes y crear encabezado
            message_data = json.dumps(message).encode('utf-8')
            header = struct.pack('!I', len(message_data))
            
            # Enviar encabezado y luego el mensaje
            writer.write(header)
            writer.write(message_data)
            await writer.drain()
            
            logger.info(f"Notificación enviada al Master para {alert['worker_id']}")

        except ConnectionRefusedError:
            logger.error(f"No se pudo notificar al Master. Conexión rechazada en {self.master_host}:{self.master_port}")
        except Exception as e:
            logger.error(f"Error inesperado notificando al Master: {e}", exc_info=True)
        finally:
            if 'writer' in locals() and not writer.is_closing():
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
                        'alert_message': f'Worker {worker_id} no reporta métricas hace más de 30 segundos (timeout).',
                        'timestamp': current_time
                    }

                    # marcamos la alerta como enviada y la enviamos
                    self.worker_states[worker_id]['alerted_timeout'] = True
                    await self.send_alert(alert)
                    await self.notify_master(alert)


    # Inicia el servidor collector
    async def run(self):
        loop = asyncio.get_running_loop()
        
        # Iniciamos el socket TCP para que pueda recibir conexiones
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setblocking(False)  # no bloqueante (espera en segundo plano)
        server_socket.bind(('0.0.0.0', self.port))   # fijamos al host 0.0.0.0
        server_socket.listen()   # indicamos que es solo de escucha
        
        addr = server_socket.getsockname()
        logger.info(f'Collector Server escuchando en {addr}')
        
        # Iniciar el monitor de timeouts en paralelo
        loop.create_task(self.monitor_timeouts())

        while True:
            conn, addr = await loop.sock_accept(server_socket) # acepta las conexiones de los Agentes de manera asíncrona
            
            # ejecuta la funcion handle_agent en paralelo para cada agente que se conecta
            loop.create_task(self.handle_agent(conn, addr))


def main():
    # permitimos algunos argumentos como elegir puerto del collector, indicar el puerto del Master y el de Redis
    parser = argparse.ArgumentParser(description="Servidor Collector para métricas de workers.")
    parser.add_argument('--port', type=int, default=6000, help='Puerto para escuchar a los agentes.')
    parser.add_argument('--master-host', default='localhost', help='Host del Master Server.')
    parser.add_argument('--master-port', type=int, default=5000, help='Puerto del Master Server.')
    parser.add_argument('--redis-host', default='localhost', help='Host de Redis.')
    parser.add_argument('--redis-port', type=int, default=6379, help='Puerto de Redis.')
    args = parser.parse_args()

    # iniciamos el servidor usando los argumentos de la línea de comandos
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