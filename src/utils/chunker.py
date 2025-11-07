import io
from typing import Generator, Tuple, Dict, Union

def divide_data_with_overlap(data: bytes, chunk_size: int = 51200, overlap: int = 100) -> Generator[Tuple[int, bytes, Dict[str, any]], None, None]:
    """
    Divide un objeto bytes en chunks de tamaño fijo con un solapamiento (overlap) entre ellos.

    Args:
        data: Los datos binarios a dividir.
        chunk_size: El tamaño deseado de cada chunk en bytes (sin incluir el overlap).
        overlap: El número de bytes que se solaparán entre chunks consecutivos.

    Yields:
        Una tupla que contiene:
        - chunk_id (int): Un identificador único para el chunk.
        - chunk_data (bytes): Los datos binarios del chunk, incluyendo el overlap si aplica.
        - metadata (Dict[str, any]): Un diccionario con metadatos del chunk (id, offset, size, has_overlap).
    """
    total_size = len(data)
    chunk_id = 0
    current_offset = 0
    
    while current_offset < total_size:
        # Calcular el inicio de la lectura para incluir el overlap del chunk anterior
        read_start_index = current_offset - (overlap if chunk_id > 0 else 0)
        # Asegurarse de no leer antes del inicio de los datos
        read_start_index = max(0, read_start_index)
        
        # Calcular el final de la lectura para incluir el tamaño del chunk y el overlap para el siguiente
        read_end_index = current_offset + chunk_size + (overlap if chunk_id > 0 else 0)
        # Asegurarse de no leer más allá del final de los datos
        read_end_index = min(total_size, read_end_index)
        
        # Extraer el chunk de datos con su posible overlap
        chunk_data_with_overlap = data[read_start_index:read_end_index]
        
        if not chunk_data_with_overlap:
            break
        
        metadata = {
            'chunk_id': chunk_id,
            'offset': read_start_index, # Offset real del inicio de este chunk con overlap
            'size': len(chunk_data_with_overlap),
            'has_overlap': chunk_id > 0
        }
        
        yield chunk_id, chunk_data_with_overlap, metadata
        
        # Avanzar el offset para el siguiente chunk por el tamaño del chunk (sin overlap)
        current_offset += chunk_size
        chunk_id += 1

# Mantener la función original para compatibilidad si se usa con file_path
def divide_file_with_overlap(file_path: str, chunk_size: int = 51200, overlap: int = 100) -> Generator[Tuple[int, bytes, Dict[str, any]], None, None]:
    """
    Divide un archivo en chunks de tamaño fijo con un solapamiento (overlap) entre ellos.
    Lee el archivo completo en memoria para luego dividirlo.
    """
    with open(file_path, 'rb') as f:
        file_data = f.read()
    return divide_data_with_overlap(file_data, chunk_size, overlap)