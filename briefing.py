#!/usr/bin/env python3
"""DXW Weekly Briefing. Triage y sintesis con IA bajo la lente estrategica de DOUX.WORK."""

import json
import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta

import requests
import yaml

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FEEDS_PATH = os.path.join(BASE_DIR, "feeds.yml")
STATE_PATH = os.path.join(BASE_DIR, "state.json")
ENV_PATH = os.path.join(BASE_DIR, ".env")

TAMANO_LOTE = 25
PAUSA_ENTRE_LOTES = 3
PRESELECCION_MAX = 90
COLOR_BRIEFING = 1118481

PALABRAS_DXW = [
    "agent", "agentic", "automation", "workflow", "no-code", "low-code",
    "local seo", "google business profile", "gbp", "local search", "maps",
    "aeo", "geo", "answer engine", "generative engine", "ai search",
    "review", "reputation", "testimonial", "crm", "hubspot", "salesforce",
    "twilio", "sms", "voice", "call", "receptionist", "messaging",
    "small business", "smb", "service business", "home service",
    "field service", "contractor", "api", "integration", "webhook", "mcp",
    "onboarding", "ux", "product design", "pricing", "saas", "perplexity",
    "openai", "anthropic", "claude", "gemini", "search console", "schema",
    "structured data", "citation", "lead", "funnel", "retention", "churn",
]

DXW_CONTEXT = """DOUX.WORK is an operational intelligence and implementation studio for
relationship-driven service businesses. We help owner-led companies adopt
technology that creates measurable business value through strategy,
implementation, and continuous improvement -- not by recommending software
alone. We act as an extension of our clients' teams, turning digital,
technical, and operational priorities into working solutions. Our mission is
to build repeatable systems, validate products through real client work, and
continuously improve our delivery model.

Current strategic priorities:
- Launch DOUX.WORK successfully
- Launch and improve the Review Engine MVP
- Build a repeatable client journey
- Validate our delivery model
- Productize recurring client solutions
- Create operational intelligence for service businesses
- Scale what works

Topics that matter to us: AI agents, automation, local SEO / GEO / AEO,
Google Business Profile, CRM integrations, Twilio, customer communications,
review management, small business SaaS, APIs, product design & UX, search
(Google, OpenAI, Perplexity), voice AI, workflow automation, operational
intelligence."""

PREGUNTAS_LENTE = """- Does this help us build better products?
- Does this improve how we serve service businesses?
- Could this improve our implementation process?
- Does this create a competitive advantage?
- Does this introduce a risk we should understand?
- Should we experiment with it?
- Should we ignore it?
If the answer to all of these is no, the item scores 0-3."""

PROMPT_TRIAGE = """You are a technology scout for DOUX.WORK.

{DXW_CONTEXT}

Score each item below from 0 to 10 for how much it should influence a
DOUX.WORK product, technical, or business decision this week.

Apply this lens:
{PREGUNTAS_LENTE}

Scoring guide:
9-10 = directly actionable for a current priority (Review Engine, launch,
       delivery model, client journey)
7-8  = strong strategic signal we should discuss
4-6  = worth awareness only
0-3  = generic AI news, hype, funding gossip, unrelated verticals -> discard

Be harsh. Most items deserve 0-3. Signal over noise.

ITEMS:
{listado}

Return ONLY a JSON array, no prose, no markdown fences:
[{{"i": <item number>, "score": <0-10>, "angle": "<max 12 words: why DXW cares>"}}]"""

PROMPT_SINTESIS = """You are the DOUX.WORK weekly intelligence briefing agent.

{DXW_CONTEXT}

You are a product strategist and technology scout, NOT a news reporter.
Do not summarize AI news. Filter everything through what DOUX.WORK is
building. If a development does not influence a decision, leave it out --
it is better to write a short briefing than a padded one.

Period: {desde} to {hasta}. Items reviewed this week: {revisados}.
Top-scoring items after triage:

{listado}

Write the briefing in {idioma}, in Markdown, under 900 words total,
using EXACTLY these six sections and headers:

## What happened
3 to 6 bullets. Each bullet: the development in one sentence, with the
source linked as [Source name](url). Group related items into one bullet.

## Why it matters
Explain in 2 to 4 bullets why DOUX.WORK specifically should care. Connect to
service businesses, owner-led companies, or our delivery model. No generic
industry commentary.

## DXW Impact
2 to 4 bullets on concrete influence on our products, services, operations,
or strategy. Name the affected area: Review Engine, client journey, delivery
model, positioning, pricing, tech stack.

## Opportunities
2 to 4 concrete things worth exploring, testing, or building. Each one
should be specific enough to become a ticket or an experiment.

## Risks
1 to 3 bullets. Include "none material this week" if that is honest.
Cover roadmap risk, client-value risk, platform-dependency risk.

## Recommended actions
3 to 5 items, each starting with a verb, each assignable to a person in a
Monday standup. Mark each as [SHIP], [TEST], [DISCUSS] or [WATCH].

Rules:
- Never invent facts or links. Only use what is in the items above.
- Be specific. "Explore AI agents" is useless; "Prototype a Twilio-triggered
  review request agent for the Review Engine" is useful.
- End with one line: **Bottom line:** followed by the single most important
  thing DOUX.WORK should build, improve, experiment with, or watch next."""


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


