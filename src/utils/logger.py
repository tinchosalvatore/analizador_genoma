import logging
import json
from datetime import datetime
import os

class JSONFormatter(logging.Formatter):
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
        
        # Añadir campos extra si existen
        if hasattr(record, 'extra_data') and isinstance(record.extra_data, dict):
            log_obj.update(record.extra_data)

        return json.dumps(log_obj)

def setup_logger(name: str, log_file: str, level: str = 'INFO'):
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Crear el directorio de logs si no existe
    log_dir = os.path.dirname(log_file)
    if not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)
    
    # Eliminar handlers existentes para evitar duplicados
    if logger.hasHandlers():
        logger.handlers.clear()

    handler = logging.FileHandler(log_file)
    handler.setFormatter(JSONFormatter())
    
    logger.addHandler(handler)
    
    # Configurar un handler para la consola también, si es necesario
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(JSONFormatter())
    logger.addHandler(console_handler)

    return logger
