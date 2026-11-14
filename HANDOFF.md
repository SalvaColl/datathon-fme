# Relevo — estado a 14 nov 2026, 14:50 UTC

Leer antes `AGENTS.md`. Este documento dice qué corre en vivo, cómo cambiarlo y qué queda por hacer antes de la final (domingo 15 nov, 10:00–12:00 CET, leaderboard oculto).

## Qué hay en vivo

- **Un único writer**: `recsys/live.py` en el Mac de Javi, desde `main` en el commit `e98815f`, arrancado a las 14:28 UTC. Nunca lanzar un segundo proceso que escriba en `team_26.submissions`; para probar, `python live.py --dry-run`.
- **Política activa**: `recsys/data/policy.json` = `{"variant": "ab_lfm"}` desde las 14:33 UTC: 50/50 por hash de usuario entre `qrank` (control) y `lfm` (modelo ajustado en vivo, `recsys/lfm.py`).
- Arranque (desde `recsys/`, con el venv): `caffeinate -i nohup ../../.venv/bin/python live.py >> data/live_main.log 2>&1 &`. Tarda unos 40 s hasta `ready`, y `lfm` empieza a responder unos 80 s después del arranque (primer refresco completo de eventos); mientras tanto su brazo cae a qrank/v1.
- El portátil no puede entrar en reposo: si se cierra la tapa se pierde todo el tráfico hasta que despierta.

## Cambiar de variante sin reiniciar

Escribir `recsys/data/policy.json`; el proceso lo relee cada ~20 s y anota `{"event": "policy", ...}` en el log.

| `variant` | Qué sirve | `model_version` |
|---|---|---|
| `v1` | GBM con candidatos (versión antigua) | `v1-gbm-cand-r1` |
| `qrank` | qrank en producto/categoría, v1 en home | `v2-qrank-r1` |
| `lfm` | lfm en todas las páginas | `v3-lfm-r1-k` / `-n` (usuario conocido / nuevo), con `h` final en home |
| `ab_lfm` | 50/50 qrank contra lfm | las anteriores |
| `aff`, `qrank_aff`, `attr`, `attr_aff` y sus `ab_*` | afinidad por descripción y ranker por atributos | ver `recsys/live.py`, bloque `VARIANTS` |

Otros interruptores, todos apagados: `data/d130.json` (`{"mode": "nodead"|"home"}`, candidatos de home, D-130), `data/lq.json` (`{"mode": "on"|"ab"}`, calidad en vivo, D-180) y `qrank_arms` dentro de `policy.json` (brazos de afinado de qrank, T-019, ver `runbook.md`).

## Etiquetas públicas (`model_version`)

El leaderboard enseña nuestras etiquetas a todos los equipos, así que no deben describir el método. Desde el commit que añade `public_label` en `recsys/live.py`, si existe `recsys/data/labels.json` (no versionado, se relee cada ~20 s) el writer escribe códigos neutros en vez de los nombres internos:

```json
{"salt": "<cadena aleatoria, solo en la máquina del writer>", "map": {"<etiqueta interna>": "<código público opcional>"}}
```

Las etiquetas que no estén en `map` reciben un código estable derivado de `salt` (`m` + 5 caracteres). Cada pareja interna/pública se anota una vez en el log (`{"event": "label", ...}`): ese log y `labels.json` son la única tabla de correspondencia; no copiarla al repositorio ni a canales públicos. Cambiar `salt` rota todos los códigos (parte la serie del leaderboard: cada código nuevo necesita ~300 peticiones para aparecer). Las variantes nuevas siguen usando nombres internos descriptivos en el código; la traducción es automática. Hasta el próximo reinicio el writer sigue escribiendo los nombres antiguos.

## Cómo medir

`https://datathon.rawtree.dev/api/state?by=model` da, por `model_version`, la conversión esperada del modelo oculto en la última hora (se recalcula cada 60 s). Desde el 14 nov ~15:20 UTC admite ventana propia: `&from=<epoch>&to=<epoch>` (segundos UTC, múltiplos de 300; mínimo 15 min, máximo 3 h; `from` solo = desde ahí hasta ahora; la respuesta trae `custom: true` y `window`). Usarla para leer un bloque exacto, por ejemplo desde el cambio de variante, en vez de la última hora. Es la medida de referencia: con unas 500–1.000 peticiones por versión ya es estable. `python recsys/compare_versions.py 60` da compras reales, mucho más ruidosas. Salud por minuto: tabla `team_26.feedback` (`served_by = 'team'` contra `fallback_reason = 'missing'`).

