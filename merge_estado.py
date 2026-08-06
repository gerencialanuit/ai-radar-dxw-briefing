#!/usr/bin/env python3
"""Combina el state.json local (recien escrito por bot.py) con la version
mas reciente en origin/main, para no perder cambios cuando radar.yml y
youtube.yml corren cerca uno del otro y ambos modifican state.json. Se
usa en el paso de commit de ambos workflows, justo antes de git commit --
git no sabe fusionar JSON como texto, asi que el merge se hace aqui a
nivel de datos: union de vistos, union de archivo por (link, titulo)."""

import json
import subprocess

MAX_VISTOS = 2000
MAX_ARCHIVO = 1500


def cargar_remoto():
    try:
        salida = subprocess.check_output(["git", "show", "origin/main:state.json"], text=True)
        return json.loads(salida)
    except Exception:
        return {"vistos": [], "archivo": []}


def main():
    with open("state.json", encoding="utf-8") as f:
        local = json.load(f)
    remoto = cargar_remoto()

    vistos = list(dict.fromkeys(remoto.get("vistos", []) + local.get("vistos", [])))[-MAX_VISTOS:]

    por_clave = {}
    for item in remoto.get("archivo", []) + local.get("archivo", []):
        clave = (item.get("link"), item.get("titulo"))
        por_clave[clave] = item
    archivo = list(por_clave.values())[-MAX_ARCHIVO:]

    with open("state.json", "w", encoding="utf-8") as f:
        json.dump({"vistos": vistos, "archivo": archivo}, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
