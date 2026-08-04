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
PAUSA_ENTRE_PUBLICACIONES = 1.5
USER_AGENT = "Mozilla/5.0 (compatible; AIRadarBot/1.0)"

PROMPT_RESUMEN = (
    "Resume esta noticia de inteligencia artificial en MAXIMO 2 frases, en espanol "
    "neutro, tono ejecutivo y directo, sin introducciones ni comillas. Enfocate en que "
    "cambia y por que le importa a una empresa."
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
    embed = {
        "title": titulo[:256],
        "url": item["link"],
        "description": resumen[:2000],
        "color": categoria_cfg.get("color", 0),
        "footer": {"text": item["fuente"]},
        "timestamp": item["fecha"],
    }
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

    config_yml = cargar_feeds()
    config = config_yml.get("config", {})
    categorias = config_yml.get("categorias", {})

    if check_mode:
        modo_check(config_yml)
        return

    antiguedad_max_horas = int(os.environ.get("MAX_AGE_HOURS") or config.get("antiguedad_max_horas", 48))
    max_por_corrida = int(os.environ.get("MAX_POR_CORRIDA") or config.get("max_por_corrida", 12))
    resumir_con_ia = config.get("resumir_con_ia", True)

    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    gemini_model = os.environ.get("GEMINI_MODEL") or "gemini-2.5-flash"

    estado = cargar_estado()
    vistos = estado.get("vistos", [])
    vistos_set = set(vistos)
    primera_ejecucion = len(vistos) == 0

    corte = datetime.now(timezone.utc) - timedelta(hours=antiguedad_max_horas)

    nuevo_archivo = []
    candidatos = []

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

    candidatos.sort(key=lambda x: x["fecha"], reverse=True)

    limite_publicacion = 3 if primera_ejecucion else max_por_corrida
    a_publicar = candidatos[:limite_publicacion]

    if dry_run:
        print(f"[dry-run] {len(a_publicar)} items se publicarian (de {len(candidatos)} candidatos):")
        for item in a_publicar:
            print(f"  [{item['categoria']}] {item['titulo']} -> {item['link']}")
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
