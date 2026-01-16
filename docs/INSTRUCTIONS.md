# Technické zadání: Open-Source Mapa PSČ ČR

Smyslem projektu je poskytnout online mapu příslušnosti oblastí k PSČ tak, aby uživatel mohl rychle identifikovat která PSČ ho zajímají.

PSČ není oficiální územní jednotka, ale doručovací atribut přiřazený k adresním místům. Zobrazované hranice PSČ jsou **odvozené geometrie vypočtené z bodových dat RÚIAN** a slouží výhradně k orientačním a analytickým účelům.

Projekt je koncipován jako co nejjednodušší webová stránka s otevřeným přístupem bez nutnosti komukoliv platit.

## 1. Architektura projektu

Projekt je rozdělen na:
- offline ETL pipeline (Python, výpočetně náročné operace)
- online statickou prezentaci (Vector Tiles + MapLibre)

Cílem architektury je nulový backend a možnost hostování na statickém úložišti (GitHub Pages, S3, Cloudflare).

### Souborová struktura
```text
/
├── data/
│   ├── raw/                        # Vstupní CSV z RÚIAN (CP-1250 encoding)
│   ├── processed/                  # Body v WGS84 (Parquet)
│   ├── polygons/                   # GeoPackage s polygony
│   └── tiles/                      # Vektorové dlaždice {z}/{x}/{y}.pbf
├── src/
│   ├── config.py                   # Konfigurace pipeline
│   ├── 01_csv2parquet.py           # ETL: Čištění a transformace souřadnic
│   ├── 02_parquet2geopkg-poly.py   # ETL: Voronoi tessellation
│   └── 03_geopkg2geojson-tiles.py  # ETL: Generování MVT dlaždic
├── web/
│   ├── tiles/                      # MVT dlaždice (zkopírováno z data/tiles)
│   ├── app.js                      # MapLibre logika
│   └── index.html                  # Web UI
├── run_pipeline.sh                 # Spouští ETL pipeline (auto-download dat)
└── run_sample.pipeline.sh          # ETL nad ukázkovými daty
```

---

## 2. ETL Fáze (Python)

### Krok 01: Příprava dat

- **Vstup:** VFR CSV adresních míst z RÚIAN (~3 miliony záznamů)
- **Transformace souřadnic:** S-JTSK (EPSG:5514) → WGS84 (EPSG:4326) pomocí `pyproj`
- **Výstup:** `addresses.parquet` se sloupci `zip_code`, `lon`, `lat`

### Krok 02: Generování polygonů (Voronoi Tessellation)

#### Algoritmus (podobný přístupu Google Maps)

1. **Voronoi diagram** - každý adresní bod získá buňku obsahující prostor, který je k němu nejblíže
2. **Clip to boundary** - oříznutí na konvexní obal + buffer
3. **Dissolve by ZIP** - sloučení buněk se stejným PSČ
4. **Douglas-Peucker** - vyhlazení hranic

#### Výhody Voronoi přístupu
- Vyplňuje celý prostor (žádné mezery mezi PSČ)
- Přirozené hranice (equidistantní mezi sousedními adresami)
- Jasné vztahy mezi sousedícími oblastmi

#### Fallback logika
- 1 bod → kruhový buffer
- 2-3 body → jednoduchý polygon

#### Graph coloring
- Welsh-Powell greedy algoritmus pro přiřazení barev
- Sousedící PSČ mají vždy různé barvy

- **Výstup:** GeoPackage s atributy `zip_code`, `point_count`, `area_km2`, `color_index`

### Krok 03: Vektorové dlaždice

- **Nástroj:** `tippecanoe`
- **Zoom levels:** 6 (přehled republiky) – 14 (městská detailnost)
- **Výstup:** MVT dlaždice `{z}/{x}/{y}.pbf`

---

## 3. Webová prezentace (Frontend)

- **Mapová knihovna:** MapLibre GL JS
- **Podkladová mapa:** OpenStreetMap (XYZ raster)
- **Interaktivita:** click/hover pro identifikaci PSČ
- **Nulový backend:** Celá aplikace je statický obsah

---

## 4. Klíčové závislosti

### Python
- pandas, geopandas, pyarrow
- pyproj, scipy.spatial, shapely
- tippecanoe (CLI)

### Frontend
- MapLibre GL JS

---

## 5. Omezení

- Zobrazené hranice PSČ z principu nemohou být oficiální
- Přesnost závisí na hustotě adresních bodů
- Projekt slouží k orientaci, analýze a vizualizaci
