import argparse
import socket
import json
import os
import uuid
import base64
import struct # Añadido para el protocolo de encabezado
from typing import Dict, Any

# Importar configuración
from src.config.settings import MASTER_HOST, MASTER_PORT

# Importar logger (opcional para un cliente CLI simple, pero buena práctica)
from src.utils.logger import setup_logger
logger = setup_logger('submit_job_client', f"{os.getenv('LOG_DIR', 'logs')}/submit_job_client.log")


def submit_job(server_host: str, server_port: int, file_path: str, pattern: str):
    """
    Envía un nuevo trabajo de análisis al Master Server.
    Ahora solo envía metadatos, no el contenido del archivo.
    """
    job_id = str(uuid.uuid4())
    logger.info(f"Enviando trabajo {job_id} al Master Server...", 
                extra={'job_id': job_id, 'server': f'{server_host}:{server_port}'})

    # El mensaje ahora solo contiene metadatos
    message = {
        'type': 'submit_job',
        'job_id': job_id,
        'file_path': file_path, # La ruta relativa que el master puede ver
        'pattern': pattern
    }

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect((server_host, server_port))
            
            # Enviar petición con protocolo de encabezado
            json_data = json.dumps(message).encode('utf-8')
            header = struct.pack('!I', len(json_data))
            sock.sendall(header)
            sock.sendall(json_data)
            
            # Leer la respuesta del servidor usando el protocolo de encabezado
            header_data = sock.recv(4)
            if not header_data:
                raise ConnectionError("El servidor cerró la conexión sin enviar una respuesta.")
            
            response_length = struct.unpack('!I', header_data)[0]
            
            response_body = b''
            while len(response_body) < response_length:
                packet = sock.recv(response_length - len(response_body))
                if not packet:
                    raise ConnectionError("Conexión perdida mientras se recibía la respuesta.")
                response_body += packet
            
            response = json.loads(response_body.decode('utf-8'))
            
            logger.info(f"Respuesta del Master Server: {response}", extra={'response': response})
            return response

    except Exception as e:
        logger.error(f"Ocurrió un error inesperado: {e}", exc_info=True)
        return None

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cliente para enviar trabajos de análisis genómico al Master Server.")
    parser.add_argument('--server', type=str, default=MASTER_HOST, help='Dirección IP o hostname del Master Server.')
    parser.add_argument('--port', type=int, default=MASTER_PORT, help='Puerto del Master Server.')
    parser.add_argument('--file', type=str, required=True, help='Ruta al archivo de genoma a analizar.')
    parser.add_argument('--pattern', type=str, required=True, help='Patrón de ADN a buscar (ej: AGGTCCAT).')
    
    args = parser.parse_args()

    response = submit_job(args.server, args.port, args.file, args.pattern)

    if response and response.get("status") == "accepted":
        print(f"Job submitted successfully!")
        print(f"Job ID: {response.get('job_id')}")
        print(f"Message: {response.get('message')}")
    elif response:
        print(f"Error submitting job: {response.get('message', 'Unknown error')}")
    else:
        print("Error submitting job: No response from server. Check client logs for details.")
        print(f"Client log file: local_logs/submit_job_client.log")
