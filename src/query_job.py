import argparse
import socket
import json
import os
from typing import Dict, Any

# Importar configuración
from src.config.settings import MASTER_HOST, MASTER_PORT

# Importar logger (opcional para un cliente CLI simple, pero buena práctica)
from src.utils.logger import setup_logger
logger = setup_logger('query_job_client', f'{os.getenv('LOG_DIR', '/app/logs')}/query_job_client.log')


def query_job_status(server_host: str, server_port: int, job_id: str) -> Dict[str, Any]:
    """
    Consulta el estado de un trabajo al Master Server.

    Args:
        server_host: Dirección IP o hostname del Master Server.
        server_port: Puerto del Master Server.
        job_id: ID del trabajo a consultar.

    Returns:
        Un diccionario con la respuesta del servidor.
    """
    message = {
        "type": "query_status",
        "job_id": job_id
    }

    logger.info(f"Consultando estado del job {job_id} al Master Server...", extra={'job_id': job_id, 'server': f'{server_host}:{server_port}'})

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect((server_host, server_port))
            sock.sendall(json.dumps(message).encode('utf-8'))
            
            response_data = sock.recv(4096) # Leer la respuesta del servidor
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
    parser = argparse.ArgumentParser(description="Cliente para consultar el estado de un trabajo de análisis genómico.")
    parser.add_argument('--server', type=str, default=MASTER_HOST, help='Dirección IP o hostname del Master Server.')
    parser.add_argument('--port', type=int, default=MASTER_PORT, help='Puerto del Master Server.')
    parser.add_argument('--job-id', type=str, required=True, help='ID del trabajo a consultar.')
    parser.add_argument('--show-results', action='store_true', help='Muestra los resultados finales si el trabajo está completado.')
    
    args = parser.parse_args()

    response = query_job_status(args.server, args.port, args.job_id)

    if response.get("status") == "error":
        print(f"Error al consultar el estado del job: {response.get('message', 'Unknown error')}")
    else:
        print(f"Job ID: {response.get('job_id')}")
        print(f"Status: {response.get('status', 'N/A').upper()}")
        
        progress = response.get('progress', {})
        total_chunks = progress.get('total_chunks', 0)
        processed_chunks = progress.get('processed_chunks', 0)
        percentage = progress.get('percentage', 0.0)
        
        print(f"Progreso: {processed_chunks}/{total_chunks} chunks procesados ({percentage:.2f}%) ")
        
        partial_results = response.get('partial_results', {})
        matches_found = partial_results.get('matches_found', 0)
        print(f"Coincidencias encontradas hasta ahora: {matches_found}")

        if args.show_results and response.get("status") == "completed":
            # Aquí se podría añadir lógica para recuperar y mostrar los resultados completos
            # si el Master Server los almacenara de forma accesible o los devolviera en la respuesta.
            # Por ahora, el Master solo devuelve el conteo total de matches.
            print("\n--- Resultados Finales ---")
            print(f"Total de coincidencias: {matches_found}")
            print("Nota: La implementación actual del Master Server solo devuelve el conteo total de coincidencias.")
            print("Para ver las posiciones exactas, se necesitaría una lógica adicional en el Master y en este cliente.")
