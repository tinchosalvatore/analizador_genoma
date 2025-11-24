#!/bin/bash

# Script para enviar un trabajo y luego consultar su estado repetidamente.

# Configuración
FILE_PATH="data/genome_200MB.txt"
PATTERN="AGGTCCAT"
LOG_DIR="./local_log"
QUERY_INTERVAL=2 # Intervalo de consulta en segundos

echo "Paso 1: Enviando el trabajo..."
# Ejecutar submit_job.py y capturar la salida
SUBMIT_OUTPUT=$(PYTHONPATH=./src LOG_DIR=${LOG_DIR} python -m src.submit_job --file ${FILE_PATH} --pattern ${PATTERN} --port 5000)
SUBMIT_EXIT_CODE=$?

if [ ${SUBMIT_EXIT_CODE} -ne 0 ]; then
    echo "Error al enviar el trabajo. Saliendo."
    echo "${SUBMIT_OUTPUT}"
    exit 1
fi

echo "${SUBMIT_OUTPUT}"

# Extraer el JOB_ID de la salida
JOB_ID=$(echo "${SUBMIT_OUTPUT}" | grep "Job ID:" | awk '{print $3}')

if [ -z "${JOB_ID}" ]; then
    echo "No se pudo extraer el JOB_ID de la salida. Saliendo."
    exit 1
fi

echo "Job ID extraído: ${JOB_ID}"
echo "Paso 2: Consultando el estado del trabajo ${JOB_ID} repetidamente (Ctrl+C para detener)..."

# Bucle para consultar el estado
while true; do
    QUERY_OUTPUT=$(PYTHONPATH=./src LOG_DIR=${LOG_DIR} python -m src.query_job --job-id ${JOB_ID})
    echo "${QUERY_OUTPUT}"
    
    # Detener el bucle cuando el trabajo esté completo
    if echo "${QUERY_OUTPUT}" | grep -q "Estado Actual: COMPLETED"; then
        echo "Trabajo completado. Generando reporte HTML..."
        
        # Generar el reporte HTML final
        PYTHONPATH=./src LOG_DIR=${LOG_DIR} python -m src.query_job --job-id ${JOB_ID} --output-html "report-${JOB_ID}.html"
        
        echo "Reporte HTML 'report-${JOB_ID}.html' generado."
        break
    fi

    sleep ${QUERY_INTERVAL}
done
