# Mapa PSČ ČR - Open Source

Interaktivní mapa poštovních směrovacích čísel České republiky s hranicemi odvozenými z RÚIAN dat.

## O projektu

Smyslem projektu je poskytnout online mapu příslušnosti k PSČ. PSČ není oficiální územní jednotka. PSČ se přiřazuje ke každému adresnímu bodu jednotlivě, a proto neexistuje žádná oficiální mapa PSČ. Zobrazované hranice PSČ jsou **odvozené geometrie vypočtené z bodových dat RÚIAN.**

### Klíčové vlastnosti

- **Zero backend** - statická prezentace hostovatelná bez CGI
- **Vektorové dlaždice** - efektivní zobrazení s MapLibre GL JS
- **Voronoi tessellation** - přirozené hranice mezi sousedícími PSČ bez mezer
- **Barevné rozdělení pomocí Welsh-Powell algoritmu** - sousedící PSČ mají různé barvy
- **Konfigurovatelná paleta** - barvy lze jednoduše měnit

## Architektura

```
┌─────────────────┐      ┌──────────────────┐      ┌─────────────────┐      ┌─────────────────┐
│  RÚIAN CSV      │ ───> │  ETL Pipeline    │ ───> │  Vector Tiles   │ ───> │  Static Web     │
│  (Oficiální)    │      │  (Python)        │      │  (MVT .pbf)     │      │  (MapLibre)     │
└─────────────────┘      └──────────────────┘      └─────────────────┘      └─────────────────┘
```

## Instalace a použití

### 1. Instalace závislostí

```bash
PYTHON_VERSION=$(cat .python-version)
pyenv local $PYTHON_VERSION
python -m venv .venv
source .venv/bin/activate
pip install uv
uv sync
```

### 2. Zdroj dat

Zdrojová data pocházejí z [RÚIAN](https://vdp.cuzk.gov.cz/) (Registr územní identifikace, adres a nemovitostí) spravovaného ČÚZK. Pipeline automaticky stáhne aktuální data při prvním spuštění.

### 3. Spuštění ETL pipeline

```bash
# Kompletní pipeline (automaticky stáhne data při prvním spuštění):
./run_pipeline.sh

# Testovací pipeline s ukázkovými daty (Praha 1):
./run_sample_pipeline.sh
```

### 4. Spuštění webové aplikace

```bash
# Jednoduchý HTTP server pro testování
cd web
python -m http.server 8000

# Otevřete v prohlížeči:
# http://localhost:8000
```

### 5. Deployment

Pipeline automaticky zkopíruje vygenerované dlaždice do `web/tiles/`. Pro produkční nasazení stačí zkopírovat celou složku `web/` na statický hosting.

```bash
# Zkopírujte web/ na hosting
cp -r web/ /path/to/webroot/
```

## Konfigurace

Všechny parametry jsou konfigurovatelné v `src/config.py`:

### Geometrické parametry

```python
# Voronoi tessellation
VORONOI_CLIP_BUFFER_METERS = 500  # Buffer kolem konvexního obalu
SIMPLIFY_TOLERANCE_METERS = 20    # Douglas-Peucker vyhlazení

# Buffer pro osamocené adresy
BUFFER_RADIUS_METERS = 500  # Poloměr pro PSČ s 1-2 adresami
```

### Barevná paleta

Barevná paleta jde nastavit v python konfiguraci pomocí `COLOR_PALETTE` i úpravou v JS přes `updateColorPalette()`.

### Zoom levels

```python
MIN_ZOOM = 6   # Přehled ČR
MAX_ZOOM = 14  # Městská detailnost
```

## Struktura projektu

```
.
├── pyproject.toml                  # uv dependencies
├── run_pipeline.sh                 # Spuštění celého ETL pipeline
├── run_sample_pipeline.sh          # Spuštění ETL pipeline nad ukázkovými daty
│
├── data/
│   ├── raw/                        # RÚIAN CSV (CP-1250 encoding)
│   ├── processed/                  # Parquet s transformovanými body
│   ├── polygons/                   # GeoPackage s polygony PSČ
│   └── tiles/                      # MVT vector tiles {z}/{x}/{y}.pbf
│
├── src/
│   ├── config.py                   # Globální konfigurace
│   ├── 01_csv2parquet.py           # ETL: Načtení a transformace
│   ├── 02_parquet2geopkg-poly.py   # ETL: Generování polygonů (Voronoi)
│   └── 03_geopkg2geojson-tiles.py  # ETL: Generování MVT dlaždic
│
├── web/
│   ├── index.html                  # Web UI
│   ├── app.js                      # MapLibre logika
│   └── tiles/                      # MVT dlaždice (zkopírováno z data/tiles)
│
└── docs/                           # Dokumentace, popis zadání
```

## Technologie

### Backend (ETL)
- **pandas** - zpracování CSV
- **geopandas** - geografická data
- **pyproj** - transformace souřadnic (S-JTSK → WGS84)
- **scipy.spatial** - Voronoi tessellation
- **shapely** - geometrické operace
- **pyarrow** - Parquet I/O
- **tippecanoe** - generování MVT dlaždic

### Frontend
- **MapLibre GL JS** - renderování vektorových map
- **OpenStreetMap** - podkladová rasterová mapa

## Aktualizace dat

RÚIAN data se aktualizují měsíčně. Pro aktualizaci mapy smažte `data/raw/addresses.csv` a spusťte pipeline znovu - data se automaticky stáhnou:

```bash
rm data/raw/addresses.csv
./run_pipeline.sh
```

Pipeline je idempotentní a lze ji opakovaně spouštět.

## Licence

**GNU General Public License v3.0 or later (GPL-3.0-or-later)**

Tento projekt je open-source software šířený pod licencí GPL-3.0-or-later. Zdrojový kód můžete volně používat, upravovat a šířit v souladu s touto licencí.

### Upozornění k datům

**Data nejsou ve vlastnictví autora projektu.** Zdrojová data pocházejí z:

- **RÚIAN** (Registr územní identifikace, adres a nemovitostí) - © Český úřad zeměměřický a katastrální (ČÚZK)
- Podmínky použití RÚIAN dat: https://www.cuzk.cz/

Při použití této mapy je nutné uvést zdroj dat podle podmínek ČÚZK.
