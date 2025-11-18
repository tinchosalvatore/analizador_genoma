import argparse
import socket
import json
import os
import uuid
import base64
from typing import Dict, Any

# Importar configuración
from src.config.settings import MASTER_HOST, MASTER_PORT, DEFAULT_CHUNK_SIZE

from src.utils.logger import setup_logger

logger = setup_logger('submit_job_client', f'{os.getenv("LOG_DIR", "/app/logs")}/submit_job_client.log')


def submit_job(server_host: str, server_port: int, file_path: str, pattern: str) -> Dict[str, Any]:
    """
    Envía un trabajo de análisis genómico al Master Server.

    Args:
        server_host: Dirección IP o hostname del Master Server.
        server_port: Puerto del Master Server.
        file_path: Ruta al archivo de genoma a analizar.
        pattern: Patrón de ADN a buscar.
        chunk_size: Tamaño de los chunks para dividir el archivo.

    Returns:
        Un diccionario con la respuesta del servidor.
    """
    if not os.path.exists(file_path):
        logger.error(f"El archivo no existe: {file_path}")
        return {"status": "error", "message": f"El archivo no existe: {file_path}"}
    
    if not os.path.isfile(file_path):
        logger.error(f"La ruta especificada no es un archivo: {file_path}")
        return {"status": "error", "message": f"La ruta especificada no es un archivo: {file_path}"}

    try:
        # Validar tamaño del archivo antes de leerlo
        MAX_FILE_SIZE = 501 * 1024 * 1024  # 500MB
        file_size_on_disk = os.path.getsize(file_path)
        
        if file_size_on_disk > MAX_FILE_SIZE:
            error_msg = f"Archivo demasiado grande: {file_size_on_disk/(1024*1024):.2f}MB. Máximo permitido: {MAX_FILE_SIZE/(1024*1024):.0f}MB"
            logger.error(error_msg, extra={'file_path': file_path, 'file_size': file_size_on_disk})
            return {
                "status": "error",
                "message": error_msg
            }
        
        with open(file_path, 'rb') as f:
            file_data = f.read()
        
        file_data_b64 = base64.b64encode(file_data).decode('utf-8')
        file_size = len(file_data)

        job_id = str(uuid.uuid4()) # Generar un UUID único para el trabajo

        message = {
            "type": "submit_job",
            "job_id": job_id,
            "filename": os.path.basename(file_path),
            "pattern": pattern,
            "chunk_size": DEFAULT_CHUNK_SIZE,
            "file_size": file_size,
            "file_data_b64": file_data_b64
        }

        logger.info(f"Enviando trabajo {job_id} al Master Server...", extra={'job_id': job_id, 'server': f'{server_host}:{server_port}'})

        # Obtener todas las direcciones posibles (IPv4 e IPv6)
        addrs = socket.getaddrinfo(server_host, server_port, socket.AF_UNSPEC, socket.SOCK_STREAM)
        
        sock = None
        for family, socktype, proto, canonname, sockaddr in addrs:
            try:
                sock = socket.socket(family, socktype, proto)
                sock.connect(sockaddr)
                logger.info(f"Conectado a Master Server en {sockaddr} usando {family}", extra={'job_id': job_id, 'sockaddr': sockaddr, 'family': family})
                break # Conexión exitosa
            except OSError as e:
                logger.warning(f"Fallo al conectar a {sockaddr}: {e}")
                if sock:
                    sock.close()
                sock = None
        
        if sock is None:
            logger.error(f"No se pudo conectar a {server_host}:{server_port} en ninguna dirección disponible.")
            return {"status": "error", "message": "No se pudo conectar al Master Server."}

        with sock: # Usar el socket conectado
            # enviamos todos los datos
            sock.sendall(json.dumps(message).encode('utf-8'))
            
            # Notificamos al servidor que terminamos de enviar datos, para que sepa que debe dejar de leer y empezar a procesar.
            sock.shutdown(socket.SHUT_WR)

            response_data = sock.recv(4096) # Leer la respuesta del servidor
            
            if not response_data:
                logger.error("El servidor cerró la conexión sin enviar respuesta.")
                return {"status": "error", "message": "Sin respuesta del servidor."}
            

            response = json.loads(response_data.decode('utf-8'))
            
            logger.info(f"Respuesta del Master Server para job {job_id}: {response}", extra={'job_id': job_id, 'response': response})
            return response

    except ConnectionRefusedError:
        logger.error(f"Conexión rechazada. Asegúrate de que el Master Server esté corriendo en {server_host}:{server_port}.")
        return {"status": "error", "message": "Conexión rechazada. Master Server no disponible."}
    except json.JSONDecodeError:
        logger.error("Error al decodificar la respuesta JSON del servidor.")
        return {"status": "error", "message": "Respuesta inválida del servidor."}
    except Exception as e:
        logger.error(f"Ocurrió un error inesperado: {e}", exc_info=True)
        return {"status": "error", "message": f"Error inesperado: {e}"}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cliente para enviar trabajos de análisis genómico al Master Server.")
    parser.add_argument('--server', type=str, default=MASTER_HOST, help='Dirección IP o hostname del Master Server.')
    parser.add_argument('--port', type=int, default=MASTER_PORT, help='Puerto del Master Server.')
    parser.add_argument('--file', type=str, required=True, help='Ruta al archivo de genoma a analizar.')
    parser.add_argument('--pattern', type=str, required=True, help='Patrón de ADN a buscar (ej: AGGTCCAT).')

    
    args = parser.parse_args()

    response = submit_job(args.server, args.port, args.file, args.pattern)

    if response.get("status") == "accepted":
        print(f"Job submitted successfully!")
        print(f"Job ID: {response.get('job_id')}")
        print(f"Total chunks: {response.get('total_chunks')}")
        print(f"Estimated time: {response.get('estimated_time')} seconds")
    else:
        print(f"Error submitting job: {response.get('message', 'Unknown error')}")
