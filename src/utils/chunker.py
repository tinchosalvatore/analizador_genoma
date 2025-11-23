from typing import Generator, Tuple, Dict
from src.config.settings import DEFAULT_CHUNK_SIZE

def divide_data_with_overlap(data: bytes, chunk_size: int = DEFAULT_CHUNK_SIZE, overlap: int = 100) -> Generator[Tuple[int, bytes, Dict[str, any]], None, None]:
    """
    Divide un objeto bytes en chunks de tamaño fijo con un solapamiento (overlap) entre ellos.
    El solapamiento aplica solo para UN chunk posterior.

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
    current_offset = 0  # Posicion absoluta en el archivo
    
    while current_offset < total_size:  
        # Calcular el inicio de la lectura para incluir el overlap del chunk anterior
        read_start_index = current_offset - (overlap if chunk_id > 0 else 0)
        # Asegurarse de no leer antes del inicio de los datos
        read_start_index = max(0, read_start_index)
        
        # Calcular el final de la lectura para incluir el tamaño del chunk y el overlap para el siguiente
        read_end_index = current_offset + chunk_size + (overlap if chunk_id > 0 else 0)
        # Asegurarse de no leer más allá del final de los datos
        read_end_index = min(total_size, read_end_index)
        
        # Extraer el chunk de datos con su overlap
        chunk_data_with_overlap = data[read_start_index:read_end_index]
        
        if not chunk_data_with_overlap:   # termino
            break
        
        metadata = {
            'chunk_id': chunk_id,
            'offset': read_start_index, # Offset real del inicio de este chunk con overlap
            'size': len(chunk_data_with_overlap),
            'has_overlap': chunk_id > 0       # si el chunk id no es el primero, entonces si tiene overlap, osea True
        }
        
        # Usamos yield para que devuelva los valores cuando puede, por mas que no sean los 3 al mismo tiempo
        yield chunk_id, chunk_data_with_overlap, metadata     
        
        # Avanzar el offset para el siguiente chunk por el tamaño del chunk (sin overlap)
        current_offset += chunk_size
        chunk_id += 1


def divide_file_with_overlap(file_path: str, chunk_size: int = DEFAULT_CHUNK_SIZE, overlap: int = 100) -> Generator[Tuple[int, bytes, Dict[str, any]], None, None]:
    """
    Lee el archivo completo en memoria para ejecutar la funcion que lo divide.    
    """
    with open(file_path, 'rb') as f:
        file_data = f.read()
    return divide_data_with_overlap(file_data, chunk_size, overlap)