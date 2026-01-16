#!/usr/bin/env python3
"""
ETL Step 3: Vector Tile Generation
- Convert GeoPackage to GeoJSON (tippecanoe input)
- Generate MVT tiles using tippecanoe
- Output: {z}/{x}/{y}.pbf directory structure
"""

import sys
import subprocess
import shutil
from pathlib import Path

import geopandas as gpd

# Add project root to path for config import
sys.path.insert(0, str(Path(__file__).parent))
import config


def check_tippecanoe():
    """Check if tippecanoe is available."""
    if shutil.which('tippecanoe'):
        print("✓ tippecanoe found")
        return True
    else:
        print("✗ tippecanoe not found")
        print("\nInstallation options:")
        print("1. Try: pip install tippecanoe")
        print("2. Or install from source: https://github.com/felt/tippecanoe")
        print("3. On Ubuntu/Debian: sudo apt-get install tippecanoe")
        print("4. On macOS: brew install tippecanoe")
        return False


def convert_to_geojson(gpkg_path: Path, geojson_path: Path):
    """
    Convert GeoPackage to GeoJSON for tippecanoe.

    Args:
        gpkg_path: Input GeoPackage path
        geojson_path: Output GeoJSON path
    """
    print(f"Converting {gpkg_path} to GeoJSON...")

    # Load GeoPackage
    gdf = gpd.read_file(gpkg_path)

    # Export to GeoJSON
    gdf.to_file(geojson_path, driver='GeoJSON')

    file_size_mb = geojson_path.stat().st_size / 1024 / 1024
    print(f"Created GeoJSON: {file_size_mb:.2f} MB")


def generate_tiles(geojson_path: Path, output_dir: Path):
    """
    Generate vector tiles using tippecanoe.

    Args:
        geojson_path: Input GeoJSON file
        output_dir: Output directory for tiles
    """
    print(f"\nGenerating vector tiles...")
    print(f"  Zoom levels: {config.MIN_ZOOM} - {config.MAX_ZOOM}")
    print(f"  Output: {output_dir}")

    # Ensure output directory exists
    output_dir.mkdir(parents=True, exist_ok=True)

    # Build tippecanoe command
    cmd = [
        'tippecanoe',
        f'--output-to-directory={output_dir}',
        f'--minimum-zoom={config.MIN_ZOOM}',
        f'--maximum-zoom={config.MAX_ZOOM}',
        '--layer=zip_codes',  # Layer name
        '--attribution=Data © RÚIAN',
    ]

    # Add configured options
    cmd.extend(config.TIPPECANOE_OPTIONS)

    # Add input file
    cmd.append(str(geojson_path))

    print(f"\nRunning: {' '.join(cmd)}\n")

    # Run tippecanoe
    try:
        result = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True
        )

        if result.stdout:
            print(result.stdout)

        print("\n✓ Tiles generated successfully")

        # Count generated tiles
        tile_count = sum(1 for _ in output_dir.rglob('*.pbf'))
        print(f"  Generated {tile_count:,} tile files")

        # Calculate total size
        total_size = sum(f.stat().st_size for f in output_dir.rglob('*.pbf'))
        total_size_mb = total_size / 1024 / 1024
        print(f"  Total size: {total_size_mb:.2f} MB")

    except subprocess.CalledProcessError as e:
        print(f"Error running tippecanoe: {e}")
        if e.stderr:
            print(e.stderr)
        sys.exit(1)


def create_metadata(output_dir: Path):
    """
    Create metadata.json for tile layer.

    Args:
        output_dir: Tiles directory
    """
    import json

    metadata = {
        "name": "PSČ ČR",
        "description": "Odvozené hranice PSČ z RÚIAN adresních bodů",
        "version": "1.0",
        "attribution": "Data © RÚIAN, Mapa © Open Source contributors",
        "type": "overlay",
        "format": "pbf",
        "minzoom": config.MIN_ZOOM,
        "maxzoom": config.MAX_ZOOM,
        "bounds": [12.0, 48.5, 18.9, 51.1],  # Czech Republic bounds
        "center": [15.3381, 49.7437, 7],  # [lon, lat, zoom]
        "vector_layers": [
            {
                "id": "zip_codes",
                "description": "ZIP code polygons",
                "fields": {
                    "zip_code": "String - ZIP code (5 digits)",
                    "point_count": "Number - Count of address points",
                    "area_km2": "Number - Approximate area in km²",
                    "color_index": "Number - Color index for polygon coloring",
                    "method": "String - Generation method",
                }
            }
        ]
    }

    metadata_path = output_dir / 'metadata.json'
    with open(metadata_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    print(f"  Created {metadata_path}")


def main():
    """Main tile generation pipeline."""
    import argparse

    parser = argparse.ArgumentParser(description='ETL Step 3: Vector Tile Generation')
    parser.add_argument('--input', type=Path, default=config.POLYGONS_GPKG,
                        help='Input GeoPackage file path')
    parser.add_argument('--output', type=Path, default=config.TILES_DIR,
                        help='Output tiles directory path')
    args = parser.parse_args()

    print("=" * 60)
    print("ETL Step 3: Vector Tile Generation")
    print("=" * 60)

    # Check tippecanoe availability
    if not check_tippecanoe():
        print("\nPlease install tippecanoe first (see README.md)")
        sys.exit(1)

    # Check if input file exists
    if not args.input.exists():
        print(f"Error: Input file not found: {args.input}")
        print(f"Please run 02_cluster.py first")
        sys.exit(1)

    # Create temporary GeoJSON
    temp_geojson = args.input.parent / 'zip_codes.geojson'

    # Convert to GeoJSON
    convert_to_geojson(args.input, temp_geojson)

    # Generate tiles
    generate_tiles(temp_geojson, args.output)

    # Create metadata
    create_metadata(args.output)

    # Clean up temporary GeoJSON
    print(f"\nCleaning up temporary file...")
    temp_geojson.unlink()

    print("=" * 60)
    print("Step 3 completed successfully!")
    print(f"Output: {args.output}")
    print(f"Ready for web deployment!")
    print("=" * 60)


if __name__ == "__main__":
    main()
