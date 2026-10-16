<div align="center">

⚡ IKER GOAT 🐐
Hackathon de IA Agéntica · Agent Development Kit
Un equipo. Un agente. Soluciones basadas en datos.
Python · Google ADK · Gemini · SQLite · MCP · RAG
</div>

👨‍💻 Nuestro equipo
Integrante	Equipo
Iker Manuel Aboitiz 🐐	IKER GOAT
Elías Penhos Abadi	IKER GOAT
Meyer Hemlinson Rosenthal	IKER GOAT


🎯 ¿Qué vamos a construir?
Desarrollaremos un agente de inteligencia artificial para resolver un reto operativo de Distribuidora La Cosecha del Bajío. Partiremos del esqueleto proporcionado para el hackathon y lo adaptaremos al problema que se asigne.
El agente estará diseñado para entender solicitudes en lenguaje natural, consultar información confiable y entregar respuestas o recomendaciones verificables. Su alcance y las acciones permitidas se definirán de acuerdo con el caso.
🛠️ Herramientas y tecnologías
Tecnología	Para qué la usaremos
Python	Implementar la lógica y las herramientas del agente.
Google Agent Development Kit (ADK)	Construir, ejecutar y probar el agente.
Gemini	Interpretar solicitudes, razonar sobre resultados y redactar respuestas.
SQLite	Consultar la base de datos de la distribuidora.
Herramientas propias (Function Tools)	Ejecutar consultas y funciones específicas para el reto.
Model Context Protocol (MCP)	Exponer o integrar herramientas cuando lo requiera la solución.
RAG (si el caso lo requiere)	Recuperar información de documentos relevantes para fundamentar respuestas.
Git y GitHub	Control de versiones y colaboración en equipo.

🧾 ¿Qué hace nuestro agente?
Es un asistente de conciliación bancaria para el área de contabilidad: ayuda a descubrir de quién es cada depósito que llega al banco sin referencia y a aplicarlo a las facturas correctas, sin que nadie tenga que revisar cientos de movimientos a mano.

Herramienta	Qué hace por ti
🔍 describir_tabla	Te muestra qué datos guarda la base (columnas y ejemplos) para que el agente sepa dónde buscar.
🕵️ buscar_facturas_de_movimiento	Hace de detective: toma un depósito sin identificar y sugiere a qué cliente y a qué facturas pertenece. Revisa si esa cuenta ya había pagado antes, si el concepto menciona un folio o un nombre, y si el monto cuadra con una factura o con la suma de varias. Cada candidato llega con su puntaje, su nivel de confianza (alta, media o baja) y la explicación de por qué lo sugiere. Solo propone: no cambia nada.
✅ cuadrar_pago	Aplica el pago: reparte el depósito entre las facturas, baja sus saldos, las marca como pagadas y deja el movimiento como aplicado. Todo ocurre en un solo paso: o se guarda completo o no se guarda nada. Siempre pide tu aprobación antes de escribir en la base.

Cómo funciona en la práctica: el contador pregunta "¿a quién corresponde el movimiento MB000893?", el agente explica sus sospechas y qué tan fuertes son, y solo si el contador aprueba, el pago se aplica. La IA propone; la persona decide.


🧠 Conceptos de inteligencia artificial
- IA agéntica: un agente que selecciona herramientas para cumplir un objetivo.
- Tool calling: invocación de funciones para obtener datos y ejecutar tareas concretas.
- Prompt engineering: definición de rol, instrucciones, límites y formato de respuesta.
- Grounding: respuestas fundamentadas en registros de la base y, cuando aplique, documentos.
- RAG (Retrieval-Augmented Generation): recuperación de información externa antes de generar una respuesta, si el reto requiere documentos.
- MCP (Model Context Protocol): protocolo para conectar herramientas externas con sistemas de IA.
- Human-in-the-loop (HITL): aprobación humana antes de acciones sensibles, si se implementan.

<div align="center">

IKER GOAT 🐐 
</div>