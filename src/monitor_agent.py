import asyncio
import json
import time
import psutil
import socket
import argparse
import os

from utils.logger import setup_logger

logger = setup_logger('monitor_agent', f'{os.getenv("LOG_DIR", "/app/logs")}/monitor_agent.log')

class MonitorAgent:
    def __init__(self, worker_id: str, collector_host: str, collector_port: int, ipc_socket_path: str):
        self.worker_id = worker_id
        self.collector_host = collector_host
        self.collector_port = collector_port
        self.ipc_socket_path = ipc_socket_path
        self.last_heartbeat = time.time()
        self.status = "ALIVE"     # el estado por defecto es "ALIVE"
        
        socket_dir = os.path.dirname(self.ipc_socket_path)
        if not os.path.exists(socket_dir):
            os.makedirs(socket_dir)


        # Escucha heartbeats del worker via Unix socket
    async def listen_ipc_heartbeat(self):
        if os.path.exists(self.ipc_socket_path):
            os.remove(self.ipc_socket_path)

        #  Socket UNIX
        server_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        
        # Se asocia al path
        server_socket.bind(self.ipc_socket_path)
        server_socket.listen()   # escucha, no envia 
        server_socket.setblocking(False)  # no bloqueante   (espera en segundo plano)


# El event loop es basicamente el Scheduler de asyncio
# Por lo que se encarga de la gestion y ejecución de las tareas asíncronas. 
        loop = asyncio.get_running_loop()    
        logger.info(f"Agente {self.worker_id} escuchando en socket IPC (bajo nivel): {self.ipc_socket_path}")

        # Bucle para aceptar conexiones de forma asíncrona
        while True:
            try:
                conn, addr = await loop.sock_accept(server_socket)    # espera a que inicie la conexion
                logger.debug(f"Nueva conexión de heartbeat recibida en {self.ipc_socket_path}")
                # Crear una tarea usando el loop de asyncio, usando el handler que definimos abajo
                loop.create_task(self.handle_worker_heartbeat(conn))
            except Exception as e:
                logger.error(f"Error aceptando conexión en socket IPC: {e}")


    # Recibe heartbeat del worker desde una conexión de socket UNIX
    async def handle_worker_heartbeat(self, conn: socket.socket):
        loop = asyncio.get_running_loop()  # definimos al Scheduler
        try:
            # Leer del socket de forma asíncrona
            data = await loop.sock_recv(conn, 1024)
            if not data:
                return

            message = json.loads(data.decode())
            if message.get('type') == 'heartbeat':
                self.last_heartbeat = time.time()
                if self.status == "DEAD":  # llega un heartbeat a uno que estaba DEAD, entonces ahora está ALIVE
                    logger.info(f"Worker {self.worker_id} se ha recuperado (estaba DEAD). Nuevo status: ALIVE")
                self.status = "ALIVE"   # cambia el estado a ALIVE
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Error procesando mensaje de heartbeat: {e}")
        finally:
            conn.close()  # cierra la conexion con el socket del worker


    # Recolecta métricas del sistema y las reporta al Collector.
    async def collect_and_report_metrics(self):
        while True:
            await asyncio.sleep(10)  # reporta cada 10 seg

            if time.time() - self.last_heartbeat > 15 and self.status == "ALIVE":
                logger.warning(f"Worker {self.worker_id} no ha enviado heartbeat en 15s. Status: DEAD")
                self.status = "DEAD"

            # msj json siguiendo el protocolo
            metrics = {
                'worker_id': self.worker_id,
                'timestamp': time.time(),
                'status': self.status,
                'cpu_percent': psutil.cpu_percent(interval=1),
                'memory_percent': psutil.virtual_memory().percent
            }

            await self.send_to_collector(metrics)  


        # Envía métricas al Collector via TCP
    async def send_to_collector(self, metrics: dict):
        loop = asyncio.get_running_loop()   # definimos al Scheduler
        client_socket = None
        try:
            # IPv4 TCP
            client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client_socket.setblocking(False)

            # Conectamos los sockets de forma asíncrona
            await loop.sock_connect(client_socket, (self.collector_host, self.collector_port))
            
            message = {
                'type': 'metrics',
                'data': metrics
            }
            
            # Enviamos datos de forma asíncrona
            await loop.sock_sendall(client_socket, json.dumps(message).encode())
            
            logger.info(f"Métricas de {self.worker_id} enviadas al Collector.")

        except ConnectionRefusedError:
            logger.error(f"Error enviando al Collector: Conexión rechazada. ¿Está el Collector corriendo en {self.collector_host}:{self.collector_port}?")
        except Exception as e:
            logger.error(f"Error inesperado enviando al Collector: {e}")
        finally:
            if client_socket:   # si hay una conexión abierta, la cerramos
                client_socket.close()


        # levanta el agente.
    async def run(self):
        logger.info(f"Iniciando agente para worker: {self.worker_id}")
        
        # .gather es para ejecutar varias tareas al mismo tiempo, dentro del mismo awaits
        await asyncio.gather(
            self.listen_ipc_heartbeat(),
            self.collect_and_report_metrics()
        )


def main():

    # permitimos parsear argumentos como elegir puerto y path del socket, a que worker monitorear, etc
    parser = argparse.ArgumentParser(description="Agente de Monitoreo para un Worker.")
    parser.add_argument('--worker-id', required=True, help='ID único del worker a monitorear.')
    parser.add_argument('--collector-host', default='localhost', help='Host del Collector Server.')
    parser.add_argument('--collector-port', type=int, default=6000, help='Puerto del Collector Server.')
    parser.add_argument('--ipc-socket-path', help='Ruta al Unix Domain Socket para IPC.')
    args = parser.parse_args()

    # generamos el path del socket dentro de /tmp para que sea temporal y se borra al apagar el container
    ipc_socket_path = args.ipc_socket_path or f"/tmp/worker_{args.worker_id}.sock"    

    agent = MonitorAgent(
        worker_id=args.worker_id,
        collector_host=args.collector_host,
        collector_port=args.collector_port,
        ipc_socket_path=ipc_socket_path
    )
    
    try:
        asyncio.run(agent.run())   # iniciamos el agente
    except KeyboardInterrupt:  # ctrl+c
        logger.info(f"\nAgente {args.worker_id} detenido.")
    finally:  # borramos el socket una vez muerto el agente
        if os.path.exists(ipc_socket_path):
            os.remove(ipc_socket_path)

if __name__ == "__main__":
    main()