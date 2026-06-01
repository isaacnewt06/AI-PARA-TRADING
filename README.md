# TELEGRAM_TRADING_BRAIN

TELEGRAM_TRADING_BRAIN es una plataforma profesional para extraer conocimiento de canales de Telegram relacionados con trading, persistirlo con trazabilidad, procesarlo en una base estructurada y dejar preparado el camino hacia análisis con IA, backtesting y futura ejecución en MetaTrader 5.

## Propósito

El proyecto está diseñado como una base seria de producto, no como un simple descargador:

- Conecta con uno o varios canales a los que tu cuenta ya tiene acceso.
- Extrae mensajes y archivos con reanudación segura.
- Guarda metadatos y contenido en disco + SQLite.
- Procesa texto, PDF, DOCX y XLSX.
- Construye una knowledge base local con chunking y consultas iniciales.
- Añade una Fase 2 con embeddings locales, retrieval híbrido, extracción estructurada de reglas y playbooks.
- Deja interfaces limpias para LLMs, embeddings remotos, transcripción, backtesting y MT5.

## Arquitectura

La solución separa responsabilidades por capas:

- `src/core`: configuración, logging, rutas y excepciones.
- `src/db`: ORM, sesión y repositorios.
- `src/telegram`: cliente Telethon, resolución de canales, descarga y sincronización.
- `src/processing`: limpieza, clasificación, extracción básica de entidades y procesamiento de activos.
- `src/knowledge`: chunking persistente, recuperación local y placeholders de reglas/playbooks.
- `src/knowledge`: chunking, embeddings locales, índice vectorial, retrieval híbrido, reglas estructuradas, clustering, playbooks y resúmenes por módulos.
- `src/ai`: contratos agnósticos para LLM, embeddings y transcripción.
- `src/trading`: puentes preparados para strategy builder, backtesting y MT5.
- `src/application`: orquestación de casos de uso.
- `src/cli`: interfaz de comandos profesional con Typer.

## Flujo de Fase 1

1. Autenticación con Telegram mediante Telethon.
2. Registro de canales objetivo en la base local.
3. Sincronización full o incremental de mensajes y archivos.
4. Descarga a `data/raw/telegram/<canal>/...`.
5. Persistencia de metadatos en SQLite.
6. Procesamiento de mensajes y documentos.
7. Construcción de `content_chunks` para consulta local.

## Flujo de Fase 2

1. Generación de embeddings locales para `content_chunks`.
2. Persistencia del índice vectorial en SQLite (`chunk_embeddings`) y manifiesto local en `data/vector_store/`.
3. Retrieval híbrido keyword + semantic.
4. Extracción estructurada de reglas de trading desde los chunks.
5. Agrupación de reglas similares en `rule_clusters`.
6. Generación de playbooks por estrategia en `strategy_playbooks`.
7. Resumen de documentos/cursos por módulos en `course_module_summaries`.
8. Exportación de un dataset base para backtesting en `backtest_dataset_rows`.

## Filtro de Calidad

Antes de embeddings, extracción de reglas y compilación de setups, el sistema puede puntuar y filtrar `content_chunks` para evitar aprender de ruido. Cada chunk conserva `quality_score`, `source_weight`, `usefulness_score`, `quality_label`, `quality_flags_json` y `filtered_out`.

El filtro prioriza estructura operativa, ejemplos reales, reglas claras, gestión de riesgo y conceptos técnicos. Penaliza spam/promoción, contenido genérico/motivacional, baja densidad informativa y duplicados exactos o semánticos.

## Priorización de Documentos

Para acelerar la extracción de reglas, los archivos catalogados también pueden rankearse por probabilidad de contener trading operable.

Cada `FileAsset` puede conservar:

- `knowledge_density_score`
- `strategy_probability_score`
- `priority_score`
- `priority_notes`

El priorizador da más peso a:

- términos técnicos como `BOS`, `FVG`, `OB`, `liquidity`
- presencia de `SL`, `TP`, `RR`, riesgo y confirmaciones
- timeframes, sesiones y contexto operativo
- formatos documentales procesables

Y penaliza:

- promoción, contenido VIP/genérico
- software o ejecutables
- archives pesados con poco contexto útil
- tamaños poco informativos frente a ruido

## Selección Inteligente de Archives

Los ZIP/RAR/7z ya no se procesan por orden bruto ni solo por tamaño. El sistema calcula una selección avanzada usando:

