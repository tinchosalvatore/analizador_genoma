import os

"""
Archivo que contiene variables de entorno para la configuración de la aplicación.
Tambien valores por defecto en caso de no encontrarlas en el archivo .env
"""

# Configuración de Redis
REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))

# Configuración del Master Server
MASTER_HOST = os.getenv('MASTER_HOST', 'localhost')
MASTER_PORT = int(os.getenv('MASTER_PORT', 5000))

# Configuración del Collector Server
COLLECTOR_HOST = os.getenv('COLLECTOR_HOST', 'localhost')
COLLECTOR_PORT = int(os.getenv('COLLECTOR_PORT', 6000))
ALERT_THRESHOLD_CPU = int(os.getenv('ALERT_THRESHOLD_CPU', 95))
ALERT_THRESHOLD_MEMORY = int(os.getenv('ALERT_THRESHOLD_MEMORY', 90))

# Configuración de Chunks
DEFAULT_CHUNK_SIZE = int(os.getenv('DEFAULT_CHUNK_SIZE', 1048576)) # 1MB


# Configuración del Worker
WORKER_ID = os.getenv('WORKER_ID', 'worker1') # Default para desarrollo local
CELERY_BROKER = os.getenv('CELERY_BROKER', f'redis://{REDIS_HOST}:{REDIS_PORT}/0')
CELERY_BACKEND = os.getenv('CELERY_BACKEND', f'redis://{REDIS_HOST}:{REDIS_PORT}/1')

# Configuración del Agente Monitor
AGENT_REPORT_INTERVAL = int(os.getenv('AGENT_REPORT_INTERVAL', 10)) # segundos
HEARTBEAT_TIMEOUT = int(os.getenv('HEARTBEAT_TIMEOUT', 15)) # segundos
IPC_SOCKET_PATH = os.getenv('IPC_SOCKET_PATH', f'/tmp/worker_{WORKER_ID}.sock')

# Configuración de Logging
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
LOG_DIR = os.getenv('LOG_DIR', '/app/logs') # Dentro del contenedor Docker
