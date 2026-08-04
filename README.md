# AI Radar + DXW Weekly Briefing

## 1. Qué hace este sistema

Este sistema lee automáticamente ~34 fuentes de noticias sobre inteligencia
artificial y negocios, y publica lo más relevante en cuatro canales de
Discord. Cada mañana laboral recibes noticias de lanzamientos, análisis y
negocios; cada viernes recibes además un briefing estratégico de una página
escrito con la perspectiva de DOUX.WORK, que filtra el ruido y solo destaca
lo que realmente debería influir en una decisión. Todo corre gratis en la
infraestructura de GitHub, sin servidores ni mantenimiento.

## 2. Los 4 canales de Discord

| Canal | Qué recibe | Frecuencia |
|---|---|---|
| `#ai-releases` | Anuncios oficiales de laboratorios de IA (OpenAI, Anthropic, Google, Meta, Hugging Face...) | 2 veces al día (8:00 a.m. y 4:00 p.m. EST), lunes a viernes |
| `#ai-news` | Noticias y análisis generales de IA (TechCrunch, The Verge, MIT Tech Review...) | 2 veces al día (8:00 a.m. y 4:00 p.m. EST), lunes a viernes |
| `#ai-business-growth` | IA aplicada a negocios, marketing y crecimiento | 2 veces al día (8:00 a.m. y 4:00 p.m. EST), lunes a viernes |
| `#dxw-ai-briefing` | Briefing semanal estratégico, filtrado con la lente de DOUX.WORK | Viernes 8:00 a.m. EST |

> **Nota sobre "EST":** GitHub Actions programa en UTC fijo, sin ajuste
> automático por horario de verano. Estos horarios están fijados a UTC-5
> (el mismo offset que hora Colombia todo el año, y que EST en invierno).
> Si literalmente quieres que sea hora del Este de EE.UU. con horario de
> verano (UTC-4 de marzo a noviembre), avísame para ajustar el cron dos
> veces al año.

## 3. Cómo crear los 5 GitHub Secrets

Ve a tu repositorio en GitHub → pestaña **Settings** → **Secrets and
variables** → **Actions** → botón **New repository secret**. Crea estos 5
secretos, uno por uno, con el nombre EXACTO de la primera columna:

| Nombre del secreto | Qué valor va aquí |
|---|---|
| `WEBHOOK_AI_RELEASES` | URL del webhook del canal `#ai-releases` |
| `WEBHOOK_AI_NEWS` | URL del webhook del canal `#ai-news` |
| `WEBHOOK_AI_BUSINESS` | URL del webhook del canal `#ai-business-growth` |
| `WEBHOOK_DXW_BRIEFING` | URL del webhook del canal `#dxw-ai-briefing` |
| `GEMINI_API_KEY` | Tu clave de Google AI Studio (nivel gratuito) |

**⚠️ Advertencia importante:** en Discord, si creaste los 4 webhooks con el
mismo nombre (por ejemplo "AI Radar"), se van a ver idénticos en la lista de
integraciones. **No copies las URLs de memoria ni por el orden en que
aparecen.** Entra a cada canal individualmente (`#ai-releases`,
`#ai-news`, etc.), abre su webhook desde **Configuración del canal → 
Integraciones → Webhooks**, y copia la URL desde ahí. Si mezclas las URLs,
las noticias van a llegar al canal equivocado.

Para crear un webhook en Discord: entra al canal → ⚙️ Editar canal →
Integraciones → Webhooks → Nuevo Webhook → Copiar URL del Webhook.