- `archive_contents` inspeccionados sin extraer todo el archive
- nombre del archivo
- caption o texto del mensaje
- estructura interna por módulos, clases y sesiones
- mezcla de documentos, videos e imágenes
- señales de software, cracks, ejecutables y basura
- duplicados internos y similitud entre archives
- conceptos recurrentes ya detectados en la KB

Campos persistidos en `files`:

- `archive_selection_score`
- `archive_usefulness_label`
- `archive_selection_reason`
- `archive_processing_recommendation`
- `archive_internal_structure_score`
- `archive_educational_score`
- `archive_strategy_score`
- `archive_similarity_group`
- `duplicate_cluster_id`
- `duplicate_confidence`

Etiquetas típicas:

- `high_value_course`
- `likely_document_bundle`
- `likely_video_course`
- `mixed_educational`
- `tooling_or_software`
- `duplicate_or_low_value`
- `huge_low_priority`
- `unknown_needs_manual_review`

Recomendaciones operativas:

- `process_now`
- `process_documents_only`
- `inspect_first`
- `process_videos_later`
- `skip_for_now`
- `manual_review`

## Flujo de Fase 3

Fase 3 convierte la knowledge base semántica en una capa operativa cuantificable:

1. `extracted_rules` se normalizan en `normalized_rules`.
2. La ontología interna estandariza conceptos, sesiones, timeframes, stops, take profits y familias estratégicas.
3. Cada regla normalizada se convierte en `quantifiable_conditions`.
4. `strategy_builder` compila reglas compatibles en `strategy_candidates`.
5. `candidate_components` conserva cómo se armó cada setup.
6. `rule_quality_scores` y `setup_quality_scores` evalúan completitud, claridad, cuantificabilidad y trazabilidad.
7. `backtest_bridge` exporta estrategias compiladas a JSON/CSV listas para conectar OHLCV en Fase 4.
8. `strategy_pattern_detector` agrupa reglas repetidas por conceptos, timeframe, sesión y tipo de entrada para materializar `top_strategies_detected`.

## Fase 4: Backtesting Formal

La Fase 4 toma los specs exportados en `data/backtests/specs/*.json` y los prueba contra OHLCV históricos cargados desde CSV locales.

Estructura usada:

- `data/backtests/input/`: OHLCV CSV de entrada
- `data/backtests/specs/`: specs exportados desde blueprints ejecutables
- `data/backtests/results/`: resultados JSON y detalle de trades CSV
- `data/backtests/reports/`: reportes Markdown por estrategia

Formato CSV esperado:

```csv
time,open,high,low,close,volume
2026-01-01T13:00:00Z,2635.1,2637.2,2633.8,2636.5,1200
```

Convención de nombres:

- `XAUUSDm_M5.csv`
- `XAUUSDm_M1.csv`
- `XAUUSDm_H1.csv`
- `EURUSDm_H1.csv`

Compatibilidad opcional:

- `XAUUSD_M5.csv`
- `XAUUSD_M1.csv`
- `XAUUSD_H1.csv`

Capacidades actuales del motor:

- simulación conservadora basada en velas OHLCV
- filtro de sesión `new_york` y `london`
- contexto HTF `H1`
- entrada `M5` o `M1` cuando existe CSV compatible
- proxies cuantificables para bias, order block, rechazo, entrada, SL, TP y RR mínimo
- exportación de:
  - métricas agregadas
  - detalle de trades
  - reporte Markdown

Limitaciones explícitas de esta fase:

- no usa datos tick ni book
- no ejecuta operaciones reales
- si `SL` y `TP` tocan en la misma vela, asume primero `SL`
- `BOS`, `OB`, rechazo y liquidez usan heurísticas conservadoras sobre OHLCV
- si falta `H1`, el motor lo reagrupa desde el timeframe menor disponible
- los timestamps se interpretan como UTC si el CSV no trae zona horaria

Flujo recomendado:

```powershell
python -m src.cli.main export-mt5-ohlcv --symbol XAUUSDm --bars 50000
python -m src.cli.main generate-relaxed-filtered-ob-backtest
python -m src.cli.main generate-robust-ob-backtests
python -m src.cli.main export-blueprint-backtests
python -m src.cli.main run-blueprint-backtests
python -m src.cli.main analyze-backtest-results
python -m src.cli.main optimize-ob-rejection
```

