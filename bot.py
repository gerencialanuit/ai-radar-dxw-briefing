#!/usr/bin/env python3
"""AI Radar -> Discord. Lee feeds RSS, filtra, resume con Gemini y publica embeds."""

import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta

import feedparser
import requests
import yaml

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FEEDS_PATH = os.path.join(BASE_DIR, "feeds.yml")
STATE_PATH = os.path.join(BASE_DIR, "state.json")
ENV_PATH = os.path.join(BASE_DIR, ".env")

MAX_VISTOS = 2000
MAX_ARCHIVO = 1500
ARCHIVO_DIAS = 10
MAX_ENTRIES_POR_FEED = 25
PAUSA_ENTRE_PUBLICACIONES = 7
USER_AGENT = "Mozilla/5.0 (compatible; AIRadarBot/1.0)"

YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"

# Rangos Unicode de escrituras no latinas (coreano, tamil, devanagari, CJK,
# arabe, tailandes) -- si el titulo cae aca, se descarta como "no ingles"
# sin necesidad de una libreria de deteccion de idioma.
PATRON_SCRIPT_NO_LATIN = re.compile(
    r"[가-힣஀-௿ऀ-ॿ一-鿿؀-ۿ฀-๿]"
)

# Mismos temas que la lente DXW del briefing semanal (ver DXW_CONTEXT en
# briefing.py) -- se usan aqui como puntaje de prioridad, no como filtro:
# no descartan nada, solo deciden quien gana el cupo cuando hay mas
# candidatos que espacio en max_por_corrida.
PALABRAS_PRIORIDAD = [
    "agent", "agentic", "automation", "workflow", "no-code", "low-code",
    "local seo", "google business profile", "gbp", "local search", "maps",
    "aeo", "geo", "answer engine", "generative engine", "ai search",
    "review", "reputation", "testimonial", "crm", "hubspot", "salesforce",
    "twilio", "sms", "voice", "call", "receptionist", "messaging",
    "small business", "smb", "service business", "home service",
    "field service", "contractor", "api", "integration", "webhook", "mcp",
    "onboarding", "ux", "product design", "pricing", "saas", "perplexity",
    "search console", "schema", "structured data", "citation", "lead",
    "funnel", "retention", "churn",
]
PALABRAS_CLAUDE = ["claude", "anthropic"]
BONUS_CLAUDE = 10

PROMPT_RESUMEN = (
    "Summarize this AI news story in AT MOST 2 sentences, in neutral English, "
    "executive and direct tone, no introductions or quotes. Focus on what is "
    "changing and why it matters to a business."
)


