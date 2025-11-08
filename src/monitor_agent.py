import asyncio
import json
import time
import psutil
import socket
import argparse
import os

from src.utils.logger import setup_logger

logger = setup_logger('monitor_agent')

class MonitorAgent:
    def __init__(self, worker_id: str, collector_host: str, collector_port: int, ipc_socket_path: str):
        self.worker_id = worker_id
        self.collector_host = collector_host
        self.collector_port = collector_port
        self.ipc_socket_path = ipc_socket_path
        self.last_heartbeat = time.time()
        self.status = "ALIVE"
        
        socket_dir = os.path.dirname(self.ipc_socket_path)
        if not os.path.exists(socket_dir):
            os.makedirs(socket_dir)

    async def listen_ipc_heartbeat(self):
        """Escucha heartbeats del worker via Unix socket."""
        if os.path.exists(self.ipc_socket_path):
            os.remove(self.ipc_socket_path)
            
        server = await asyncio.start_unix_server(
            self.handle_worker_heartbeat,
            path=self.ipc_socket_path
        )
        logger.info(f"Agente {self.worker_id} escuchando en socket IPC: {self.ipc_socket_path}")
        async with server:
            await server.serve_forever()

    async def handle_worker_heartbeat(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Recibe heartbeat del worker."""
        data = await reader.read(1024)
        if not data:
            writer.close()
            await writer.wait_closed()
            return

        try:
            message = json.loads(data.decode())
            if message.get('type') == 'heartbeat':
                self.last_heartbeat = time.time()
                if self.status == "DEAD":
                    logger.info(f"Worker {self.worker_id} ha vuelto. Status: ALIVE")
                self.status = "ALIVE"
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Error procesando mensaje de heartbeat: {e}")
        finally:
            writer.close()
            await writer.wait_closed()

    async def collect_and_report_metrics(self):
        """Recolecta métricas del sistema y las reporta al Collector."""
        while True:
            await asyncio.sleep(10)

            if time.time() - self.last_heartbeat > 15 and self.status == "ALIVE":
                logger.warning(f"Worker {self.worker_id} no ha enviado heartbeat en 15s. Status: DEAD")
                self.status = "DEAD"

            metrics = {
                'worker_id': self.worker_id,
                'timestamp': time.time(),
                'status': self.status,
                'cpu_percent': psutil.cpu_percent(interval=1),
                'memory_percent': psutil.virtual_memory().percent
            }

            await self.send_to_collector(metrics)

    async def send_to_collector(self, metrics: dict):
        """Envía métricas al Collector via TCP."""
        writer = None
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
            
            logger.info(f"Métricas de {self.worker_id} enviadas al Collector.")

        except ConnectionRefusedError:
            logger.error(f"Error enviando al Collector: Conexión rechazada. ¿Está el Collector corriendo en {self.collector_host}:{self.collector_port}?")
        except Exception as e:
            logger.error(f"Error inesperado enviando al Collector: {e}")
        finally:
            if writer and not writer.is_closing():
                writer.close()
                await writer.wait_closed()

    async def run(self):
        """Inicia el agente."""
        logger.info(f"Iniciando agente para worker: {self.worker_id}")
        await asyncio.gather(
            self.listen_ipc_heartbeat(),
            self.collect_and_report_metrics()
        )

def main():
    parser = argparse.ArgumentParser(description="Agente de Monitoreo para un Worker.")
    parser.add_argument('--worker-id', required=True, help='ID único del worker a monitorear.')
    parser.add_argument('--collector-host', default='localhost', help='Host del Collector Server.')
    parser.add_argument('--collector-port', type=int, default=6000, help='Puerto del Collector Server.')
    parser.add_argument('--ipc-socket-path', help='Ruta al Unix Domain Socket para IPC.')
    args = parser.parse_args()

    ipc_socket_path = args.ipc_socket_path or f"/tmp/worker_{args.worker_id}.sock"

    agent = MonitorAgent(
        worker_id=args.worker_id,
        collector_host=args.collector_host,
        collector_port=args.collector_port,
        ipc_socket_path=ipc_socket_path
    )
    
    try:
        asyncio.run(agent.run())
    except KeyboardInterrupt:
        logger.info(f"\nAgente {args.worker_id} detenido.")
    finally:
        if os.path.exists(ipc_socket_path):
            os.remove(ipc_socket_path)

if __name__ == "__main__":
    main()
