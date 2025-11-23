import argparse
import socket
import json
import os
from pathlib import Path
from typing import Dict, Any

# Importar configuración
from src.config.settings import MASTER_HOST, MASTER_PORT

# configurar el logger
from src.utils.logger import setup_logger
logger = setup_logger('query_job_client', f'{os.getenv("LOG_DIR", "/app/logs")}/query_job_client.log')


def query_job_status(server_host: str, server_port: int, job_id: str, ip_family: str | None = None) -> Dict[str, Any]:
    """
    Consulta el estado de un trabajo al Master Server.

    Args:
        server_host: Dirección IP o hostname del Master Server.
        server_port: Puerto del Master Server.
        job_id: ID del trabajo a consultar.

    Returns:
        Un diccionario con la respuesta que envio el servidor.
    """
    message = {
        "type": "query_status",  # para que el protocolo lo revise
        "job_id": job_id
    }

    logger.info(f"Consultando estado del job {job_id} al Master Server...", extra={'job_id': job_id, 'server': f'{server_host}:{server_port}'})

    try:
        # Determinar la familia de IP a utilizar con argparse (si es None, hace el UNSPEC)
        family_to_use = socket.AF_UNSPEC
        if ip_family == 'ipv4':
            family_to_use = socket.AF_INET
        elif ip_family == 'ipv6':
            family_to_use = socket.AF_INET6
        
        ip_family_str = ip_family.upper() if ip_family else 'La que se detecte con UNSPEC' # para los logs
        logger.info(f"Resolviendo host {server_host} con familia de socket forzada a: {ip_family_str}")


    # obtenemos datos clave sobre el socket al que nos vamos a conectar (el Master Server)
        addrs = socket.getaddrinfo(server_host, server_port, family_to_use, socket.SOCK_STREAM)
        
        sock = None  # si se mantiene None al final es porque fallo la conexion
        for family, socktype, proto, canonname, sockaddr in addrs:
            try:
                sock = socket.socket(family, socktype, proto)
                sock.connect(sockaddr)
                logger.info(f"Conectado a Master Server en {sockaddr} usando {family}", extra={'job_id': job_id, 'sockaddr': sockaddr, 'family': family})
                break # se rompe junto a la primer conexion exitosa
            except OSError as e:
                logger.warning(f"Fallo al conectar a {sockaddr}: {e}")
                if sock:
                    sock.close()
                sock = None
        
        # fallo la conexion
        if sock is None:
            logger.error(f"No se pudo conectar a {server_host}:{server_port} en ninguna dirección disponible.")
            return {"status": "error", "message": "No se pudo conectar al Master Server."}

        with sock: # Usar el socket conectado
            sock.sendall(json.dumps(message).encode('utf-8'))   # envia la peticion de estado de tarea usando el job_id
            
            # Señalizamos que hemos terminado de enviar la petición
            sock.shutdown(socket.SHUT_WR)

            # Para mas robustez, leemos toda la respuesta hasta que el servidor cierre
            response_chunks = []
            while True:
                chunk = sock.recv(4096) 
                if not chunk:
                    break
                response_chunks.append(chunk)


            response_data = b"".join(response_chunks) # leemos la respuesta del chunk de rta completo del servidor

            if not response_data:
                logger.error(f"El servidor cerró la conexión sin enviar respuesta.", extra={'job_id': job_id})
                return {"status": "error", "message": "El servidor cerró la conexión sin enviar respuesta."}

            # decodificamos y devolvemos la respuesta del master
            response = json.loads(response_data.decode('utf-8'))  
            logger.info(f"Respuesta del Master Server para job {job_id}: {response}", extra={'job_id': job_id, 'response': response})
            return response

    # Manejo de errores de conexión
    except ConnectionRefusedError:
        logger.error(f"Conexión rechazada. Asegúrate de que el Master Server esté corriendo en {server_host}:{server_port}.")
        return {"status": "error", "message": "Conexión rechazada. Master Server no disponible."}
    except json.JSONDecodeError:
        logger.error("Error al decodificar la respuesta JSON del servidor.")
        return {"status": "error", "message": "Respuesta inválida del servidor."}
    except Exception as e:
        logger.error(f"Ocurrió un error inesperado: {e}", exc_info=True)
        return {"status": "error", "message": f"Error inesperado: {e}"}