def extraer_json(texto):
    texto = re.sub(r"```(?:json)?", "", texto, flags=re.IGNORECASE)
    inicio = texto.find("[")
    fin = texto.rfind("]")
    if inicio == -1 or fin == -1 or fin < inicio:
        return []
    try:
        return json.loads(texto[inicio:fin + 1])
    except Exception:
        return []


def llamar_gemini(prompt, api_key, modelo, timeout=120, max_intentos=3):
    if not api_key:
        return None
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"
        f"?key={api_key}"
    )
    body = {"contents": [{"parts": [{"text": prompt}]}]}
    for intento in range(max_intentos):
        try:
            resp = requests.post(url, json=body, timeout=timeout)
            if resp.status_code == 429:
                print(f"  [gemini] 429, esperando {20 * (intento + 1)}s")
                time.sleep(20 * (intento + 1))
                continue
            resp.raise_for_status()
            data = resp.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:
            print(f"  [gemini] intento {intento + 1} fallo: {e}")
            time.sleep(8 * (intento + 1))
    return None


def triage(items, api_key, modelo):
    resultado = []
    lotes = [items[i:i + TAMANO_LOTE] for i in range(0, len(items), TAMANO_LOTE)]
    for idx, lote in enumerate(lotes):
        listado = "\n".join(
            f"[{i}] {it['titulo']} :: {it['fuente']} :: {it['extracto'][:220]}"
            for i, it in enumerate(lote)
        )
        prompt = PROMPT_TRIAGE.format(DXW_CONTEXT=DXW_CONTEXT, PREGUNTAS_LENTE=PREGUNTAS_LENTE, listado=listado)
        texto = llamar_gemini(prompt, api_key, modelo)
        if texto is None:
            print(f"  [triage] lote {idx + 1}/{len(lotes)} fallo, continuando")
        else:
            datos = extraer_json(texto)
            for d in datos:
                try:
                    i = int(d["i"])
                    score = float(d["score"])
                    angle = str(d.get("angle", ""))
                except Exception:
                    continue
                if 0 <= i < len(lote):
                    item = dict(lote[i])
                    item["score"] = score
                    item["angle"] = angle
                    resultado.append(item)
        if idx < len(lotes) - 1:
            time.sleep(PAUSA_ENTRE_LOTES)
    return resultado


def sintetizar(finalistas, desde, hasta, revisados, idioma, api_key, modelo):
    listado = "\n".join(
        f"{n}. {it['titulo']}\n"
        f"   Source: {it['fuente']} | Date: {it['fecha'][:10]} | Score: {it['score']}\n"
        f"   Scout angle: {it['angle']}\n"
        f"   URL: {it['link']}\n"
        f"   Extract: {it['extracto'][:400]}"
        for n, it in enumerate(finalistas, start=1)
    )
    prompt = PROMPT_SINTESIS.format(
        DXW_CONTEXT=DXW_CONTEXT, desde=desde, hasta=hasta, revisados=revisados, listado=listado, idioma=idioma
    )
    return llamar_gemini(prompt, api_key, modelo, timeout=120)


def trocear(texto, limite):
    if len(texto) <= limite:
        return [texto]
    bloques = []
    actual = ""
    for parrafo in texto.split("\n\n"):
        candidato = (actual + "\n\n" + parrafo) if actual else parrafo
        if len(candidato) > limite:
            if actual:
                bloques.append(actual)
                actual = ""
            if len(parrafo) > limite:
                for i in range(0, len(parrafo), limite):
                    bloques.append(parrafo[i:i + limite])
            else:
                actual = parrafo
        else:
            actual = candidato
    if actual:
        bloques.append(actual)
    return bloques


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


