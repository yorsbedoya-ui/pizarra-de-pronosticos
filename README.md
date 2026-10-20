# Pizarra de Pronósticos

Pronósticos de fútbol para 9 ligas (Premier, Championship, LaLiga, Serie A, Bundesliga, Ligue 1, Portugal, Eredivisie y Ekstraklasa) calculados solo con datos reales.

**Web:** https://yorsbedoya-ui.github.io/pizarra-de-pronosticos/

## Cómo funciona (todo automático en GitHub Actions)

| Workflow | Cuándo | Qué hace |
|---|---|---|
| Resultados (cada hora) | :07 | Resultados y estadísticas (tiros a puerta, tiros, posesión, córners) desde ESPN → `data/live/` |
| Cuotas y estadísticas (diario) | 07:17 | Resultados, tiros, tarjetas y cuotas de football-data.co.uk (4 temporadas) → `data/fd/` |
| Web (cada hora) | :27 | Modelo Dixon-Coles + Elo + tiros + cuotas de mercado, backtest sin mirar el futuro, historial en vivo → `web/` y GitHub Pages |

- `app/pronosticos.py`: el modelo. `app/template.html`: la página.
- `data/historial.json`: cada pick ≥ 85 % publicado y su resultado real.
- Las probabilidades no son garantías.

### Datos de xG
| xG Understat (diario) | 04:43 | xG real por partido de las 5 grandes ligas (paquete abierto `soccerdata`) → `data/xg/`. El modelo lo usa en vez de los tiros en esas ligas: en el backtest de 2026 mejoró "ambos marcan" (57,2 % → 57,9 %) y el modelo de goles; en ganador y +2,5 siguen mandando las cuotas. |

### Competiciones europeas
| Europa (Champions, Europa y Conference) | cada 2 h | Resultados, estadísticas y calendario de ESPN desde 2023 → `data/europa/`. |

Para estos partidos no hay cuotas gratuitas, así que se usa un **Elo europeo propio**: un único Elo para todos los clubes, alimentado por 19 ligas (las 9 de la app más Bélgica, Escocia, Turquía, Grecia, Austria, Suiza, Dinamarca, Noruega, Suecia y Rumanía, solo como conexión) y los partidos europeos. Backtest sin mirar el futuro (621 partidos europeos de 2025-26 y 2026-27): ganador 58 %, picks seguros ≥ 85 % aciertan el 90 %.