## Resultados medidos (modelo oculto)

Lectura de las 14:43 UTC, con lfm 10 minutos en vivo. Muestras pequeñas en lfm: repetir la lectura antes de fiarse de los decimales.

| Versión | Peticiones | Conversión | Cold | € por petición |
|---|---|---|---|---|
| lfm, producto/categoría, conocidos (`-k`) | 486 | 2,37% | 2,62% | 1,14 |
| lfm, producto/categoría, nuevos (`-n`) | 211 | 2,96% | 2,96% | 1,15 |
| lfm, home, conocidos (`-kh`) | 116 | 0,34% | — | 0,14 |
| lfm, home, nuevos (`-nh`) | 45 | 2,00% | 2,00% | 1,53 |
| qrank (producto/categoría) | 5.120 | 1,36% | 2,08% | 0,71 |
| v1 (mezcla con home) | 3.935 | 0,94% | 1,62% | 0,44 |

Referencias de la misma hora: líder 1,61%, nuestra media 1,23% (aún arrastraba v1), `baseline` ≈0,70%, `reference` ≈2,04%.

Decisión recomendada y pendiente: pasar a `{"variant": "lfm"}` al 100%.

## Volver atrás

- Política: `echo '{"variant": "qrank"}' > data/policy.json` (o `v1`).
- Código: `kill -INT <pid>`, comprobar con `pgrep -fl live.py` que no queda ninguno, `git checkout c5b1fe2` (versión anterior, sin lfm/attr/live_quality) y el mismo comando de arranque. Cada reinicio cuesta entre 1 y 2 minutos de respuestas de reserva.

## Lecciones operativas

- No ejecutar tests ni pruebas en seco en la misma máquina que el writer: le quitan CPU y se pierden peticiones (14:08 UTC: 22 servidas de 180). Validar en otra máquina y reiniciar directamente con regla de vuelta atrás a los 2 minutos.
- El writer descarta las peticiones de más de 2,5 s en vez de enviarlas tarde (`serving.py`); en régimen normal sirve 99,9% con p95 ≈1,7–2,0 s.
- No subir a `main` mientras hay un reinicio desde `main` en curso.

## Lista antes de la final

1. Reajustar los pesos de lfm con datos recientes: `cd recsys && python lfm_build.py --pull` (revisar `lfm_coef.json` y pasar `python -m unittest discover -s tests`, 104 tests).
2. Decidir home: probar `d130.json` `{"mode": "home"}` contra el home de lfm (`-kh`/`-nh`) en bloques consecutivos y quedarse con el mejor. Home de usuarios conocidos es el punto más flojo (≈0,3%).
3. Laboratorio nocturno opcional: `recsys/night_lab.py` (sección en `runbook.md`); solo cambia `policy.json`/`d130.json`.
4. Un único reinicio con el `main` final, con margen antes de las 10:00 CET, y política fijada. Portátil enchufado y sin reposo. Hacerlo con relevo (`live.py --takeover --replace-pid <pid>`, sección T-022 de `runbook.md`): el writer viejo sigue respondiendo mientras el nuevo carga, y no se pierde ninguna petición (E-220).

## Dónde está cada cosa

- Ideas, evidencia y decisiones: `insights.md`, `experiments.md`, `decisions.md` (solo se añaden entradas; hay IDs repetidos entre tareas paralelas, por ejemplo dos T-018, buscar por nombre). Tareas: `tasks.md`. Operación: `runbook.md`.
- Presentación al jurado: `presentation/` (faltan cifras finales).
- Sin fusionar a propósito: `feat/graph-recommender` (rama de otro miembro) y el renombrado de etiqueta `v4-lfm-r1` de `javi/lfm-live-fit` (se mantiene `v3-lfm-r1`, que es lo que escribe el writer).


## Optional returning-user challenger K30 (Codex, salva/k30)

Team's returning product/category priority: an optional taste-conditioned pending-cart boost is ready for review, with full instructions in [recsys/K30.md](recsys/K30.md). It differs from Javi's uniform cart weights; exact r2 coefficient clone plus a bounded score patch, no live.py/serving.py changes. Local replay: 600 real as-of requests, zero invalid slates, relevant-cart placements 1.69 ? 2.00/slate; no online conversion claim. 148 tests OK (eight Windows POSIX skips). A new branch does not update a running Python process: deployment is Javi's, with one writer. Do not overwrite active tuner settings; use the review-only planner and fixed-window reporter, then restore saved arms if worse. No live activation or main merge was performed. Latest fetched main d842407; unmerged javi/known-gap work was inspected, not merged.
