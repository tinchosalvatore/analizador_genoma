import logging
import json
from datetime import datetime
import os

class JSONFormatter(logging.Formatter):
    
    # Formate el log a un JSON con su formato esperado
    def format(self, record):
        log_obj = {
            'timestamp': datetime.utcnow().isoformat(),
            'level': record.levelname,
            'component': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName
        }
        if record.exc_info:
            log_obj['exception'] = self.formatException(record.exc_info)
        
        # Procesar cualquier atributo extra que no sea interno de logging
        RESERVED_ATTRS = {
            'name', 'msg', 'args', 'created', 'filename', 'funcName', 'levelname',
            'levelno', 'lineno', 'module', 'msecs', 'pathname', 'process',
            'processName', 'relativeCreated', 'thread', 'threadName', 'exc_info',
            'exc_text', 'stack_info', 'getMessage', 'message'
        }

        for key, value in record.__dict__.items():
            if key not in RESERVED_ATTRS and not key.startswith('_'):
                try:
                    # Intentar serializar el valor a JSON
                    json.dumps(value)
                    log_obj[key] = value
                except (TypeError, ValueError):
                    # Si no se puede serializar, convertir a string
                    log_obj[key] = str(value)

        return json.dumps(log_obj)

def setup_logger(name: str, log_file: str, level: str = 'INFO'):
    logger = logging.getLogger(name)   # inicializamos el logger
    logger.setLevel(level)

    # Crear el directorio de logs si no existe
    log_dir = os.path.dirname(log_file)
    if not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)
    
    # Eliminar handlers existentes genericos para evitar duplicados
    if logger.hasHandlers():
        logger.handlers.clear()

    handler = logging.FileHandler(log_file)   # definimos que handler queremos usar
    handler.setFormatter(JSONFormatter())    # usamos nuestro propio formateador del handler
    
    logger.addHandler(handler)
    
    # Configurar un handler para la consola también, si es necesario
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(JSONFormatter())
    logger.addHandler(console_handler)

    return logger