Para Exness, el símbolo principal priorizado por los specs es `XAUUSDm`. Si el histórico local todavía usa el nombre clásico `XAUUSD`, el backtester intenta resolver ambos nombres automáticamente.

Diagnóstico post-backtest:

- `python -m src.cli.main analyze-backtest-results`

Artefactos generados:

- `data/backtests/reports/backtest_diagnostics.md`
- `data/backtests/results/backtest_diagnostics.json`
- `data/backtests/optimization/ob_rejection_optimization_results.json`
- `data/backtests/optimization/ob_rejection_optimization_report.md`
- `data/backtests/optimization/top_candidates.csv`

El diagnóstico descompone resultados por sesión, hora, día, dirección, timeframe, banda ATR, tamaño de vela de confirmación, RR obtenido y rachas de pérdidas. También incluye una sección comparativa centrada en `Relaxed`, `Balanced` y `Balanced v2`.

Optimización cuantitativa:

- `python -m src.cli.main generate-relaxed-filtered-ob-backtest`
- `python -m src.cli.main generate-robust-ob-backtests`
- `python -m src.cli.main export-mt5-ohlcv --symbol XAUUSDm --bars 50000`
- `python -m src.cli.main export-mt5-ohlcv-range --symbol XAUUSDm --from-date 2025-01-01 --to-date 2025-12-31`
- `python -m src.cli.main optimize-ob-rejection`
- `python -m src.cli.main run-yearly-backtest --symbol XAUUSDm --year 2025 --initial-capital 500`

`export-mt5-ohlcv` exporta histórico real desde MT5 hacia `data/backtests/input` y prioriza `XAUUSDm`.

`export-mt5-ohlcv-range` exporta OHLCV por rango UTC y genera archivos como:

- `data/backtests/input/XAUUSDm_M1_2025.csv`
- `data/backtests/input/XAUUSDm_M5_2025.csv`
- `data/backtests/input/XAUUSDm_H1_2025.csv`

`run-yearly-backtest` usa la estrategia aprobada `OB Rejection Short Only Trailing ATR v3`, simula capital real con riesgo por trade y genera:

- `data/backtests/yearly/<year>_monthly_report.csv`
- `data/backtests/yearly/<year>_summary.json`
- `data/backtests/yearly/<year>_report.md`
- `data/backtests/yearly/comparison_2024_2025.md`

`optimize-ob-rejection` ahora está enfocado exclusivamente en `OB Rejection Short Only Trailing ATR`, con validación:

- month-by-month
- rolling `70/30`
- walk-forward por bloques

La lógica penaliza:

- pocas operaciones
- drawdown alto
- rachas de pérdidas largas
- profit factor in-sample que colapsa fuera de muestra

La salida prioriza robustez sobre curve fitting. Si ningún candidato supera los umbrales mínimos, el reporte lo marca explícitamente y recomienda seguir optimizando antes de paper trading o MT5.

Paper trading controlado:

- `python -m src.cli.main run-paper-trading --symbol XAUUSDm --dry-run`

Este comando no usa `order_send` ni abre operaciones reales. Solo:

- lee `XAUUSDm` desde MT5 en modo read-only
- analiza `M1`, `M5` y `H1`
- aplica la configuración aceptada de `OB Rejection Short Only Trailing ATR v3`
- genera señales ficticias y estado virtual de trades en:
  - `data/paper_trading/signals.csv`
  - `data/paper_trading/open_paper_trades.json`
  - `data/paper_trading/closed_paper_trades.csv`
  - `data/paper_trading/paper_report.md`

El modo `--dry-run` hace una pasada única y deja el sistema listo para monitoreo demo sin riesgo.

Variantes de robustez fuera de muestra:

- `OB Rejection Short Only`
- `OB Rejection Long Only`
- `OB Rejection Short Only Partial 1R 2R`
- `OB Rejection Short Only Break Even`
- `OB Rejection Short Only Trailing ATR`
- `OB Rejection Long Only Partial 1R 2R`
- `OB Rejection Long Only Break Even`
- `OB Rejection Long Only Trailing ATR`

Cada trade exportado ahora conserva metadata real para diagnóstico:

- `ob_detected`
- `htf_bias`
- `rejection_type`
- `confirmation_band`
- `atr_band`
- `session`
- `hour_utc`
- `direction`
- `entry_reason`
- `exit_reason`

### Variante Relajada Experimental

También existe una variante separada para validación inicial:

- `OB Rejection Relaxed Validation`