def mensaje_sin_senal(revisados):
    return (
        "No developments this week cleared the DXW relevance threshold.\n\n"
        "**Bottom line:** Nothing external should change the roadmap. Keep shipping.\n"
        f"({revisados} items reviewed)"
    )


def publicar_briefing(bloques, desde, hasta, revisados, cleared, webhook_url, dry_run):
    if dry_run:
        print(f"[dry-run] DXW Weekly AI Briefing — {desde} to {hasta}")
        print(f"[dry-run] {revisados} items reviewed · {cleared} cleared triage\n")
        for bloque in bloques:
            print(bloque)
            print()
        return

    for idx, bloque in enumerate(bloques):
        if idx == 0:
            embed = {
                "title": f"🎯 DXW Weekly AI Briefing — {desde} to {hasta}",
                "description": bloque,
                "color": COLOR_BRIEFING,
                "footer": {"text": f"{revisados} items reviewed · {cleared} cleared triage"},
            }
        else:
            embed = {"description": bloque, "color": COLOR_BRIEFING}

        if webhook_url:
            ok = publicar_discord(webhook_url, embed)
            print(f"[{'ok' if ok else 'fallo'}] bloque {idx + 1}/{len(bloques)}")
        else:
            print("[sin-webhook] briefing no publicado")
        time.sleep(1.5)


def main():
    cargar_env()
    dry_run = "--dry-run" in sys.argv

    config_yml = cargar_feeds()
    config = config_yml.get("config", {})

    briefing_dias = config.get("briefing_dias", 7)
    briefing_max_items = config.get("briefing_max_items", 12)
    briefing_score_minimo = config.get("briefing_score_minimo", 6)
    briefing_idioma_cfg = config.get("briefing_idioma", "en")
    idioma = "English" if briefing_idioma_cfg == "en" else "Spanish (neutral, executive tone)"

    estado = cargar_estado()
    archivo = estado.get("archivo", [])

    hasta_dt = datetime.now(timezone.utc)
    corte = hasta_dt - timedelta(days=briefing_dias)
    desde = corte.strftime("%Y-%m-%d")
    hasta = hasta_dt.strftime("%Y-%m-%d")

    items = []
    for it in archivo:
        try:
            fecha = datetime.fromisoformat(it["fecha"])
        except Exception:
            continue
        if fecha >= corte:
            items.append(it)

    if not items:
        print("[briefing] archivo vacio: no hay items en la ventana de tiempo. Nada que publicar.")
        return

    revisados = len(items)
    webhook_url = os.environ.get("WEBHOOK_DXW_BRIEFING", "")

    puntuados = []
    for it in items:
        texto = (it["titulo"] + " " + it["extracto"]).lower()
        score = sum(1 for palabra in PALABRAS_DXW if palabra in texto)
        if it.get("categoria") == "dxw":
            score += 2
        if score > 0:
            puntuados.append((score, it))
    puntuados.sort(key=lambda x: x[0], reverse=True)
    preseleccion = [it for _, it in puntuados[:PRESELECCION_MAX]]

    if not preseleccion:
        bloques = [mensaje_sin_senal(revisados)]
        publicar_briefing(bloques, desde, hasta, revisados, 0, webhook_url, dry_run)
        return

    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    modelo_triage = os.environ.get("GEMINI_MODEL_TRIAGE") or "gemini-2.5-flash"
    modelo_briefing = os.environ.get("GEMINI_MODEL_BRIEFING") or "gemini-2.5-flash"

    triados = triage(preseleccion, gemini_key, modelo_triage)
    finalistas = [it for it in triados if it["score"] >= briefing_score_minimo]
    finalistas.sort(key=lambda x: x["score"], reverse=True)
    finalistas = finalistas[:briefing_max_items]

    if not finalistas:
        bloques = [mensaje_sin_senal(revisados)]
        publicar_briefing(bloques, desde, hasta, revisados, 0, webhook_url, dry_run)
        return

    texto_briefing = sintetizar(finalistas, desde, hasta, revisados, idioma, gemini_key, modelo_briefing)
    if not texto_briefing:
        texto_briefing = (
            "No se pudo generar la sintesis esta semana por un error tecnico con el modelo de IA.\n\n"
            "**Bottom line:** Revisar manualmente los items de la semana; el modelo de sintesis fallo."
        )

    bloques = trocear(texto_briefing.strip(), 3800)
    publicar_briefing(bloques, desde, hasta, revisados, len(finalistas), webhook_url, dry_run)


if __name__ == "__main__":
    main()