# <=================  GENERACION HTML con CSS  =================>

def generate_html_report(job_id: str, response: Dict[str, Any]) -> str:
    status = response.get('status', 'N/A').upper()
    progress = response.get('progress', {})
    total_chunks = progress.get('total_chunks', 0)
    processed_chunks = progress.get('processed_chunks', 0)
    percentage = progress.get('percentage', 0.0)
    matches_found = response.get('partial_results', {}).get('matches_found', 0)

    # Determine status icon and color
    status_icon = ""
    status_color = ""
    if status == "COMPLETED":
        status_icon = "✅"
        status_color = "green"
    elif status == "QUEUING":
        status_icon = "⏳"
        status_color = "orange"
    elif status == "PROCESSING":
        status_icon = "🔄"
        status_color = "blue"
    elif status == "FAILED":
        status_icon = "❌"
        status_color = "red"
    else:
        status_icon = "❓"
        status_color = "gray"

    html_content = f"""
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Reporte de Estado del Job: {job_id}</title>
    <style>
        body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 20px; background-color: #f4f7f6; color: #333; }}
        .container {{ max-width: 800px; margin: auto; background: #fff; padding: 30px; border-radius: 10px; box-shadow: 0 4px 8px rgba(0,0,0,0.1); }}
        h1 {{ color: #0056b3; text-align: center; margin-bottom: 25px; }}
        .job-id {{ font-size: 1.2em; font-weight: bold; color: #555; margin-bottom: 20px; text-align: center; }}
        .status-section {{ background-color: #e9ecef; padding: 15px; border-radius: 8px; margin-bottom: 20px; border-left: 5px solid {status_color}; }}
        .status-section p {{ margin: 5px 0; font-size: 1.1em; }}
        .status-section .status-value {{ font-weight: bold; color: {status_color}; }}
        .progress-bar-container {{ width: 100%; background-color: #e0e0e0; border-radius: 5px; overflow: hidden; margin-top: 10px; }}
        .progress-bar {{ height: 25px; background-color: #4CAF50; width: {percentage}%; text-align: center; line-height: 25px; color: white; font-weight: bold; border-radius: 5px; }}
        .info-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin-top: 20px; }}
        .info-item {{ background-color: #f8f9fa; padding: 15px; border-radius: 8px; border: 1px solid #dee2e6; }}
        .info-item h3 {{ color: #0056b3; margin-top: 0; font-size: 1em; }}
        .info-item p {{ margin: 0; font-size: 0.9em; }}
        .footer {{ text-align: center; margin-top: 30px; font-size: 0.8em; color: #777; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Reporte de Estado del Trabajo</h1>
        <p class="job-id">ID del Trabajo: <code>{job_id}</code></p>
        
        <div class="status-section">
            <p><strong>Estado Actual:</strong> <span class="status-value">{status_icon} {status}</span></p>
            <p><strong>Mensaje:</strong> 
    """
    if status == "COMPLETED":
        html_content += f"El trabajo {job_id} ha sido completado exitosamente."
    elif status == "QUEUING":
        html_content += f"El trabajo {job_id} ha sido aceptado y está en cola para procesamiento."
    elif status == "PROCESSING":
        html_content += f"El trabajo {job_id} está actualmente en procesamiento."
    elif status == "FAILED":
        html_content += f"El trabajo {job_id} ha fallado. Por favor, revise los logs del servidor."
    else:
        html_content += f"Estado desconocido para el trabajo {job_id}."
    
    html_content += f"""
            </p>
        </div>

        <div class="info-grid">
            <div class="info-item">
                <h3>Progreso</h3>
                <p>Chunks Procesados: {processed_chunks}</p>
                <p>Total de Chunks: {total_chunks if total_chunks > 0 else 'Aún no determinado'}</p>
                <p>Porcentaje: {percentage:.2f}%</p>
                <div class="progress-bar-container">
                    <div class="progress-bar" style="width: {percentage:.2f}%;">{"{:.2f}%".format(percentage)}</div>
                </div>
            </div>
            <div class="info-item">
                <h3>Resultados Parciales</h3>
                <p>Coincidencias Encontradas: {matches_found}</p>
            </div>
        </div>

        <div class="footer">
            <p>Reporte generado por el cliente de consulta de estado.</p>
        </div>
    </div>
</body>
</html>
    """
    return html_content


