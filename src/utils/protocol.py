import json
from typing import Any, Dict, Tuple

# Esquemas de validación para los diferentes tipos de mensajes
# Definiciones basadas en la Sección 4 del README.md

MESSAGE_SCHEMAS = {
    "submit_job": {
        "required": ["type", "job_id", "filename", "pattern", "chunk_size", "file_size", "file_data_b64"],
        "properties": {
            "type": {"type": "string", "enum": ["submit_job"]},
            "job_id": {"type": "string"}, # UUID
            "filename": {"type": "string"},
            "pattern": {"type": "string"},
            "chunk_size": {"type": "integer", "minimum": 1},
            "file_size": {"type": "integer", "minimum": 0},
            "file_data_b64": {"type": "string"} # Base64 encoded data
        }
    },
    "query_status": {
        "required": ["type", "job_id"],
        "properties": {
            "type": {"type": "string", "enum": ["query_status"]},
            "job_id": {"type": "string"} # UUID
        }
    },
    "metrics": {
        "required": ["type", "data"],
        "properties": {
            "type": {"type": "string", "enum": ["metrics"]},
            "data": {
                "type": "object",
                "required": ["worker_id", "timestamp", "status", "cpu_percent", "memory_mb", "memory_percent"],
                "properties": {
                    "worker_id": {"type": "string"},
                    "timestamp": {"type": "number"},
                    "status": {"type": "string", "enum": ["ALIVE", "DEAD"]},
                    "cpu_percent": {"type": "number", "minimum": 0.0, "maximum": 100.0},
                    "memory_mb": {"type": "number", "minimum": 0.0},
                    "memory_percent": {"type": "number", "minimum": 0.0, "maximum": 100.0},
                    "tasks_processed": {"type": "integer", "minimum": 0} # Opcional
                }
            }
        }
    },
    "worker_down": {
        "required": ["type", "worker_id", "timestamp"],
        "properties": {
            "type": {"type": "string", "enum": ["worker_down"]},
            "worker_id": {"type": "string"},
            "timestamp": {"type": "number"},
            "last_task_id": {"type": "string"} # Opcional
        }
    },
    "heartbeat": {
        "required": ["type", "timestamp"],
        "properties": {
            "type": {"type": "string", "enum": ["heartbeat"]},
            "timestamp": {"type": "number"},
            "tasks_completed": {"type": "integer", "minimum": 0} # Opcional
        }
    }
}

def validate_message(message: Dict[str, Any], message_type: str) -> Tuple[bool, str]:
    """
    Valida un mensaje JSON contra un esquema predefinido.

    Args:
        message: El diccionario del mensaje JSON a validar.
        message_type: El tipo de mensaje esperado (ej. 'submit_job', 'metrics').

    Returns:
        Una tupla (bool, str) donde el booleano indica si es válido y el string
        contiene un mensaje de error si no es válido, o "OK" si lo es.
    """
    schema = MESSAGE_SCHEMAS.get(message_type)
    if not schema:
        return False, f"Esquema de validación no encontrado para el tipo de mensaje: {message_type}"

    # Validar campos requeridos
    for field in schema.get("required", []):
        if field not in message:
            return False, f"Campo requerido '{field}' ausente en el mensaje de tipo '{message_type}'."

    # Validar propiedades y tipos
    for field, props in schema.get("properties", {}).items():
        if field in message:
            value = message[field]
            expected_type = props.get("type")
            
            if expected_type == "string" and not isinstance(value, str):
                return False, f"Campo '{field}' debe ser de tipo string."
            elif expected_type == "integer" and not isinstance(value, int):
                return False, f"Campo '{field}' debe ser de tipo entero."
            elif expected_type == "number" and not (isinstance(value, int) or isinstance(value, float)):
                return False, f"Campo '{field}' debe ser de tipo numérico."
            elif expected_type == "object" and not isinstance(value, dict):
                return False, f"Campo '{field}' debe ser de tipo objeto."
            elif expected_type == "array" and not isinstance(value, list):
                return False, f"Campo '{field}' debe ser de tipo array."

            if "enum" in props and value not in props["enum"]:
                return False, f"Campo '{field}' tiene un valor inválido: '{value}'. Valores permitidos: {props["enum"]}."
            
            if "minimum" in props and isinstance(value, (int, float)) and value < props["minimum"]:
                return False, f"Campo '{field}' debe ser mayor o igual a {props["minimum"]}."
            
            if "maximum" in props and isinstance(value, (int, float)) and value > props["maximum"]:
                return False, f"Campo '{field}' debe ser menor o igual a {props["maximum"]}."

            # Si el campo es un objeto anidado (como 'data' en 'metrics'), validarlo recursivamente
            if expected_type == "object" and field == "data" and message_type == "metrics":
                # Aquí se asume que el esquema para 'data' está directamente en MESSAGE_SCHEMAS['metrics']['data']
                # y no se llama recursivamente a validate_message con un nuevo message_type.
                # Se valida directamente contra las propiedades definidas para 'data'.
                data_schema_props = MESSAGE_SCHEMAS["metrics"]["properties"]["data"]
                for data_field, data_props in data_schema_props.get("properties", {}).items():
                    if data_field in value:
                        data_value = value[data_field]
                        data_expected_type = data_props.get("type")

                        if data_expected_type == "string" and not isinstance(data_value, str):
                            return False, f"Campo 'data.{data_field}' debe ser de tipo string."
                        elif data_expected_type == "integer" and not isinstance(data_value, int):
                            return False, f"Campo 'data.{data_field}' debe ser de tipo entero."
                        elif data_expected_type == "number" and not (isinstance(data_value, int) or isinstance(data_value, float)):
                            return False, f"Campo 'data.{data_field}' debe ser de tipo numérico."

                        if "enum" in data_props and data_value not in data_props["enum"]:
                            return False, f"Campo 'data.{data_field}' tiene un valor inválido: '{data_value}'. Valores permitidos: {data_props["enum"]}."
                        
                        if "minimum" in data_props and isinstance(data_value, (int, float)) and data_value < data_props["minimum"]:
                            return False, f"Campo 'data.{data_field}' debe ser mayor o igual a {data_props["minimum"]}."
                        
                        if "maximum" in data_props and isinstance(data_value, (int, float)) and data_value > data_props["maximum"]:
                            return False, f"Campo 'data.{data_field}' debe ser menor o igual a {data_props["maximum"]}."


    return True, "OK"
