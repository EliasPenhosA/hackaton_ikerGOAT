"""Revisa que todo esté listo para el hackathon. Córranlo hasta que todo salga en ✅.

Uso:
    python verificar_entorno.py
    python verificar_entorno.py --sin-gemini     # no gasta cuota de la API (no prueba el modelo)
"""

import argparse
import asyncio
import importlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV = ROOT / "agente" / ".env"
resultados = []


def check(desc, ok, pista=""):
    resultados.append(ok)
    print(f"✅ {desc}" if ok else f"❌ {desc}\n     → {pista}")
    return ok


def paquete(nombre, modulo):
    try:
        m = importlib.import_module(modulo)
        v = getattr(m, "__version__", "")
        if not v:
            from importlib.metadata import version
            v = version(nombre)
        return check(f"{nombre} instalado ({v})", True)
    except Exception as e:  # noqa: BLE001
        return check(f"{nombre} instalado", False, f"pip install -r requirements.txt  ({e.__class__.__name__})")


async def _probar_mcp():
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    params = StdioServerParameters(command=sys.executable, args=[str(ROOT / "servidor_mcp.py")])
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            return [t.name for t in (await s.list_tools()).tools]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sin-gemini", action="store_true")
    args = ap.parse_args()

    print("1. Python y paquetes")
    check(f"Python {sys.version.split()[0]} (se necesita 3.10 o mayor)", sys.version_info >= (3, 10),
          "instalen Python 3.10+ y creen de nuevo el entorno virtual")
    check("están dentro de un entorno virtual", sys.prefix != getattr(sys, "base_prefix", sys.prefix),
          "activen el entorno: source .venv/bin/activate  (Windows: .venv\\Scripts\\activate)")
    for nombre, modulo in [("google-adk", "google.adk"), ("python-dotenv", "dotenv"), ("mcp", "mcp"),
                           ("chromadb", "chromadb"), ("sentence-transformers", "sentence_transformers"),
                           ("pymupdf4llm", "pymupdf4llm")]:  # los tres últimos: para reutilizar su RAG del Lab 6
        paquete(nombre, modulo)

    print("\n2. Configuración (agente/.env)")
    if check("existe agente/.env", ENV.exists(), "cp agente/.env.example agente/.env y pongan su API key"):
        from dotenv import load_dotenv
        load_dotenv(ENV)
    key = os.getenv("GOOGLE_API_KEY", "")
    check("GOOGLE_API_KEY configurada", bool(key) and key != "tu_api_key",
          "pongan su API key de AI Studio en agente/.env")
    modelo = os.getenv("AGENT_MODEL", "gemini-3.5-flash-lite")
    print(f"   modelo del agente: {modelo}")

    print("\n3. Base de datos")
    try:
        sys.path.insert(0, str(ROOT))
        from agente.db import DB_PATH, consultar
        tablas = [r["name"] for r in consultar("SELECT name FROM sqlite_master WHERE type='table'")]
        n = consultar("SELECT COUNT(*) AS n FROM clientes")[0]["n"]
        check(f"base conectada: {DB_PATH.name} ({len(tablas)} tablas, {n:,} clientes)", "pedidos" in tablas,
              "revisen LA_COSECHA_DB en agente/.env")
        if "acerca_de" in tablas:
            print("   (es la base de PRÁCTICA: datos aleatorios, sólo para probar el código)")
    except Exception as e:  # noqa: BLE001
        check("base conectada", False, f"{e}")

    print("\n4. Agente")
    try:
        from agente.agent import root_agent
        check(f"el agente carga ({root_agent.name}, {len(root_agent.tools)} herramientas)", True)
    except Exception as e:  # noqa: BLE001
        check("el agente carga", False, f"{e.__class__.__name__}: {str(e)[:200]}")

    print("\n5. Servidor MCP")
    try:
        herramientas = asyncio.run(asyncio.wait_for(_probar_mcp(), timeout=120))
        check(f"servidor_mcp.py responde ({', '.join(herramientas)})", bool(herramientas))
    except Exception as e:  # noqa: BLE001
        check("servidor_mcp.py responde", False, f"{e.__class__.__name__}: {str(e)[:200]}  (corran python servidor_mcp.py para ver el error)")

    print("\n6. Gemini")
    if args.sin_gemini:
        print("   (omitido con --sin-gemini)")
    else:
        try:
            from google import genai
            client = genai.Client()
            r = client.models.generate_content(model=modelo, contents="Responde sólo: OK")
            check(f"la API responde con {modelo}: {r.text.strip()[:20]!r}", True)
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            pista = ("cuota agotada por ahora; prueben más tarde o con otra API key" if "429" in msg
                     else "revisen la API key y el nombre del modelo en agente/.env")
            check("la API de Gemini responde", False, f"{msg[:150]} → {pista}")

    total, ok = len(resultados), sum(resultados)
    print(f"\n{'🎉 Todo listo' if ok == total else '⚠️  Faltan cosas'}: {ok}/{total} verificaciones correctas.")


if __name__ == "__main__":
    main()
