#!/bin/bash
# Complete ETL pipeline runner for Czech ZIP Code Map
# Usage: ./run_pipeline.sh

set -e  # Exit on error

echo "=========================================="
echo "  Czech ZIP Code Map - ETL Pipeline"
echo "=========================================="
echo ""

# Define file paths
INPUT_CSV="data/raw/sample.csv"
PROCESSED_PARQUET="data/processed/sample.parquet"
POLYGONS_GPKG="data/polygons/sample.gpkg"
TILES_DIR="data/tiles"

# Check if input file exists
if [ ! -f "$INPUT_CSV" ]; then
    echo "❌ Error: Input file not found: $INPUT_CSV"
    echo ""
    echo "Please place RÚIAN CSV file at: $INPUT_CSV"
    echo "Download from: https://www.cuzk.cz/ruian"
    exit 1
fi

echo "✓ Input file found"
echo ""

# Step 1: Data preparation
echo "=========================================="
echo "Step 1/4: Data Preparation"
echo "=========================================="
uv run python src/01_csv2parquet.py --input "$INPUT_CSV" --output "$PROCESSED_PARQUET"
echo ""

# Step 2: Polygon generation
echo "=========================================="
echo "Step 2/4: Polygon Generation"
echo "=========================================="
uv run python src/02_parquet2geopkg-poly.py --input "$PROCESSED_PARQUET" --output "$POLYGONS_GPKG"
echo ""

# Step 3: Tile generation
echo "=========================================="
echo "Step 3/4: Vector Tile Generation"
echo "=========================================="
uv run python src/03_geopkg2geojson-tiles.py --input "$POLYGONS_GPKG" --output "$TILES_DIR"
echo ""

# Step 4: Copy tiles to web directory
echo "=========================================="
echo "Step 4/4: Deploying Tiles to Web Directory"
echo "=========================================="
echo "Copying tiles from $TILES_DIR to web/tiles/..."
rm -rf web/tiles
cp -r "$TILES_DIR" web/tiles
echo "✓ Tiles deployed"
echo ""

# Success
echo "=========================================="
echo "✅ Pipeline completed successfully!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. cd web"
echo "2. python -m http.server 8000"
echo "3. Open http://localhost:8000 in your browser"
echo ""