Para conseguir tu `GEMINI_API_KEY`: entra a [Google AI Studio](https://aistudio.google.com/apikey),
inicia sesión y genera una API key gratuita.

## 4. Cómo correr cada workflow desde la pestaña Actions

No necesitas terminal ni saber programar. Todo se hace desde el navegador:

1. Entra a tu repositorio en GitHub.
2. Haz clic en la pestaña **Actions** (arriba, junto a "Code" y "Pull requests").
3. En la lista de la izquierda verás tres workflows: **AI Radar -> Discord**,
   **DXW Weekly Briefing** y **Herramientas**.
4. Haz clic en el que quieras correr.
5. Haz clic en el botón **Run workflow** (arriba a la derecha, con un menú
   desplegable).
6. Si el workflow tiene opciones (como "modo" o "horas"), elígelas ahí mismo.
7. Haz clic en el botón verde **Run workflow** para confirmar.
8. Espera unos segundos y refresca la página: verás la corrida en la lista,
   con un ícono amarillo (corriendo), verde (éxito) o rojo (falló).
9. Haz clic sobre la corrida para ver los detalles y el log paso a paso.

## 5. Cómo sembrar el archivo antes del primer briefing

El briefing semanal necesita historial de noticias para poder analizarlo.
Si nunca has corrido el radar, el `archivo` está vacío. Para llenarlo con
una semana completa de noticias antes del primer briefing:

1. Ve a **Actions** → **AI Radar -> Discord** → **Run workflow**.
2. En el campo **horas**, escribe `168` (equivale a 7 días).
3. Ejecuta. Esto va a traer una semana de noticias y guardarlas en el
   archivo (aunque solo publique 3 en Discord, por ser la primera corrida).
4. A partir de ahí, el radar sigue corriendo normal 2 veces al día y el
   archivo se va llenando solo.

## 6. Tabla de calibración

Si algo no te gusta de lo que llega a Discord, ajusta `feeds.yml` (edítalo
directamente en GitHub, botón del lápiz ✏️, y luego "Commit changes"):

| Problema | Qué cambiar en `feeds.yml` |
|---|---|
| Demasiadas noticias | `max_por_corrida: 12` → `6` |
| Llegan cosas irrelevantes | Añadir palabras a `excluir` |
| Llegan muy pocas | Quitar palabras de `incluir` |
| Briefing con relleno | `briefing_score_minimo: 6` → `7` |
| Briefing vacío o de 2 líneas | `briefing_score_minimo: 6` → `5` |
| Briefing en español | `briefing_idioma: en` → `es` |

## 6.1 Cómo se decide qué se publica cuando hay más noticias que cupo

Cada corrida solo publica hasta `max_por_corrida` noticias (12 por defecto).
Ese cupo **se reparte entre los 3 canales diarios por turnos** (releases,
news, business, releases, news, business...), así que ningún canal se queda
en cero solo porque otro tuvo una ráfaga de noticias — cada uno se lleva su
parte, y si un canal no tiene suficientes noticias nuevas ese cupo sobrante
pasa a los demás en vez de perderse.

Dentro de cada canal, tampoco gana simplemente lo más reciente — cada
noticia recibe un puntaje de prioridad y gana la que más puntúa:

- **+1 punto** por cada palabra de una lista de ~55 temas que le importan a
  DOUX.WORK (agentes de IA, automatización, local SEO/GEO/AEO, Google
  Business Profile, CRM, Twilio, voz, review management, SaaS, APIs, UX,
  etc. — la misma lista que usa el Briefing semanal).
- **+10 puntos extra** si la noticia menciona "Claude" o "Anthropic" —
  prácticamente garantiza que gane cupo frente a noticias genéricas de IA
  dentro de su mismo canal.
- Si dos noticias empatan en puntaje, gana la más reciente (como antes).

Esto significa que una noticia relevante para DOUX.WORK o sobre Claude no
se pierde solo porque llegó al mismo tiempo que una ráfaga de noticias
genéricas de otra fuente — ni dentro de su canal, ni porque otro canal se
haya comido todo el cupo. Si quieres agregar o quitar temas de esa lista,
edita `PALABRAS_PRIORIDAD` en `bot.py` (requiere tocar código, no solo
`feeds.yml`).

## 7. Cómo desactivar un feed muerto

Si una fuente empieza a fallar seguido (revisa `python bot.py --check` desde
el workflow **Herramientas**), puedes apagarla sin borrarla: comenta sus 3
líneas con `#` en `feeds.yml`. Ejemplo:

```yaml
  # - nombre: "Feed que ya no funciona"
  #   url: "https://ejemplo.com/feed"
  #   categoria: news
```

## 8. Troubleshooting

| Síntoma | Qué hacer |
|---|---|
| El workflow aparece en rojo (falló) | Haz clic en la corrida → abre el paso rojo → lee el error. Casi siempre es un secreto mal copiado o un feed caído. |
| No llega nada a Discord | Revisa que los 4 webhooks estén bien configurados como Secrets (paso 3) y que las URLs no estén invertidas entre canales. |
| Las noticias llegan al canal equivocado | Probablemente mezclaste las URLs de los webhooks al crearlos. Vuelve a copiar cada una desde su canal específico. |
| El briefing dice "archivo vacío" | Aún no hay historial. Sigue el paso 5 (sembrar con `horas: 168`) y espera a que el radar corra al menos una vez más. |
| El cron dejó de correr solo | GitHub apaga los workflows automáticos si el repositorio está 60 días sin actividad. Cada corrida del radar hace un commit a `state.json`, lo cual mantiene el repo "activo" — si ves que dejó de correr, entra a Actions y dale "Run workflow" manualmente una vez para reactivarlo. |

## 9. Notas sobre las fuentes

- **"Anthropic News (mirror)"** y **"Claude Blog (mirror)"** no son fuentes
  oficiales: Anthropic no publica RSS propio, así que usamos el espejo
  comunitario [github.com/Olshansk/rss-feeds](https://github.com/Olshansk/rss-feeds)
  (mismo proyecto que usamos para Meta AI Blog). Originalmente "Anthropic
  News (mirror)" apuntaba a `rsshub.bestblogs.dev`, pero esa fuente estaba
  entregando solo 1 item desactualizado (última noticia de una semana
  atrás) — se reemplazó por el mirror de Olshansk, que trae el historial
  completo y se actualiza al día. "Claude Blog (mirror)" es nuevo: cubre el
  blog de producto de Claude (modelos, MCP, diseño), que antes no se
  rastreaba — solo teníamos "Claude Code — Releases", que son notas de
  versión del CLI, no del blog general.
- **"Meta AI Blog (mirror)"** usa el mismo proyecto comunitario, porque
  `ai.meta.com` no expone RSS propio. Los tres mirrors de Olshansk
  (Anthropic, Claude, Meta) comparten el mismo riesgo: si ese repo se cae o
  deja de mantenerse, las tres fuentes fallan juntas.
- **"BrightLocal (Local SEO)"** cambió de URL: su feed se movió de
  `/blog/feed/` a `/resources/feed/`. Si vuelve a fallar, revisa si movieron
  la ruta otra vez.
- **"a16z"** y **"MarkTechPost"** están comentadas en `feeds.yml` (no
  desactivadas por accidente): a16z ya no publica RSS en ningún path
  conocido, y MarkTechPost bloquea tráfico automatizado con Cloudflare
  (403 sin importar la URL). Si alguna vuelve a estar disponible, descomenta
  sus 3 líneas.
- Es normal que 1-2 de los 32 feeds activos fallen ocasionalmente (sitios
  caídos, cambios de URL, etc.). El sistema sigue funcionando con el resto.

## 10. Un briefing corto es correcto, no una falla

El Agente B (`briefing.py`) actúa como estratega, no como resumidor de
noticias. Si en una semana nada cumple el umbral de relevancia para
DOUX.WORK, el sistema publica un mensaje corto diciendo que no hay señal
relevante, en vez de inventar contenido para rellenar. Eso es
comportamiento deseado: preferimos un briefing corto y honesto a uno largo
y con relleno.

---

## Notas técnicas (para quien mantenga el código)

- Stack: Python 3.12, sin frameworks — solo `feedparser`, `requests` y
  `PyYAML`.
- `state.json` se commitea automáticamente en cada corrida del radar; esto
  también evita que GitHub desactive los cron por inactividad (ocurre a los
  60 días sin commits).
- Degradación elegante: si `GEMINI_API_KEY` falta o la llamada a Gemini
  falla, se publica el extracto original truncado en vez de abortar.
- Fecha de un item cuando el feed no trae `published`/`updated`: se usa la
  hora actual, para no descartarlo por antigüedad incorrectamente (decisión
  tomada por ambigüedad en la especificación).
- El índice `[i]` del triage (`briefing.py`) es local a cada lote de 25
  items, no global sobre todo el archivo.
