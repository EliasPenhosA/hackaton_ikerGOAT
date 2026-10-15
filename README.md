# Kit del hackathon: La Cosecha del Bajío

Este kit trae las piezas genéricas para construir su agente el viernes 16 de octubre: la conexión a la base de datos, un esqueleto de agente de ADK con una herramienta de ejemplo y la plantilla del servidor MCP. Lo que se califica es lo que construyan encima para el problema que elijan.

El kit **no** trae RAG. Si su agente necesita consultar documentos (una política, un procedimiento), reutilicen el que construyeron en el Lab 6; ver [Si necesitan RAG](#si-necesitan-rag).

**Antes del examen:** instálenlo y corran `python verificar_entorno.py` hasta que todo salga en ✅. Para que el día del examen no tengan que instalar nada. 

## Qué trae

```
kit_hackathon/
├── README.md                    ← este archivo
├── requirements.txt
├── verificar_entorno.py         ← revisa que todo funcione
├── servidor_mcp.py              ← plantilla de servidor MCP (Lab 7)
├── probar_servidor.py           ← se conecta al servidor MCP como cualquier cliente
├── GUIA_BASE_DE_DATOS.md        ← tablas, columnas y consultas de ejemplo
├── la_cosecha_practica.db       ← base de PRÁCTICA (datos aleatorios)
└── agente/                      ← su agente de ADK
    ├── __init__.py
    ├── agent.py                 ← esqueleto: herramienta de ejemplo + sus herramientas (TODO)
    ├── db.py                    ← consultar() y ejecutar() sobre la base
    └── .env.example             ← cópienlo como .env
```

## Instalación (una vez, antes del examen)

```bash
cd kit_hackathon
uv venv                              # o: python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
uv pip install -r requirements.txt   # o: pip install -r requirements.txt
cp agente/.env.example agente/.env   # Windows: copy agente\.env.example agente\.env
```

Abran `agente/.env` y pongan su API key de AI Studio. **Cada integrante necesita su propia key**: en el free tier, la cuota diaria se acaba rápido si los tres usan la misma.

```bash
python verificar_entorno.py
```

Si todo sale en ✅, prueben el agente:

```bash
adk web
```

y abran [http://localhost:8000](http://localhost:8000). Pregúntenle, por ejemplo, "¿qué columnas tiene la tabla facturas?": debe usar `describir_tabla`.

## Para practicar esta semana

- **Base de datos:** `la_cosecha_practica.db` tiene el mismo esquema que la real, pero datos aleatorios y pocos registros. Practiquen consultas y escriban herramientas de prueba con ella. No saquen conclusiones de negocio: los datos no significan nada.
- **RAG:** tengan a la mano su proyecto del Lab 6 y practiquen copiarlo al kit (ver abajo). Pruébenlo con los PDF de su Lab 6; los documentos del caso llegan el día del examen.
- **MCP:** `python probar_servidor.py clientes` debe mostrar el menú de herramientas y describir la tabla `clientes`.

## El día del examen (7:30)

1. Descarguen el zip del caso de Canvas y descomprímanlo **dentro de la carpeta `caso/`** del kit.
2. Copien `datos_SICOM/la_cosecha.db` a la carpeta del kit y cambien en `agente/.env`:
  ```
   LA_COSECHA_DB=la_cosecha.db
  ```
3. Corran `python verificar_entorno.py --sin-gemini` para confirmar que todo apunta a los datos reales.
4. Lean el caso y elijan su problema. **Después** decidan qué herramientas necesita su agente.
5. Construyan: instrucciones, herramientas y, si su problema lo pide, RAG o su servidor MCP.

## Cómo construir sobre el kit

- **Herramientas específicas, no genéricas.** Escriban herramientas para su problema (por ejemplo, "facturas abiertas de un cliente"), no una que ejecute cualquier SQL que escriba el modelo. Son más confiables, más fáciles de probar y más seguras. Hay un ejemplo comentado en `agente/agent.py`.
- **Regresen poco.** Una herramienta que regresa 5,000 filas llena el contexto del modelo. Filtren, resuman o limiten.
- **Requisito:** al menos 2 tipos distintos de herramienta (funciones propias, RAG, MCP). Lo que se califica es que cada una tenga sentido para su problema, no cuántas haya.
- **Bono de aprobación humana:** envuelvan la herramienta que escribe con `FunctionTool(su_funcion, require_confirmation=True)`. ADK pausa y pide confirmación antes de ejecutarla.
- **Instrucciones:** sigan la estructura vista en clase (rol y alcance, herramientas, límites, formato, prioridad)

## Si necesitan RAG

Indexar los 36 documentos del caso no hace a su agente más útil: la mayoría son material para que **ustedes** entiendan el problema (correos, minutas, reportes). Un agente sólo necesita RAG si en operación tiene que consultar un texto, por ejemplo la política de crédito o el procedimiento de reclamaciones. En ese caso:

1. Copien de su Lab 6 a `agente/`: `rag_core.py`, su `ingest.py` y sus herramientas de búsqueda (`search_documents`, `read_page` o como las hayan llamado).
2. Cambien los imports de `rag_agent` a `agente` (por ejemplo, `from .rag_core import get_collection`).
3. Apunten `ingest.py` sólo a los documentos que su agente necesita y revisen los metadatos: los del Lab 6 dependían de sus carpetas.
4. Agreguen sus herramientas de búsqueda a `tools=[...]` en `agent.py` y expliquen en las instrucciones cuándo usarlas.

`chromadb`, `sentence-transformers` y `pymupdf4llm` ya están en `requirements.txt`, así que no tienen que instalar nada más. La primera vez que usen embeddings locales se descarga el modelo (~490 MB): háganlo **antes** del examen, con su Lab 6.

## Qué NO entregar

No incluyan en sus zips: `agente/.env` (tiene su API key), las bases de datos (`*.db`), la carpeta `chroma_db/` ni la carpeta `caso/`. El `.gitignore` ya los excluye si usan git.