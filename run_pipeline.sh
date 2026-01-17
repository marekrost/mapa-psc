#!/bin/bash
# Complete ETL pipeline runner for Czech ZIP Code Map
# Usage: ./run_pipeline.sh
#
# This script will:
# 1. Download RÚIAN data if not present
# 2. Process CSV to Parquet
# 3. Generate polygons
# 4. Generate vector tiles
# 5. Deploy tiles to web directory

set -e  # Exit on error

echo "=========================================="
echo "  Czech ZIP Code Map - ETL Pipeline"
echo "=========================================="
echo ""

# Define file paths
RAW_DIR="data/raw"
INPUT_CSV="$RAW_DIR/addresses.csv"
PROCESSED_PARQUET="data/processed/addresses.parquet"
BOUNDARY_GEOJSON="data/boundary/czech_republic.json"
POLYGONS_GPKG="data/polygons/addresses.gpkg"
TILES_DIR="data/tiles"

# Data source URL (update date as needed)
RUIAN_URL="https://vdp.cuzk.gov.cz/vymenny_format/csv/20251231_OB_ADR_csv.zip"

# Step 0: Download data if not present
echo "=========================================="
echo "Step 1/5: Data Acquisition"
echo "=========================================="

if [ -f "$INPUT_CSV" ]; then
    echo "Input file already exists: $INPUT_CSV"
    echo "Skipping download."
else
    echo "Input file not found. Downloading RÚIAN data..."
    echo "Source: $RUIAN_URL"
    echo ""

    # Create directories
    mkdir -p "$RAW_DIR"

    # Create temporary directory
    TMPDIR=$(mktemp -d)
    trap "rm -rf $TMPDIR" EXIT

    # Download ZIP file
    echo "Downloading..."
    wget --quiet --show-progress --directory-prefix="$TMPDIR" "$RUIAN_URL"

    # Extract CSV files
    echo "Extracting..."
    unzip -q -j "$TMPDIR"/*.zip '*.csv' -d "$TMPDIR/"

    # Merge all CSV files (skip header on subsequent files)
    echo "Merging CSV files..."
    awk 'FNR==1 && NR!=1{next;}{print}' "$TMPDIR"/*.csv > "$INPUT_CSV"

    # Show result
    LINE_COUNT=$(wc -l < "$INPUT_CSV")
    FILE_SIZE=$(du -h "$INPUT_CSV" | cut -f1)
    echo "Created $INPUT_CSV ($LINE_COUNT lines, $FILE_SIZE)"
fi
echo ""

# Step 1: Data preparation
echo "=========================================="
echo "Step 2/5: Data Preparation"
echo "=========================================="
uv run python src/01_csv2parquet.py --input "$INPUT_CSV" --output "$PROCESSED_PARQUET"
echo ""

# Step 2: Polygon generation
echo "=========================================="
echo "Step 3/5: Polygon Generation"
echo "=========================================="
uv run python src/02_parquet2geopkg-poly.py \
    --input "$PROCESSED_PARQUET" \
    --boundary "$BOUNDARY_GEOJSON" \
    --output "$POLYGONS_GPKG"
echo ""

# Step 3: Tile generation
echo "=========================================="
echo "Step 4/5: Vector Tile Generation"
echo "=========================================="
uv run python src/03_geopkg2geojson-tiles.py --input "$POLYGONS_GPKG" --output "$TILES_DIR"
echo ""

# Step 4: Copy tiles to web directory
echo "=========================================="
echo "Step 5/5: Deploying Tiles to Web Directory"
echo "=========================================="
echo "Copying tiles from $TILES_DIR to web/tiles/..."
rm -rf web/tiles
cp -r "$TILES_DIR" web/tiles
echo "Tiles deployed"
echo ""

# Success
echo "=========================================="
echo "Pipeline completed successfully!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. cd web"
echo "2. python -m http.server 8000"
echo "3. Open http://localhost:8000 in your browser"
echo ""