No reemplaza la estrategia principal. Sirve para backtesting exploratorio con filtros más permisivos:

- `session_filter = any_session`
- `rr_min = 1.2`
- confirmación por cualquiera de:
  - `strong_rejection_candle`
  - `wick_rejection`
  - `displacement_candle`
- entrada en apertura de la vela siguiente al rechazo
- order block reciente dentro de las últimas 20 velas
- bias HTF relajado con `EMA50` o swings simples
- `risk_per_trade = 0.5%`

Comando:

```powershell
python -m src.cli.main generate-relaxed-ob-backtest
```

Artefactos generados:

- `data/knowledge/strategy_blueprints/ob_rejection_relaxed_validation.md`
- `data/backtests/specs/ob_rejection_relaxed_validation.json`

### Variante Intermedia Balanceada

También existe una variante intermedia para validación con menos ruido que la relajada:

- `OB Rejection Balanced Validation`

Objetivo:

- mantener suficientes operaciones para backtesting
- reducir entradas débiles de la variante relajada

Reglas clave:

- sesiones: `london` y `new_york`
- bias HTF: `close` respecto a `EMA50` y pendiente de `EMA50`
- order block reciente dentro de las últimas `30` velas
- confirmación mínima de `2 de 3`:
  - `wick_rejection`
  - `displacement_candle`
  - `close_back_inside_structure`
- entrada en la apertura de la siguiente vela
- `SL = extremo del OB + 0.10 ATR(14)`
- `TP = liquidez previa si existe o RR fijo 1.5`
- filtro de volatilidad:
  - descarta ATR por debajo del percentil 30 de las últimas 100 velas
  - descarta velas con rango proxy demasiado alto frente a ATR

Comando:

```powershell
python -m src.cli.main generate-balanced-ob-backtest
```

Artefactos generados:

- `data/knowledge/strategy_blueprints/ob_rejection_balanced_validation.md`
- `data/backtests/specs/ob_rejection_balanced_validation.json`

### Variante Balanceada v2

La variante `OB Rejection Balanced v2` añade dos perfiles de take profit para comparar sensibilidad de salida sin romper el resto del pipeline:

- `OB Rejection Balanced v2 RR12`
- `OB Rejection Balanced v2 RR15`

Cambios principales:

- confirmación `2 de 3` mantenida
- banda de ATR entre percentiles `20` y `90`
- ventana de sesión `london` + `new_york`, con prioridad conceptual para la hora posterior a apertura NY
- entrada en apertura siguiente, pero con retroceso mínimo `25%` si la vela de confirmación es demasiado grande
- dos specs formales separadas para comparar `RR 1.2` y `RR 1.5`

Comando:

```powershell
python -m src.cli.main generate-balanced-v2-ob-backtest
```

Artefactos generados:

- `data/knowledge/strategy_blueprints/ob_rejection_balanced_v2_rr12.md`
- `data/knowledge/strategy_blueprints/ob_rejection_balanced_v2_rr15.md`
- `data/backtests/specs/ob_rejection_balanced_v2_rr12.json`
- `data/backtests/specs/ob_rejection_balanced_v2_rr15.json`

## Detección de Estrategias Relevantes

El detector de estrategias toma `normalized_rules`, `strategy_candidates`, `rule_quality_scores` y `setup_quality_scores` para encontrar patrones fuertes que se repiten en el canal.

Agrupa por:

- familia estratégica
- conceptos dominantes como `BOS`, `FVG`, `OB`, `liquidity_sweep`
- timeframe operativo
- sesión dominante
- tipo de entrada

Luego calcula `relevance_score` con señales de:

- repetición en múltiples fuentes
- presencia de `SL/TP`
- confirmación operativa
- contexto definido
- preparación de ejecución en setups ya compilados

El resultado queda persistido en `top_strategies_detected`, listo para ranking, inspección y priorización de estrategias reales.

## Estructura del proyecto

```text
project_root/
  config/
    settings.yaml
  data/
    raw/
      telegram/
    processed/
    transcripts/
    summaries/
    knowledge/
    vector_store/
  docs/
  logs/
  scripts/
  src/
  tests/
```

## Instalación

### Requisitos

- Python 3.11 o superior
- Telegram API credentials (`api_id`, `api_hash`)
- FFmpeg instalado y accesible por PATH o configurado en `FFMPEG_PATH`

### FFmpeg en Windows

Instala FFmpeg y asegúrate de que `ffmpeg.exe` esté disponible:

