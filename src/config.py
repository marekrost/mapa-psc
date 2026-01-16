"""
Global configuration for ZIP Map ETL pipeline
"""

from pathlib import Path

# Project root directory
PROJECT_ROOT = Path(__file__).parent

# Data paths
DATA_DIR = PROJECT_ROOT / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
POLYGONS_DIR = DATA_DIR / "polygons"
TILES_DIR = DATA_DIR / "tiles"

# Input/Output files
INPUT_CSV = RAW_DATA_DIR / "addresses.csv"  # Adjust filename as needed
POINTS_PARQUET = PROCESSED_DATA_DIR / "addresses.parquet"
POLYGONS_GPKG = POLYGONS_DIR / "addresses.gpkg"

# Coordinate Reference Systems
CRS_SOURCE = "EPSG:5514"  # S-JTSK
CRS_TARGET = "EPSG:4326"  # WGS84

# CSV encoding (RÚIAN uses CP-1250 / Windows-1250)
CSV_ENCODING = "cp1250"

# Delaunay triangulation parameters (for polygon generation)
# Triangles with edges longer than threshold are removed, preserving holes and U-shapes
EDGE_LENGTH_BASE_METERS = 150  # Base edge threshold for dense urban areas
EDGE_LENGTH_MAX_METERS = 500   # Maximum edge threshold for sparse rural areas
EDGE_DENSITY_THRESHOLD = 50    # Points per km² - below this, use longer edges

# Fallback for small point counts
BUFFER_RADIUS_METERS = 500  # Buffer radius for single-point ZIP (visible at zoom 10, clickable at zoom 12)

# Tippecanoe parameters
MIN_ZOOM = 6   # Republic overview
MAX_ZOOM = 14  # Urban detail
TIPPECANOE_OPTIONS = [
    "--detect-shared-borders",
    "--coalesce-densest-as-needed",
    "--drop-densest-as-needed",
    "--no-feature-limit",
    "--no-tile-compression",  # Uncompressed tiles work with any static file server
    "--force",  # Overwrite existing tiles
]

# Color palette for polygon coloring (configurable RGB tuples)
# Welsh-Powell greedy algorithm assigns colors so neighbors differ
COLOR_PALETTE = [
    (255, 107, 107),  # Red
    (78, 205, 196),   # Teal
    (255, 195, 113),  # Orange
    (162, 155, 254),  # Purple
    (129, 199, 132),  # Green
    (255, 183, 197),  # Pink
]

# Web map configuration
MAP_INITIAL_CENTER = [15.3381, 49.7437]  # Czech Republic center (lon, lat)
MAP_INITIAL_ZOOM = 7
