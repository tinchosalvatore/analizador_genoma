import argparse
import socket
import json
import os
import uuid
import base64
from typing import Dict, Any

# Importar configuración
from src.config.settings import MASTER_HOST, MASTER_PORT, DEFAULT_CHUNK_SIZE, MAX_FILE_SIZE
from src.utils.logger import setup_logger

#   nombre y ruta destino del logger
logger = setup_logger('submit_job_client', f'{os.getenv("LOG_DIR", "/app/logs")}/submit_job_client.log') 


def submit_job(server_host: str, server_port: int, file_path: str, pattern: str, ip_family: str | None = None) -> Dict[str, Any]:
    """
    Envía un trabajo de análisis genómico al Master Server.

    Args:
        server_host: Dirección IP o hostname del Master Server.
        server_port: Puerto del Master Server.
        file_path: Ruta al archivo de genoma a analizar.
        pattern: Patrón de ADN a buscar.
        ip_family: 'ipv4' o 'ipv6' para forzar una familia de IP, o None para permitir cualquiera.

    Returns:
        Un diccionario con la respuesta del servidor.
    """

    # dos verificaciones de la integridad del archivo de genoma 
    if not os.path.exists(file_path):
        logger.error(f"El archivo no existe: {file_path}")
        return {"status": "error", "message": f"El archivo no existe: {file_path}"}
    if not os.path.isfile(file_path):
        logger.error(f"La ruta especificada no es un archivo: {file_path}")
        return {"status": "error", "message": f"La ruta especificada no es un archivo: {file_path}"}

    try:
        # Validar tamaño del archivo antes de leerlo
        max_size = MAX_FILE_SIZE
        file_size = os.path.getsize(file_path)
        
        if file_size > max_size:
            error_msg = f"Archivo demasiado grande: {file_size/(1024*1024):.2f}MB. Máximo permitido: {max_size/(1024*1024):.0f}MB"
            logger.error(error_msg, extra={'file_path': file_path, 'file_size': file_size})
            return {
                "status": "error",
                "message": error_msg
            }
        
        # rb es read binary
        with open(file_path, 'rb') as f:    
            file_data = f.read()
        
        file_data_b64 = base64.b64encode(file_data).decode('utf-8')  # Codificar en Base64  (binario a ASCII)

        job_id = str(uuid.uuid4()) # Generar un Identificador Unico Universal para el trabajo

        message = {
            "type": "submit_job",
            "job_id": job_id,
            "filename": os.path.basename(file_path), # basename obtiene el nombre del archivo
            "pattern": pattern,
            "chunk_size": DEFAULT_CHUNK_SIZE,
            "file_size": file_size,
            "file_data_b64": file_data_b64
        }

        logger.info(f"Enviando trabajo {job_id} al Master Server...", extra={'job_id': job_id, 'server': f'{server_host}:{server_port}'})

        # Determinar la familia de IP a utilizar con argparse (si es Nonen, hace el UNSPEC)
        family_to_use = socket.AF_UNSPEC   # en mi caso detecta tanto IPv4 como IPv6 y termina usando IPv4
        if ip_family == 'ipv4':
            family_to_use = socket.AF_INET
        elif ip_family == 'ipv6':
            family_to_use = socket.AF_INET6
        
        ip_family_str = ip_family.upper() if ip_family else 'La que se detecte con UNSPEC' # para los logs
        logger.info(f"Resolviendo host {server_host} con familia de socket forzada a: {ip_family_str}")


# obtenemos datos clave sobre el socket al que nos vamos a conectar (el Master Server)
        addrs = socket.getaddrinfo(server_host, server_port, family_to_use, socket.SOCK_STREAM)


# variable que va a tomar valor solo si hay una conexion (la usamos para saber si se conecto correctamente)
        sock = None  

        for family, socktype, proto, canonname, sockaddr in addrs:
            try:
                sock = socket.socket(family, socktype, proto)
                sock.connect(sockaddr)
                logger.info(f"Conectado a Master Server en {sockaddr} usando {family}", extra={'job_id': job_id, 'sockaddr': sockaddr, 'family': str(family)})
                break # se rompe con la priemr conexión exitosa
            except OSError as e:
                logger.warning(f"Fallo al conectar a {sockaddr}: {e}")
                if sock:
                    sock.close()
                sock = None
        
        # si el socket es none, es porque fallo la conexion
        if sock is None:
            error_message = f"No se pudo conectar a {server_host}:{server_port} en ninguna dirección disponible (familia forzada: {ip_family_str})."
            logger.error(error_message)
            return {"status": "error", "message": error_message}

        with sock:
            sock.sendall(json.dumps(message).encode('utf-8'))
            sock.shutdown(socket.SHUT_WR)  # indicador para saber que se mando toda la informacion
            response_data = sock.recv(4096)   # es TCP asi que esperamos la respuesta del Master Server 
            
            if not response_data:
                logger.error("El servidor Master cerró la conexión sin enviar respuesta.")
                return {"status": "error", "message": "Sin respuesta del servidor."}

            # decodificamos y devolvemos la response del Master Server
            response = json.loads(response_data.decode('utf-8')) 
            logger.info(f"Respuesta del Master Server para job {job_id}: {response}", extra={'job_id': job_id, 'response': response})
            return response

    # multiples excepciones
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
    parser.add_argument('--ip-family', type=str, choices=['ipv4', 'ipv6'], help='Forzar el uso de una familia de IP específica (ipv4 o ipv6).')

    args = parser.parse_args()

    response = submit_job(args.server, args.port, args.file, args.pattern, ip_family=args.ip_family)

    # si lo acepto, imprime por terminal el response para que el cliente este al tanto
    if response.get("status") == "accepted":
        print("Job submitted successfully!")
        print(f"Job ID: {response.get('job_id')}")
        print(f"Total chunks: {response.get('total_chunks')}")
        print(f"Estimated time: {response.get('estimated_time')} seconds")
    else:
        print(f"Error submitting job: {response.get('message', 'Unknown error')}")