# Explicación de Docker en el Proyecto Analizador de Genoma

Este documento explica el papel fundamental que juegan Docker y Docker Compose en nuestro sistema distribuido de análisis genómico.

## 1. ¿Qué problema resuelve Docker aquí?

Imagina que tienes que ejecutar nuestro proyecto en tu PC. Necesitarías:
1.  Instalar Python 3.11.
2.  Instalar Redis y asegurarte de que esté corriendo.
3.  Abrir 6 terminales distintas.
4.  En una, correr el `master_server.py`.
5.  En otra, correr el `collector_server.py`.
6.  En tres más, correr cada uno de los `genome_worker.py` con su `monitor_agent.py`.
7.  Asegurarte de que todos sepan cómo encontrarse entre sí (configurar IPs y puertos).

Esto es complicado, propenso a errores y no se parece en nada a un entorno de producción real.

**Docker resuelve esto empaquetando cada pieza de nuestro sistema en un "contenedor" aislado y portable.**

- **Contenedor:** Es como una mini-computadora virtual muy ligera que contiene todo lo que un servicio necesita para funcionar: el código de Python, las librerías (`celery`, `redis`, `psutil`), y las dependencias del sistema (como `gcc` para `psutil`).

- **Imagen:** Es la "plantilla" o el "molde" para crear un contenedor. Nuestros `Dockerfile` son las recetas para construir estas imágenes. Por ejemplo, `docker/Dockerfile.worker` es la receta para construir la imagen de un nodo de cómputo.

**Docker Compose** es el orquestador. Lee el archivo `docker-compose.yml` y maneja todos los contenedores como un único sistema: los inicia, los detiene, los conecta entre sí y gestiona sus recursos. Con un solo comando, `docker-compose up`, levanta todo nuestro sistema distribuido.

## 2. Conceptos Técnicos Clave en Nuestro `docker-compose.yml`

### a. Servicios (`services`)

Cada componente de nuestro sistema es un `service` en Docker Compose. Tenemos: `redis`, `master`, `collector`, `worker1`, `worker2`, `worker3`, `worker4` y `worker5`. Cada uno se convierte en un contenedor cuando ejecutamos `docker-compose up`.

### b. Redes (`networks`)

```yaml
networks:
  genome-network:
    driver: bridge
```
Hemos creado una red virtual privada llamada `genome-network`. Todos nuestros contenedores están conectados a esta red.

**¿Por qué es tan importante?**
Dentro de esta red, Docker proporciona un **DNS interno**. Esto significa que un contenedor puede encontrar a otro simplemente usando su nombre de servicio.

Cuando en el `master` configuramos `REDIS_HOST=redis`, no necesitamos saber la dirección IP del contenedor de Redis. Docker se encarga de que el nombre `redis` se resuelva a la IP correcta dentro de la red `genome-network`. Esto hace que la configuración sea limpia y portable.

### c. Volúmenes (`volumes`)

Los volúmenes son el mecanismo de Docker para manejar datos. En nuestro proyecto los usamos de dos formas cruciales:

1.  **Para persistir datos (`redis-data:/data`):**
    - Los contenedores son efímeros. Si borras un contenedor, todos los datos dentro de él se pierden.
    - Para Redis, esto sería un desastre (perderíamos todos los jobs y resultados).
    - Un **volumen nombrado** como `redis-data` le dice a Docker: "Crea un espacio de almacenamiento gestionado por ti en la máquina host y conéctalo al directorio `/data` del contenedor de Redis".
    - Así, aunque el contenedor de Redis se destruya, los datos persisten en el volumen y estarán disponibles la próxima vez que se inicie.

2.  **Para desarrollo en vivo (`./src:/app/src`):**
    - Esto es un **bind mount**. Mapea un directorio de tu PC (`./src`) a un directorio dentro del contenedor (`/app/src`).
    - Su gran ventaja es que **los cambios son instantáneos**. Si modificas un archivo `.py` en tu editor de código, ese cambio se refleja inmediatamente dentro del contenedor.
    - Esto nos permite desarrollar y depurar sin tener que reconstruir la imagen de Docker (`docker-compose build`) cada vez que cambiamos una línea de código, lo cual es extremadamente eficiente.

### d. El Comando del Worker (El más complejo)

```yaml
command: >
  sh -c "
    python src/monitor_agent.py ... &
    sleep 3
    celery -A src.genome_worker worker ...
  "
```
Un contenedor normalmente ejecuta un solo proceso principal. Sin embargo, nuestro diseño requiere que en cada "nodo de cómputo" corran dos procesos: el `genome_worker` (de Celery) y el `monitor_agent`.

Este comando es un pequeño truco de shell para lograrlo:
- `sh -c "..."`: Le dice al contenedor que ejecute los siguientes comandos a través de un intérprete de shell.
- `python src/monitor_agent.py ... &`: Inicia el agente monitor. El `&` al final es crucial, ya que envía este proceso a **segundo plano** (background), permitiendo que el script continúe.
- `sleep 3`: Es una pausa simple pero vital. Le da unos segundos al `monitor_agent` para que se inicie y cree el archivo de socket Unix en `/tmp/`.
- `celery -A src.genome_worker worker ...`: Inicia el worker de Celery. Este es el **proceso principal** (foreground). El contenedor se mantendrá vivo mientras este proceso esté corriendo. Cuando el worker de Celery se detenga, el contenedor se detendrá.

Esta estructura nos permite simular un nodo de cómputo realista donde un proceso de monitoreo vigila a un proceso de trabajo principal, todo dentro del mismo entorno aislado de un contenedor.