1. Descarga una build oficial o confiable.
2. Descomprime, por ejemplo, en `C:\ffmpeg`.
3. Agrega `C:\ffmpeg\bin` al `PATH` del sistema o configura `FFMPEG_PATH=C:\ffmpeg\bin\ffmpeg.exe` en `.env`.

### Soporte RAR en Windows

El proyecto usa `rarfile` y puede trabajar con alguno de estos backends:

- `UnRAR.exe`
- `rar.exe`
- `7z.exe`
- `7zz.exe`
- `bsdtar`

Rutas típicas detectadas automáticamente:

- `C:\Program Files\WinRAR\UnRAR.exe`
- `C:\Program Files\WinRAR\rar.exe`
- `C:\Program Files\7-Zip\7z.exe`
- `PATH` del sistema

Script recomendado:

```powershell
.\scripts\setup_rar_support.ps1
```

Si quieres que intente instalar 7-Zip automáticamente con `winget`:

```powershell
.\scripts\setup_rar_support.ps1 -Install7Zip
```

Variables nuevas en `.env`:

```env
RAR_BACKEND_PATH=
RAR_BACKEND_TYPE=
ARCHIVE_INSPECTION_ENABLED=true
```

### Preparación

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python scripts/bootstrap.py
```

## Configuración

Edita `.env`:

```env
TELEGRAM_API_ID=123456
TELEGRAM_API_HASH=your_hash
TELEGRAM_PHONE=+59100000000
SESSION_NAME=telegram_trading_brain
DATA_DIR=./data
DB_URL=sqlite:///./data/telegram_trading_brain.db
LOG_LEVEL=INFO
FFMPEG_PATH=ffmpeg
OPENAI_API_KEY=
TELEGRAM_SIGNAL_BOT_TOKEN=
TELEGRAM_SIGNAL_BOT_NAME=telegram_signal_bot
```

Y si quieres ajustar chunking o reintentos, modifica `config/settings.yaml`.

## Uso CLI

```powershell
python -m src.cli.main auth
python -m src.cli.main import-channels
python -m src.cli.main add-channel "https://t.me/mi_canal"
python -m src.cli.main learn-from-channel --channel "https://t.me/tradingcursosgratiss" --doc-limit 10 --archive-limit 2 --inspect-limit 10
python -m src.cli.main sync --mode full
python -m src.cli.main process
python -m src.cli.main rank-documents
python -m src.cli.main process-top-documents --limit 5
python -m src.cli.main doctor-archives
python -m src.cli.main download-archives --limit 1 --max-group-size-mb 2500 --download-only-complete-groups --retry 5
python -m src.cli.main inspect-archives --limit 20
python -m src.cli.main rank-archives
python -m src.cli.main select-archives --limit 10
python -m src.cli.main process-selected-archives --limit 3
python -m src.cli.main explain-archive "MES_1.part1.rar"
python -m src.cli.main unlock-archives-and-learn --channel "https://t.me/tradingcursosgratiss" --archive-limit 2 --inspect-limit 10 --max-group-size-mb 2500 --download-only-complete-groups --retry 5
python -m src.cli.main build-kb
python -m src.cli.main filter-content
python -m src.cli.main rebuild-kb --filtered
python -m src.cli.main status
python -m src.cli.main query "gestion de riesgo"
python -m src.cli.main build-semantic-index
python -m src.cli.main semantic-query "bos fvg london session" --concept bos --channel "SMC"
python -m src.cli.main extract-rules
python -m src.cli.main build-playbooks
python -m src.cli.main summarize-course --rebuild
python -m src.cli.main summarize-course "ict_masterclass.pdf"
python -m src.cli.main compare-authors "Mentor_A" "Mentor_B"
python -m src.cli.main compare-courses "ict_masterclass.pdf" "smc_bootcamp.pdf"
python -m src.cli.main export-backtest-dataset --output .\data\knowledge\backtest_dataset.csv
python -m src.cli.main normalize-rules
python -m src.cli.main compile-setups
python -m src.cli.main score-rules
python -m src.cli.main detect-strategies
python -m src.cli.main rank-strategies
python -m src.cli.main inspect-strategy "FVG Continuation | bos + fvg + liquidity_sweep | london | M15 | fvg_entry"
python -m src.cli.main export-strategies --output .\data\knowledge\strategies.json
python -m src.cli.main inspect-setup "FVG Continuation - fvg - XAUUSD - M5"
python -m src.cli.main compare-strategies "setup_a" "setup_b"
```

También hay wrappers PowerShell:

```powershell
.\scripts\bootstrap.ps1
.\scripts\auth.ps1
.\scripts\sync.ps1 -Channel "https://t.me/mi_canal" -Mode incremental
.\scripts\process.ps1
```

## Canal Inicial Configurado

El proyecto incluye `config/channels.yaml` con el canal objetivo inicial:

```text
https://t.me/tradingcursosgratiss
Cursos de Trading GRATIS
-1002397614732
```

Para registrarlo localmente sin autenticar todavía contra Telegram:

```powershell
python -m src.cli.main import-channels
python -m src.cli.main status
```

## Bot de Señales por Bot API

También puedes ingerir señales desde un bot propio vía Telegram Bot API. Configura el token en `.env`:

```env
TELEGRAM_SIGNAL_BOT_TOKEN=123456:ABC...
```

La fuente queda definida en `config/bots.yaml` como `telegram_signal_bot`. Para registrarla y sincronizar updates:

```powershell
python -m src.cli.main import-signal-bots
python -m src.cli.main sync-signal-bots
```

Nota importante: Telegram Bot API solo entrega updates que el bot puede recibir/ver. No permite leer todo tu historial personal como una cuenta de usuario; para historial de canales usamos Telethon con tu cuenta.

## Información Clave de Bots Locales

Si ya tienes bots de señales/trading en otros proyectos locales, puedes importarlos como conocimiento estructurado sin exponer secretos. El proyecto incluye `config/external_bots.yaml` apuntando a:

```text
C:\Users\Administrador\Desktop\BINANCEBOT
```

Importar esa información:

```powershell
python -m src.cli.main import-external-bot-info
```

Esto extrae configuración operativa como estrategia, pares, timeframe, riesgo, futures, leverage y RR; las claves sensibles quedan enmascaradas.

## Qué funciona ya

- Autenticación real con Telegram.
- Registro de canales.
- Sync incremental y full usando `last_synced_message_id`.
- Descarga de mensajes y medios a disco.
- Persistencia de metadatos en SQLite con SQLAlchemy.
- Detección de duplicados por hash + nombre + tamaño, reutilizando archivos ya descargados.
- Procesamiento de mensajes con limpieza, idioma y clasificación heurística.
- Extracción de texto de PDF, DOCX y XLSX.
- Chunking configurable y almacenamiento en `content_chunks`.
- Consulta local básica por palabras clave.
- Logging en consola y archivo.
- Historial de runs de ingestión y procesamiento.

## Qué funciona en Fase 2

- Embeddings locales determinísticos para `content_chunks`.
- Índice vectorial local persistido en SQLite.
- Retrieval híbrido con filtros por tema, autor, canal, estrategia y concepto.
- Extracción estructurada de reglas con:
  - activo
  - timeframe
  - contexto
  - condición de entrada
  - confirmación
  - stop loss
  - take profit
  - gestión de riesgo
  - filtro de sesión
  - observaciones
- Clustering de reglas similares.
- Playbooks por estrategia.
- Comparación entre autores y cursos.

## Qué agrega la detección de estrategias

- Ranking de estrategias más repetidas dentro del canal.
- Agrupación por conceptos, timeframe, sesión y tipo de entrada.
- Penalización de reglas incompletas.
- Evidencia trazable a `chunks`, autores, canales, setups compilados y reglas fuente.
- Salida materializada para responder: "estas son las estrategias más fuertes encontradas en el canal".

## Flujo Recomendado para Archives

1. `python -m src.cli.main sync-catalog --channel "https://t.me/tradingcursosgratiss"`
2. `python -m src.cli.main doctor-archives`
3. `python -m src.cli.main download-archives --limit 1 --max-group-size-mb 2500 --download-only-complete-groups --retry 5`
4. `python -m src.cli.main inspect-archives --limit 20`
5. `python -m src.cli.main rank-archives`
6. `python -m src.cli.main select-archives --limit 10`
7. `python -m src.cli.main explain-archive "<archivo>"`
8. `python -m src.cli.main process-selected-archives --limit 3`

Cómo interpretar `rank-archives`:

- `archive_selection_score` alto: archive con fuerte probabilidad de contener material educativo útil.
- `archive_usefulness_label`: tipo dominante del paquete.
- `archive_processing_recommendation`: acción operativa sugerida.
- `duplicate_confidence` alto: archive probablemente redundante respecto a otro ya catalogado.

Ejemplo real con multipart RAR del canal:

- `MES_1.part1.rar`
- `MES_1.part2.rar`
- `MES_3.part1.rar`
- `MES_3.part2.rar`
- `MES_3.part3.rar`

El sistema ahora detecta:

- `archive_group_key`
- `archive_part_number`
- `archive_total_parts_estimated`
- `multipart_group_status`

Y ya no trata esos archivos como basura opaca ni como duplicados ciegos.
- `download-archives` baja el grupo completo de forma inteligente:
  - selecciona grupos prometedores según `rank-archives`
  - descarga todas las partes del multipart antes de intentar procesarlo
  - reanuda desde `.part` cuando la transferencia se corta
  - reintenta automáticamente con `--retry`
  - respeta `--max-group-size-mb`
  - puede saltar grupos grandes con `--skip-large-groups`
  - puede restringirse a grupos completos con `--download-only-complete-groups`
  - guarda multipart futuros bajo un directorio común por grupo para que `RAR` pueda extraer con todas las partes visibles

Estados relevantes en esta fase:

- `downloaded`: el archivo quedó listo en disco
- `partial`: el grupo multipart no quedó completo o faltan partes
- `failed`: la descarga del archivo falló

Ejemplo recomendado para el canal real:

```powershell
python -m src.cli.main doctor-archives
python -m src.cli.main download-archives --limit 1 --max-group-size-mb 2500 --download-only-complete-groups --retry 5
python -m src.cli.main inspect-archives --limit 5
python -m src.cli.main process-selected-archives --limit 1 --max-size-mb 2500
python -m src.cli.main rebuild-kb --filtered
python -m src.cli.main normalize-rules
python -m src.cli.main detect-strategies
python -m src.cli.main unlock-archives-and-learn --channel "https://t.me/tradingcursosgratiss" --archive-limit 1 --inspect-limit 5 --max-group-size-mb 2500 --download-only-complete-groups --retry 5
```
- Resumen de cursos/documentos por módulos.
- Dataset base para backtesting exportable a CSV.

## Qué funciona en Fase 3

- Normalización operativa de reglas extraídas.
- Ontología reusable para ICT, SMC, trend pullback, breakout retest, liquidity reversal, OB rejection, FVG continuation y session expansion.
- Catálogos internos para sesiones, timeframes, conceptos técnicos, confirmaciones, entradas, SL, TP, riesgo y filtros de contexto.
- Traducción de conceptos cualitativos a proxies cuantificables:
  - BOS -> `detect_break_of_structure`
  - liquidity sweep -> `detect_wick_sweep`
  - FVG -> `detect_fair_value_gap`
  - order block -> `detect_order_block`
  - engulfing -> `detect_engulfing_candle`
  - session filter -> `is_within_allowed_session`
- Compilación de `StrategySetupDefinition`.
- Exportación JSON/CSV para backtesting posterior.
- Scoring de calidad para reglas y setups.
- Trazabilidad desde setup hacia reglas normalizadas, reglas extraídas, chunks, autores, canales y fuentes.

## Qué queda preparado para Fase 4

- `src/processing/video_processor.py`: extracción de audio con FFmpeg.
- `src/processing/audio_processor.py`: interfaz de transcripción con mock listo para cambiar por API.
- `src/ai/interfaces.py`: contratos para LLM y embeddings remotos.
- `src/knowledge/rule_extractor.py`: ampliable con extracción asistida por LLM.
- `src/knowledge/playbook_builder.py`: base para versionado y validación humana de playbooks.
- `src/trading/strategy_builder.py`: ya genera estrategias candidatas cuantificables.
- `src/trading/backtest_bridge.py`: ya exporta paquetes estructurados; falta conectar OHLCV y motor de simulación real.
- `src/trading/mt5_bridge.py`: integración futura con MetaTrader 5.

## Tests

```powershell
pytest
```

## Notas de diseño

- Las rutas son centralizadas y compatibles con Windows.
- La base separa `raw`, `processed`, `transcripts`, `summaries`, `knowledge` y `vector_store`.
- La arquitectura no está acoplada a un proveedor único de IA.
- La Fase 2 usa embeddings locales para no depender todavía de servicios externos.
- El esquema SQLite incluye compatibilidad hacia adelante con upgrades ligeros de columnas e índices.
