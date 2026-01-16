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
│   ├── raw/                        # Vstupní CSV z RÚIAN (VFR exporty). CP-1250 / WinLatin 2 encoding.
│   ├── processed/                  # Body v WGS84 (Apache Parquet)
│   ├── polygons/                   # Surové i sjednocené polygony (GeoPackage)
│   └── tiles/                      # Finální vektorové dlaždice {z}/{x}/{y}.pbf
├── src/
│   ├── 01_csv2parquet.py           # ETL: Čištění a transformace souřadnic
│   ├── 02_parquet2geopkg-poly.py   # ETL: Geometrie: Generování polygonů (Alpha Shapes)
│   ├── 03_geopkg2geojson-tiles.py  # ETL: Optimalizace: Generování MVT dlaždic (Tippecanoe)
│   └── config.py
├── web/
│   ├── tiles/                      # MVT dlaždice (zkopírováno z data/tiles)
│   ├── app.js                      # MapLibre logika
│   └── index.html                  # Web UI
├── run_pipeline.sh                 # Spouští Python ETL pipeline
└── run_sample_pipeline.sh          # Spouští Python ETL pipeline nad Sample daty k ověření procesu
```

---

## 2. ETL Fáze (Python)

### Krok 01: Příprava dat

- **Vstup:** VFR CSV adresních míst z RÚIAN (~3 miliony záznamů)
- **Filtrace:** Povinné atributy:
  - `psc`
  - `x`, `y` (souřadnice)
  - doporučeno zachovat `id_adresniho_mista` pro auditovatelnost

- **Transformace souřadnic:**  
  - Zdroj: S-JTSK (EPSG:5514)  
  - Cíl: WGS84 (EPSG:4326)  
  - Nástroj: `pyproj`

- **Výstup:**  
  - `points.parquet`
  - Sloupce: `psc`, `lon`, `lat`, `id_adresniho_mista`
  - Formát Parquet zvolen pro:
    - vysokou kompresi
    - rychlé filtrování podle PSČ
    - škálovatelnost

### Krok 02: Generování polygonů (Clustering)

#### Použitý přístup

- Algoritmus: **Concave Hull (Alpha Shapes)**
- Důvod volby:
  - lepší zachycení reálného rozsahu zástavby
  - omezení „území nikoho“ oproti Voronoi
  - menší nadhodnocení než Convex Hull

#### Logika zpracování

1. Iterace přes **unikátní PSČ**
2. Pro každé PSČ:
   - výběr bodového mraku adres
   - výpočet konkávní obálky
3. Výsledkem je **jedna geometrie na jedno PSČ**
   - polygon nebo multipolygon

#### Řízení rizik a okrajové případy

- **Adaptivní parametr alpha**
  - hodnota se může lišit podle:
    - počtu bodů
    - hustoty bodového mraku
- **Fallback logika:**
  - 1 bod → kruhový buffer (konfigurovatelný poloměr)
  - 2–3 body → Convex Hull
- **Topologická validace:**
  - oprava self-intersections
  - odstranění neplatných geometrií (`make_valid`, `buffer(0)`)

#### Atributy polygonu

Každý polygon PSČ musí obsahovat:
- `psc`
- `point_count` (počet adresních bodů)
- volitelně `area_km2` (pro kontrolu extrémů)

- **Výstup:**  
  - doporučený formát: **GeoPackage**

### Krok 03: Vektorové 

- **Nástroj:** `tippecanoe`
- **Vstup:** GeoPackage polygonů PSČ
- **Výstup:** MVT dlaždice

#### Parametry

- Zoom levels:
  - min zoom: 6 (přehled republiky)
  - max zoom: 14 (městská detailnost)
- Geometrická generalizace:
  - Douglas-Peucker
  - rozdílná míra zjednodušení podle zoomu

Doporučené volby:
- `--detect-shared-borders`
- `--coalesce-densest-as-needed`
- `--drop-densest-as-needed`
- `--no-feature-limit`

- **Výstupní forma:**
  - rozbalená struktura `{z}/{x}/{y}.pbf`
  - nebo `.mbtiles` archiv

---

## 3. Webová prezentace (Frontend)

### Mapový stack

- Mapová knihovna: **MapLibre GL JS**
- Podkladová mapa:
  - OpenStreetMap (XYZ raster)
  - možnost budoucí náhrady vektorovým basemapem
- Vektorový overlay:
  - zdroj `psc-layer`
  - URL: `/data/4_tiles/{z}/{x}/{y}.pbf`

### Funkcionalita

- **Interaktivita:**
  - `click` → identifikace PSČ
  - `mousemove` → zvýraznění (s throttlingem kvůli výkonu)
- **Zobrazované atributy:**
  - PSČ
  - počet adresních bodů
  - informační poznámka o odvozené geometrii
- **Stylování:**
  - dynamické barvy podle PSČ
  - transparentní výplň, zvýrazněná hranice
- **Nulový backend:** Celá složka /data/4_tiles/ a /src/04_web/ je hostována jako statický obsah.

---

## 4. Klíčové závislosti

### Python
- pandas
- geopandas
- pyarrow
- pyproj
- alphashape / scipy.spatial
- shapely

### Frontend
- maplibre-gl-js

---

## 5. Aktualizace dat

- Zdroj RÚIAN se aktualizuje pravidelně (měsíčně)
- ETL pipeline musí být:
  - idempotentní
  - spustitelná jedním příkazem
  - schopná plného přegenerování výstupů

---

## 6. Shrnutí omezení

- Zobrazené hranice PSČ z principu nemohou být oficiální
- Přesnost závisí na hustotě adresních bodů
- Projekt slouží k orientaci, analýze a vizualizaci
