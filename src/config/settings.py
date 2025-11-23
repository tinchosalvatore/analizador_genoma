import os

"""
Archivo que contiene variables de entorno para la configuración de la aplicación.

Este intenta leer las variables de un .env, si no existe usa el valor por defecto

Los valores por defecto estan pensados en base a como estan definidos los contenedores de Docker
"""


# Configuración de Redis
REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')  # el segundo valor es el por defecto 
REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))    

# Configuración del Master Server
MASTER_HOST = os.getenv('MASTER_HOST', 'localhost')
MASTER_PORT = int(os.getenv('MASTER_PORT', 5000))

# Configuración del Collector Server
COLLECTOR_HOST = os.getenv('COLLECTOR_HOST', 'localhost')
COLLECTOR_PORT = int(os.getenv('COLLECTOR_PORT', 6000))
ALERT_THRESHOLD_CPU = int(os.getenv('ALERT_THRESHOLD_CPU', 95))   # porcentajes
ALERT_THRESHOLD_MEMORY = int(os.getenv('ALERT_THRESHOLD_MEMORY', 90))  # valores limite para la alerta

# Configuración de Chunks
DEFAULT_CHUNK_SIZE = int(os.getenv('DEFAULT_CHUNK_SIZE', 1048576)) # 1MB
MAX_FILE_SIZE = int(os.getenv('MAX_FILE_SIZE', 524288000)) # 500MB

# Configuración del Worker
WORKER_ID = os.getenv('WORKER_ID', 'worker1') # Default para desarrollo local  
CELERY_BROKER = os.getenv('CELERY_BROKER', f'redis://{REDIS_HOST}:{REDIS_PORT}/0')
CELERY_BACKEND = os.getenv('CELERY_BACKEND', f'redis://{REDIS_HOST}:{REDIS_PORT}/1')

# Configuración del Agente Monitor
AGENT_REPORT_INTERVAL = int(os.getenv('AGENT_REPORT_INTERVAL', 10)) # segundos
HEARTBEAT_TIMEOUT = int(os.getenv('HEARTBEAT_TIMEOUT', 15)) # segundos
IPC_SOCKET_PATH = os.getenv('IPC_SOCKET_PATH', f'/tmp/worker_{WORKER_ID}.sock')

# Nuevas configuraciones para el Collector Server
COLLECTOR_METRICS_TTL = int(os.getenv('COLLECTOR_METRICS_TTL', 60)) # TTL en segundos para métricas en Redis
COLLECTOR_WORKER_TIMEOUT = int(os.getenv('COLLECTOR_WORKER_TIMEOUT', 30)) # Segundos sin reporte para considerar worker en timeout
COLLECTOR_MONITOR_INTERVAL = int(os.getenv('COLLECTOR_MONITOR_INTERVAL', 10)) # Intervalo en segundos para el monitor de timeouts
COLLECTOR_LISTEN_HOSTS = os.getenv('COLLECTOR_LISTEN_HOSTS', '0.0.0.0,::').split(',') # Hosts donde el Collector escuchará (Dual-Stack)

# Configuración de Logging
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()   # puede cambiarse a DEBUG para logs mas detallados
LOG_DIR = os.getenv('LOG_DIR', '/app/logs') # Dentro del contenedor Docker 