import asyncio
import json
import time
import argparse
import redis
from collections import defaultdict

from src.utils.logger import setup_logger

logger = setup_logger('collector_server')

class CollectorServer:
    def __init__(self, port: int, master_host: str, master_port: int, redis_host: str, redis_port: int):
        self.port = port
        self.master_host = master_host
        self.master_port = master_port
        self.redis_client = redis.Redis(host=redis_host, port=redis_port, decode_responses=True)
        self.worker_states = defaultdict(dict)

    async def handle_agent(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Recibe métricas de un agente."""
        addr = writer.get_extra_info('peername')
        logger.info(f"Conexión recibida de {addr}")
        try:
            data = await reader.read(4096)
            message = json.loads(data.decode())
            
            if message.get('type') == 'metrics':
                await self.process_metrics(message['data'])
            else:
                logger.warning(f"Mensaje de tipo desconocido recibido: {message.get('type')}")

        except json.JSONDecodeError:
            logger.error("Error decodificando JSON del agente.")
        except Exception as e:
            logger.error(f"Error procesando mensaje del agente: {e}")
        finally:
            logger.info(f"Cerrando conexión con {addr}")
            writer.close()
            await writer.wait_closed()

    async def process_metrics(self, metrics: dict):
        """Procesa métricas recibidas y detecta anomalías."""
        worker_id = metrics.get('worker_id')
        if not worker_id:
            logger.warning("Métrica recibida sin worker_id")
            return

        logger.info(f"Métrica recibida de {worker_id}: CPU {metrics.get('cpu_percent'):.2f}%, MEM {metrics.get('memory_percent'):.2f}%")

        self.worker_states[worker_id] = {
            'last_update': time.time(),
            'metrics': metrics
        }
        
        self.redis_client.setex(
            f'worker:{worker_id}:metrics',
            60,
            json.dumps(metrics)
        )
        
        await self.check_anomalies(worker_id, metrics)

    async def check_anomalies(self, worker_id: str, metrics: dict):
        """Detecta si hay anomalías en las métricas."""
        if metrics.get('status') == 'DEAD':
            alert = {
                'severity': 'CRITICAL',
                'worker_id': worker_id,
                'message': f'Worker {worker_id} ha dejado de responder (reportado como DEAD por su agente)',
                'timestamp': time.time()
            }
            await self.send_alert(alert)
            await self.notify_master(alert)

    async def send_alert(self, alert: dict):
        """Loggea la alerta."""
        log_method = logger.critical if alert['severity'] == 'CRITICAL' else logger.warning
        log_method(alert['message'], extra=alert)
        # Aquí se podría extender para enviar emails, etc.

    async def notify_master(self, alert: dict):
        """Notifica al Master sobre una alerta crítica."""
        if alert['severity'] != 'CRITICAL':
            return

        logger.info(f"Notificando al Master sobre la alerta de {alert['worker_id']}")
        writer = None
        try:
            reader, writer = await asyncio.open_connection(self.master_host, self.master_port)
            
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
            if writer and not writer.is_closing():
                writer.close()
                await writer.wait_closed()

    async def monitor_timeouts(self):
        """Verifica si algún worker ha dejado de reportar métricas."""
        while True:
            await asyncio.sleep(10)
            current_time = time.time()
            
            for worker_id, state in list(self.worker_states.items()):
                # Solo alertar una vez
                if 'alerted_timeout' not in state and (current_time - state.get('last_update', 0) > 30):
                    alert = {
                        'severity': 'CRITICAL',
                        'worker_id': worker_id,
                        'message': f'Worker {worker_id} no reporta métricas hace más de 30 segundos (timeout).',
                        'timestamp': current_time
                    }
                    self.worker_states[worker_id]['alerted_timeout'] = True
                    await self.send_alert(alert)
                    await self.notify_master(alert)

    async def run(self):
        """Inicia el servidor collector."""
        server = await asyncio.start_server(
            self.handle_agent,
            '0.0.0.0',
            self.port
        )
        
        addr = server.sockets[0].getsockname()
        logger.info(f'Collector Server escuchando en {addr}')
        
        async with server:
            await asyncio.gather(
                server.serve_forever(),
                self.monitor_timeouts()
            )

def main():
    parser = argparse.ArgumentParser(description="Servidor Collector para métricas de workers.")
    parser.add_argument('--port', type=int, default=6000, help='Puerto para escuchar a los agentes.')
    parser.add_argument('--master-host', default='localhost', help='Host del Master Server.')
    parser.add_argument('--master-port', type=int, default=5000, help='Puerto del Master Server.')
    parser.add_argument('--redis-host', default='localhost', help='Host de Redis.')
    parser.add_argument('--redis-port', type=int, default=6379, help='Puerto de Redis.')
    args = parser.parse_args()

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
