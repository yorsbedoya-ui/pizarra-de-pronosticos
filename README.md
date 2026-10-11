# Pizarra de Pronósticos

Pronósticos de fútbol para 8 ligas (Premier, Championship, LaLiga, Serie A, Bundesliga, Ligue 1, Portugal, Eredivisie) calculados solo con datos reales.

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