# <=================  FIN GENERACION HTML con CSS  =================>


if __name__ == "__main__":

    # argumentos del argparse
    parser = argparse.ArgumentParser(description="Cliente para consultar el estado de un trabajo de análisis genómico.")
    parser.add_argument('--server', type=str, default=MASTER_HOST, help='Dirección IP o hostname del Master Server.')
    parser.add_argument('--port', type=int, default=MASTER_PORT, help='Puerto del Master Server.')
    parser.add_argument('--job-id', type=str, required=True, help='ID del trabajo a consultar.')
    parser.add_argument('--show-results', action='store_true', help='Muestra los resultados finales si el trabajo está completado.')
    parser.add_argument('--output-html', type=str, help='Genera un reporte HTML del estado del trabajo en el archivo especificado.')
    parser.add_argument('--ip-family', type=str, choices=['ipv4', 'ipv6'], help='Forzar el uso de una familia de IP específica (ipv4 o ipv6).')
    
    args = parser.parse_args()

    response = query_job_status(args.server, args.port, args.job_id, ip_family=args.ip_family)

    if response.get("status") == "error":
        print(f"\n❌ Error al consultar el estado del job: {response.get('message', 'Unknown error')}")
    
    else:  # consigue toda la info para imprimir en pantalla
        job_id = response.get('job_id')
        status = response.get('status', 'N/A').upper()
        progress = response.get('progress', {})
        total_chunks = progress.get('total_chunks', 0)
        processed_chunks = progress.get('processed_chunks', 0)
        percentage = progress.get('percentage', 0.0)
        matches_found = response.get('partial_results', {}).get('matches_found', 0)

        print(f"\n📊 Estado del Trabajo: {job_id}")
        print(f"------------------------------------")
        print(f"  Estado Actual: {status}")
        
        if total_chunks > 0:
            # Barra de progreso simple con porcentaje
            bar_length = 20
            filled_length = int(bar_length * percentage // 100)
            bar = '█' * filled_length + '-' * (bar_length - filled_length)
            print(f"  Progreso:    [{bar}] {percentage:.2f}% ({processed_chunks}/{total_chunks} chunks)")
        else:
            print(f"  Progreso:    {processed_chunks} chunks procesados (Total de chunks aún no determinado)")
        
        print(f"  Coincidencias Encontradas: {matches_found}")

        if status == "COMPLETED":
            print(f"\n✅ ¡Trabajo {job_id} completado exitosamente!")
            if args.show_results:
                print("\n--- Resultados Finales ---")
                print(f"Total de coincidencias: {matches_found}")
                print("Nota: La implementación actual del Master Server solo devuelve el conteo total de coincidencias.")
                print("Para ver las posiciones exactas, se necesitaría una lógica adicional en el Master y en este cliente.")
        elif status == "QUEUING":
            print(f"\n⏳ El trabajo {job_id} ha sido aceptado y está en cola para procesamiento.")
        elif status == "PROCESSING":
            print(f"\n🔄 El trabajo {job_id} está actualmente en procesamiento.")
        elif status == "FAILED":
            print(f"\n❌ El trabajo {job_id} ha fallado. Por favor, revise los logs del servidor.")
        else:
            print(f"\n❓ Estado desconocido para el trabajo {job_id}.")


        # Generar reporte HTML cuando la solicitud de trabajo indica que se ha completado
        if args.output_html and status == "COMPLETED":
            try:
                html_report_content = generate_html_report(job_id, response)
                
                report_dir = Path("reportes")
                report_dir.mkdir(parents=True, exist_ok=True) # Crear el directorio si no existe
                
                output_path = report_dir / args.output_html
                
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(html_report_content)
                print(f"\n📄 Reporte HTML generado en: {output_path}")
            except Exception as e:
                logger.error(f"Error al generar el reporte HTML: {e}", exc_info=True)
                print(f"\n❌ Error al generar el reporte HTML: {e}")
