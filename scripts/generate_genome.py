import random
import argparse

# Genera archivo de genoma mezclando los 4 tipos de nucleotidos al azar
def generate_genome(size_mb: int, output_file: str):
    nucleotides = ['A', 'C', 'G', 'T']    # A = Adenina, C = Citosina, G = Guanina, T = Timina
    size_bytes = size_mb * 1024 * 1024    # Calcula cuandos bytes son los MB que ingresamos con el argparse
    
    with open(output_file, 'w') as f:
        # Escribir en líneas de 60 caracteres
        chars_written = 0
        while chars_written < size_bytes:
            line = ''.join(random.choices(nucleotides, k=60))
            f.write(line + '\n')
            chars_written += 61  # 60 chars + newline
    
    print(f"Archivo generado: {output_file} ({size_mb}MB)")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Generate a synthetic genome file.')
    parser.add_argument('--size', type=int, required=True, help='Tamaño en MB del archivo a generar.')
    parser.add_argument('--output', required=True, help='Ruta del archivo de salida.')
    args = parser.parse_args()
    
    generate_genome(args.size, args.output)