def cargar_env():
    if not os.path.isfile(ENV_PATH):
        return
    with open(ENV_PATH, "r", encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip()
            if not linea or linea.startswith("#") or "=" not in linea:
                continue
            clave, _, valor = linea.partition("=")
            clave = clave.strip()
            valor = valor.strip().strip('"').strip("'")
            os.environ.setdefault(clave, valor)


def cargar_feeds():
    with open(FEEDS_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def cargar_estado():
    with open(STATE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def guardar_estado(estado):
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=2)


def limpiar(texto, limite):
    if not texto:
        return ""
    texto = re.sub(r"<[^>]+>", " ", texto)
    texto = re.sub(r"&[a-zA-Z#0-9]+;", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    if len(texto) > limite:
        texto = texto[:limite].rstrip() + "..."
    return texto


def huella_de(entry):
    base = entry.get("id") or entry.get("link") or entry.get("title") or ""
    return hashlib.sha1(base.encode("utf-8", errors="ignore")).hexdigest()[:16]


def fecha_de(entry):
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        return datetime(*parsed[:6], tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


def fetch_feed(url):
    resp = requests.get(url, timeout=15, headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    return feedparser.parse(resp.content)


def buscar_videos_youtube(query, api_key, dias, max_resultados):
    publicado_despues = (datetime.now(timezone.utc) - timedelta(days=dias)).strftime("%Y-%m-%dT%H:%M:%SZ")
    params = {
        "part": "snippet",
        "q": query,
        "type": "video",
        "order": "viewCount",
        "publishedAfter": publicado_despues,
        "maxResults": max_resultados,
        "relevanceLanguage": "en",
        "key": api_key,
    }
    resp = requests.get(YOUTUBE_SEARCH_URL, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json().get("items", [])


def obtener_detalles_youtube(video_ids, api_key):
    if not video_ids:
        return {}
    params = {"part": "statistics,snippet", "id": ",".join(video_ids), "key": api_key}
    resp = requests.get(YOUTUBE_VIDEOS_URL, params=params, timeout=15)
    resp.raise_for_status()
    detalles = {}
    for item in resp.json().get("items", []):
        try:
            vistas = int(item.get("statistics", {}).get("viewCount", 0))
        except Exception:
            vistas = 0
        snippet = item.get("snippet", {})
        idioma = snippet.get("defaultAudioLanguage") or snippet.get("defaultLanguage") or ""
        detalles[item["id"]] = {"vistas": vistas, "idioma": idioma}
    return detalles


PALABRAS_NO_INGLES = [
    "español", "completo", "actualizado", "atención", "alerta",
    "descontrolan", "cómo", "vídeo", "años", "está",
]


def es_titulo_en_ingles(idioma_declarado, titulo):
    if idioma_declarado and not idioma_declarado.lower().startswith("en"):
        return False
    if PATRON_SCRIPT_NO_LATIN.search(titulo):
        return False
    titulo_lower = titulo.lower()
    if "ñ" in titulo_lower or any(p in titulo_lower for p in PALABRAS_NO_INGLES):
        return False
    return True


def huella_youtube(video_id):
    return hashlib.sha1(video_id.encode("utf-8", errors="ignore")).hexdigest()[:16]


def procesar_youtube(config_yml, config, categorias, vistos_set, vistos, nuevo_archivo, api_key):
    queries = config_yml.get("youtube_queries") or []
    if not api_key or not queries:
        return []

    dias = int(os.environ.get("YOUTUBE_DIAS") or config.get("youtube_dias", 7))
    max_resultados = int(config.get("youtube_max_resultados", 8))
    vistas_minimas = int(config.get("youtube_vistas_minimas", 3000))
    categoria_cfg = categorias.get("youtube", {})

    encontrados = {}
    for query in queries:
        try:
            items = buscar_videos_youtube(query, api_key, dias, max_resultados)
        except Exception as e:
            print(f"[youtube] busqueda '{query}' fallo: {e}")
            continue
        for item in items:
            video_id = item.get("id", {}).get("videoId")
            if not video_id or video_id in encontrados:
                continue
            encontrados[video_id] = item["snippet"]

    if not encontrados:
        return []

    video_ids = list(encontrados.keys())
    try:
        detalles_por_id = obtener_detalles_youtube(video_ids, api_key)
    except Exception as e:
        print(f"[youtube] no se pudieron obtener detalles: {e}")
        detalles_por_id = {}

    candidatos_youtube = []
    for video_id, snippet in encontrados.items():
        huella = huella_youtube(video_id)
        if huella in vistos_set:
            continue
        vistos_set.add(huella)
        vistos.append(huella)

        detalles = detalles_por_id.get(video_id, {})
        vistas = detalles.get("vistas", 0)
        idioma = detalles.get("idioma", "")

        titulo = limpiar(snippet.get("title", ""), 250)
        extracto = limpiar(snippet.get("description", ""), 450)
        fecha_str = snippet.get("publishedAt")
        try:
            fecha = datetime.fromisoformat(fecha_str.replace("Z", "+00:00")) if fecha_str else datetime.now(timezone.utc)
        except Exception:
            fecha = datetime.now(timezone.utc)

        miniatura = (
            snippet.get("thumbnails", {}).get("high", {}).get("url")
            or snippet.get("thumbnails", {}).get("medium", {}).get("url")
            or snippet.get("thumbnails", {}).get("default", {}).get("url")
        )

        item = {
            "titulo": titulo,
            "link": f"https://www.youtube.com/watch?v={video_id}",
            "fuente": snippet.get("channelTitle", "YouTube"),
            "categoria": "youtube",
            "fecha": fecha.isoformat(),
            "extracto": extracto,
            "vistas": vistas,
            "miniatura": miniatura,
        }
        nuevo_archivo.append(item)

        if not es_titulo_en_ingles(idioma, titulo):
            continue
        if vistas < vistas_minimas:
            continue
        if not categoria_cfg.get("publicar_diario", False):
            continue

        candidatos_youtube.append(item)

    candidatos_youtube.sort(key=lambda x: x["vistas"], reverse=True)
    return candidatos_youtube


def pasa_filtros(categoria_cfg, titulo, extracto):
    texto = (titulo + " " + extracto).lower()
    excluir = categoria_cfg.get("excluir") or []
    for palabra in excluir:
        if palabra.lower() in texto:
            return False
    incluir = categoria_cfg.get("incluir") or []
    if not incluir:
        return True
    for palabra in incluir:
        if palabra.lower() in texto:
            return True
    return False


def calcular_prioridad(titulo, extracto):
    texto = (titulo + " " + extracto).lower()
    puntaje = sum(1 for palabra in PALABRAS_PRIORIDAD if palabra in texto)
    if any(palabra in texto for palabra in PALABRAS_CLAUDE):
        puntaje += BONUS_CLAUDE
    return puntaje


def distribuir_por_categoria(candidatos, categorias_diarias, limite):
    colas = []
    for categoria in categorias_diarias:
        cola = [c for c in candidatos if c["categoria"] == categoria]
        cola.sort(key=lambda x: (calcular_prioridad(x["titulo"], x["extracto"]), x["fecha"]), reverse=True)
        colas.append(cola)

    seleccion = []
    indices = [0] * len(colas)
    while len(seleccion) < limite:
        avance = False
        for i, cola in enumerate(colas):
            if len(seleccion) >= limite:
                break
            if indices[i] < len(cola):
                seleccion.append(cola[indices[i]])
                indices[i] += 1
                avance = True
        if not avance:
            break
    return seleccion


def resumir_con_gemini(titulo, extracto, api_key, modelo):
    if not api_key:
        return extracto[:350]
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"
        f"?key={api_key}"
    )
    prompt = f"{PROMPT_RESUMEN}\n\nTitulo: {titulo}\nContenido: {extracto}"
    body = {"contents": [{"parts": [{"text": prompt}]}]}
    try:
        resp = requests.post(url, json=body, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        print(f"  [gemini] fallo al resumir, usando extracto original: {e}")
        return extracto[:350]


def publicar_discord(webhook_url, embed, max_intentos=4):
    payload = {"embeds": [embed]}
    intento = 0
    while intento < max_intentos:
        intento += 1
        try:
            resp = requests.post(webhook_url, json=payload, timeout=15)
        except Exception as e:
            print(f"  [discord] error de red: {e}")
            return False
        if resp.status_code in (200, 204):
            return True
        if resp.status_code == 429:
            retry_after = 1.0
            try:
                retry_after = float(resp.json().get("retry_after", 1.0))
            except Exception:
                pass
            time.sleep(retry_after + 1)
            continue
        print(f"  [discord] error {resp.status_code}: {resp.text[:200]}")
        return False
    print("  [discord] maximo de reintentos alcanzado (429)")
    return False


def construir_embed(item, categoria_cfg, resumen):
    titulo = f"{categoria_cfg.get('emoji', '')} {item['titulo']}".strip()
    footer_text = item["fuente"]
    if "vistas" in item:
        footer_text += f" · {item['vistas']:,} views"
    embed = {
        "title": titulo[:256],
        "url": item["link"],
        "description": resumen[:2000],
        "color": categoria_cfg.get("color", 0),
        "footer": {"text": footer_text},
        "timestamp": item["fecha"],
    }
    if item.get("miniatura"):
        embed["image"] = {"url": item["miniatura"]}
    return embed


def purgar_archivo(archivo, dias):
    corte = datetime.now(timezone.utc) - timedelta(days=dias)
    filtrado = []
    for item in archivo:
        try:
            fecha = datetime.fromisoformat(item["fecha"])
        except Exception:
            continue
        if fecha >= corte:
            filtrado.append(item)
    return filtrado[-MAX_ARCHIVO:]


def modo_check(config_yml):
    feeds = config_yml["feeds"]
    total_ok, total_vacio, total_falla = 0, 0, 0
    for feed in feeds:
        try:
            parsed = fetch_feed(feed["url"])
            n = len(parsed.entries)
            if n == 0:
                print(f"VACIO   {feed['nombre']} (0 entries)")
                total_vacio += 1
            else:
                print(f"OK      {feed['nombre']} ({n} entries)")
                total_ok += 1
        except Exception as e:
            print(f"FALLA   {feed['nombre']} -> {e}")
            total_falla += 1
    print(f"\nResumen: {total_ok} OK, {total_vacio} vacios, {total_falla} fallas de {len(feeds)} feeds")
    sys.exit(0)


def main():
    cargar_env()

    dry_run = "--dry-run" in sys.argv
    check_mode = "--check" in sys.argv
    solo_youtube = "--solo-youtube" in sys.argv
    sembrar_youtube = "--sembrar-youtube" in sys.argv

    config_yml = cargar_feeds()
    config = config_yml.get("config", {})
    categorias = config_yml.get("categorias", {})

    if check_mode:
        modo_check(config_yml)
        return

    max_por_corrida = int(os.environ.get("MAX_POR_CORRIDA") or config.get("max_por_corrida", 12))
    resumir_con_ia = config.get("resumir_con_ia", True)

    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    gemini_model = os.environ.get("GEMINI_MODEL") or "gemini-2.5-flash"

    estado = cargar_estado()
    vistos = estado.get("vistos", [])
    vistos_set = set(vistos)
    primera_ejecucion = len(vistos) == 0

    nuevo_archivo = []
    candidatos = []
    a_publicar = []

    if sembrar_youtube:
        youtube_max_por_corrida = int(config.get("youtube_max_por_corrida", 6))
        candidatos_youtube = [
            i for i in estado.get("archivo", [])
            if i.get("categoria") == "youtube" and es_titulo_en_ingles(None, i.get("titulo", ""))
        ]
        candidatos_youtube.sort(key=lambda x: x.get("vistas", 0), reverse=True)
        a_publicar = candidatos_youtube[:youtube_max_por_corrida]
    elif solo_youtube:
        youtube_key = os.environ.get("YOUTUBE_API_KEY", "")
        youtube_max_por_corrida = int(config.get("youtube_max_por_corrida", 6))
        candidatos_youtube = procesar_youtube(config_yml, config, categorias, vistos_set, vistos, nuevo_archivo, youtube_key)
        a_publicar = candidatos_youtube[:youtube_max_por_corrida]
    else:
        antiguedad_max_horas = int(os.environ.get("MAX_AGE_HOURS") or config.get("antiguedad_max_horas", 48))
        corte = datetime.now(timezone.utc) - timedelta(hours=antiguedad_max_horas)

        for feed in config_yml.get("feeds", []):
            nombre = feed["nombre"]
            categoria = feed["categoria"]
            categoria_cfg = categorias.get(categoria, {})
            try:
                parsed = fetch_feed(feed["url"])
            except Exception as e:
                print(f"[feed] {nombre} fallo: {e}")
                continue

            for entry in parsed.entries[:MAX_ENTRIES_POR_FEED]:
                huella = huella_de(entry)
                if huella in vistos_set:
                    continue
                vistos_set.add(huella)
                vistos.append(huella)

                fecha = fecha_de(entry)
                if fecha < corte:
                    continue

                titulo = limpiar(entry.get("title", ""), 250)
                extracto = limpiar(entry.get("summary", "") or entry.get("description", ""), 450)
                link = entry.get("link", "")

                item = {
                    "titulo": titulo,
                    "link": link,
                    "fuente": nombre,
                    "categoria": categoria,
                    "fecha": fecha.isoformat(),
                    "extracto": extracto,
                }
                nuevo_archivo.append(item)

                if not categoria_cfg.get("publicar_diario", False):
                    continue
                if not pasa_filtros(categoria_cfg, titulo, extracto):
                    continue

                candidatos.append(item)

        categorias_diarias = [c for c in categorias if c != "youtube" and categorias[c].get("publicar_diario", False)]
        limite_publicacion = 3 if primera_ejecucion else max_por_corrida
        a_publicar = distribuir_por_categoria(candidatos, categorias_diarias, limite_publicacion)

    if dry_run:
        total_candidatos = len(candidatos_youtube) if (solo_youtube or sembrar_youtube) else len(candidatos)
        print(f"[dry-run] {len(a_publicar)} items se publicarian (de {total_candidatos} candidatos):")
        for item in a_publicar:
            if solo_youtube or sembrar_youtube:
                print(f"  [{item['categoria']}] ({item.get('vistas', 0):,} vistas) {item['titulo']} -> {item['link']}")
            else:
                prioridad = calcular_prioridad(item["titulo"], item["extracto"])
                print(f"  [{item['categoria']}] (prioridad={prioridad}) {item['titulo']} -> {item['link']}")
        return

    for item in a_publicar:
        categoria_cfg = categorias.get(item["categoria"], {})
        webhook_env = categoria_cfg.get("webhook_env")
        webhook_url = os.environ.get(webhook_env, "") if webhook_env else ""

        if resumir_con_ia:
            resumen = resumir_con_gemini(item["titulo"], item["extracto"], gemini_key, gemini_model)
        else:
            resumen = item["extracto"][:350]

        embed = construir_embed(item, categoria_cfg, resumen)

        if webhook_url:
            ok = publicar_discord(webhook_url, embed)
            print(f"[{'ok' if ok else 'fallo'}] {item['categoria']}: {item['titulo']}")
        else:
            print(f"[sin-webhook] {item['categoria']}: {item['titulo']}")

        time.sleep(PAUSA_ENTRE_PUBLICACIONES)

    estado["vistos"] = vistos[-MAX_VISTOS:]
    archivo_acumulado = estado.get("archivo", []) + nuevo_archivo
    estado["archivo"] = purgar_archivo(archivo_acumulado, ARCHIVO_DIAS)
    guardar_estado(estado)

    print(f"\nListo. {len(a_publicar)} publicados, {len(nuevo_archivo)} archivados, {len(vistos)} vistos totales.")


if __name__ == "__main__":
    main()
