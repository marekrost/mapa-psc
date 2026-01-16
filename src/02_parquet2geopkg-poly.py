#!/usr/bin/env python3
"""
ETL Step 2: Polygon Generation
- Load processed points from Parquet
- Generate polygons using Delaunay triangulation with edge filtering
- Adaptive edge threshold based on point density
- Preserves holes and complex shapes (donuts, U-shapes)
- Fallback logic for small point counts
- Topological validation
- Greedy algorithm coloring
- Export to GeoPackage
"""

import sys
from pathlib import Path
from typing import Tuple

import pandas as pd
import geopandas as gpd
from shapely.geometry import Point, Polygon, MultiPolygon
from shapely.ops import unary_union
from scipy.spatial import Delaunay, ConvexHull
import numpy as np

# Add project root to path for config import
sys.path.insert(0, str(Path(__file__).parent))
import config


def load_points(parquet_path: Path) -> pd.DataFrame:
    """Load processed points from Parquet."""
    print(f"Loading points from {parquet_path}...")
    df = pd.read_parquet(parquet_path)
    print(f"Loaded {len(df):,} points for {df['zip_code'].nunique():,} unique ZIP codes")
    return df


def meters_to_degrees(meters: float) -> float:
    """
    Convert meters to degrees (approximate for Czech Republic ~50° latitude).

    At latitude 50°:
    - 1 degree latitude ≈ 111 km
    - 1 degree longitude ≈ 71 km
    - Average ≈ 91 km
    """
    return meters / 91000


def calculate_adaptive_edge_threshold(points: np.ndarray, point_count: int) -> float:
    """
    Calculate adaptive edge threshold based on point density.

    Args:
        points: Array of (lon, lat) coordinates
        point_count: Number of points

    Returns:
        Edge threshold in degrees
    """
    if point_count < 4:
        return meters_to_degrees(config.EDGE_LENGTH_MAX_METERS)

    try:
        hull = ConvexHull(points)
        # Approximate area in degrees squared
        area_deg2 = hull.volume  # In 2D, volume is area

        # Convert to km²
        area_km2 = area_deg2 * 111 * 71

        # Calculate density (points per km²)
        density = point_count / area_km2 if area_km2 > 0 else 0

        # Map density to edge threshold
        # High density -> shorter edges (tighter fit)
        # Low density -> longer edges (looser fit)
        if density > config.EDGE_DENSITY_THRESHOLD:
            threshold_m = config.EDGE_LENGTH_BASE_METERS
        elif density < 10:
            threshold_m = config.EDGE_LENGTH_MAX_METERS
        else:
            # Interpolate based on density
            ratio = density / config.EDGE_DENSITY_THRESHOLD
            threshold_m = config.EDGE_LENGTH_MAX_METERS - (
                ratio * (config.EDGE_LENGTH_MAX_METERS - config.EDGE_LENGTH_BASE_METERS)
            )

        return meters_to_degrees(threshold_m)

    except Exception as e:
        print(f"  Warning: Could not calculate adaptive threshold: {e}")
        return meters_to_degrees(
            (config.EDGE_LENGTH_BASE_METERS + config.EDGE_LENGTH_MAX_METERS) / 2
        )


def generate_polygon_delaunay(coords: np.ndarray, edge_threshold_deg: float) -> Polygon | MultiPolygon | None:
    """
    Generate polygon using Delaunay triangulation with edge filtering.

    This method preserves holes and complex shapes (donuts, U-shapes) because
    triangles spanning empty areas have long edges and are filtered out.

    Args:
        coords: Array of (lon, lat) coordinates
        edge_threshold_deg: Maximum edge length in degrees

    Returns:
        Polygon or MultiPolygon geometry, or None if failed
    """
    if len(coords) < 3:
        return None

    # Create Delaunay triangulation
    try:
        tri = Delaunay(coords)
    except Exception:
        return None

    # Filter triangles by edge length
    triangles = []
    for simplex in tri.simplices:
        pts = coords[simplex]

        # Calculate edge lengths
        edges = [
            np.linalg.norm(pts[0] - pts[1]),
            np.linalg.norm(pts[1] - pts[2]),
            np.linalg.norm(pts[2] - pts[0])
        ]

        # Keep triangle only if all edges are below threshold
        if max(edges) <= edge_threshold_deg:
            triangles.append(Polygon(pts))

    if not triangles:
        return None

    # Union all triangles into a single geometry
    return unary_union(triangles)


def create_buffer_polygon(point: Tuple[float, float], radius_meters: float) -> Polygon:
    """
    Create a circular buffer around a point.

    Args:
        point: (lon, lat) tuple
        radius_meters: Buffer radius in meters

    Returns:
        Buffered polygon
    """
    pt = Point(point)
    buffer_deg = meters_to_degrees(radius_meters)
    return pt.buffer(buffer_deg)


def generate_polygon_for_zip_code(zip_code: str, points_df: pd.DataFrame) -> dict | None:
    """
    Generate polygon for a single ZIP code.

    Args:
        zip_code: ZIP code
        points_df: DataFrame with points for this ZIP code

    Returns:
        Dictionary with polygon geometry and attributes, or None if failed
    """
    point_count = len(points_df)
    coords = points_df[['lon', 'lat']].values

    geometry = None
    method = None

    try:
        if point_count == 1:
            # Single point: create buffer
            geometry = create_buffer_polygon(coords[0], config.BUFFER_RADIUS_METERS)
            method = 'buffer'

        elif point_count == 2:
            # Two points: create buffered line
            from shapely.geometry import LineString
            line = LineString(coords)
            geometry = line.buffer(meters_to_degrees(config.BUFFER_RADIUS_METERS / 2))
            method = 'buffered_line'

        elif point_count == 3:
            # Three points: simple triangle
            geometry = Polygon(coords)
            method = 'triangle'

        else:
            # Many points: use Delaunay triangulation with edge filtering
            edge_threshold = calculate_adaptive_edge_threshold(coords, point_count)
            geometry = generate_polygon_delaunay(coords, edge_threshold)

            if geometry is not None:
                method = f'delaunay(e={edge_threshold * 91000:.0f}m)'
            else:
                # Fallback to convex hull if Delaunay fails
                print(f"  ZIP {zip_code}: Delaunay produced no triangles, using convex hull")
                hull = ConvexHull(coords)
                hull_points = coords[hull.vertices]
                geometry = Polygon(hull_points)
                method = 'convex_hull_fallback'

        # Validate and fix geometry
        if geometry is not None:
            if not geometry.is_valid:
                geometry = geometry.buffer(0)  # Fix self-intersections

            # Calculate area in km²
            area_deg2 = geometry.area
            area_km2 = area_deg2 * 111 * 71  # Rough approximation

            return {
                'zip_code': zip_code,
                'geometry': geometry,
                'point_count': point_count,
                'area_km2': round(area_km2, 2),
                'method': method,
            }

    except Exception as e:
        print(f"  Error processing ZIP code {zip_code}: {e}")

    return None


def apply_graph_coloring(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Apply Welsh-Powell greedy graph coloring to ensure adjacent polygons
    have different colors.

    Args:
        gdf: GeoDataFrame with polygon geometries

    Returns:
        GeoDataFrame with color_index column added
    """
    n = len(gdf)
    print(f"Building adjacency graph for {n} polygons...")

    # Build adjacency using spatial index
    spatial_index = gdf.sindex
    adjacency = {i: set() for i in range(n)}

    # Find all geometries that intersect/touch
    possible_matches = spatial_index.query(gdf.geometry, predicate="intersects")

    for i, j in zip(possible_matches[0], possible_matches[1]):
        if i != j:
            adjacency[i].add(j)

    # Welsh-Powell: sort nodes by degree (number of neighbors) descending
    nodes = sorted(range(n), key=lambda x: len(adjacency[x]), reverse=True)

    colors = {}

    # Greedy coloring
    for node in nodes:
        used_neighbor_colors = {colors[neighbor] for neighbor in adjacency[node] if neighbor in colors}

        # Assign the smallest available color
        color = 0
        while color in used_neighbor_colors:
            color += 1

        colors[node] = color

    # Add colors to GeoDataFrame
    gdf['color_index'] = [colors[i] for i in range(n)]

    max_colors = gdf['color_index'].max() + 1
    print(f"Coloring complete using {max_colors} colors.")
    print(f"Color distribution: {gdf['color_index'].value_counts().to_dict()}")

    return gdf


def main():
    """Main polygon generation pipeline."""
    import argparse

    parser = argparse.ArgumentParser(description='ETL Step 2: Polygon Generation')
    parser.add_argument('--input', type=Path, default=config.POINTS_PARQUET,
                        help='Input Parquet file path')
    parser.add_argument('--output', type=Path, default=config.POLYGONS_GPKG,
                        help='Output GeoPackage file path')
    args = parser.parse_args()

    print("=" * 60)
    print("ETL Step 2: Polygon Generation")
    print("=" * 60)

    # Check if input file exists
    if not args.input.exists():
        print(f"Error: Input file not found: {args.input}")
        print(f"Please run 01_csv2parquet.py first")
        sys.exit(1)

    # Load points
    df = load_points(args.input)

    # Generate polygons for each ZIP code
    print(f"\nGenerating polygons for {df['zip_code'].nunique():,} ZIP codes...")
    print(f"Edge threshold range: {config.EDGE_LENGTH_BASE_METERS}-{config.EDGE_LENGTH_MAX_METERS}m")
    print(f"Buffer radius: {config.BUFFER_RADIUS_METERS}m")

    polygons = []
    for i, (zip_code, group) in enumerate(df.groupby('zip_code'), 1):
        if i % 500 == 0:
            print(f"  Processing {i}/{df['zip_code'].nunique()}...")

        result = generate_polygon_for_zip_code(zip_code, group)
        if result:
            polygons.append(result)

    print(f"Generated {len(polygons):,} polygons")

    # Create GeoDataFrame
    gdf = gpd.GeoDataFrame(polygons, crs=config.CRS_TARGET)

    # Apply graph coloring
    gdf = apply_graph_coloring(gdf)

    # Summary statistics
    print("\nSummary:")
    print(f"  Total polygons: {len(gdf):,}")
    print(f"  Total points: {gdf['point_count'].sum():,}")
    print(f"  Average points per ZIP code: {gdf['point_count'].mean():.1f}")
    print(f"  Median area: {gdf['area_km2'].median():.2f} km²")
    print(f"  Total area: {gdf['area_km2'].sum():.0f} km²")

    # Method breakdown
    method_counts = gdf['method'].apply(lambda x: x.split('(')[0]).value_counts()
    print(f"  Methods: {method_counts.to_dict()}")

    # Export to GeoPackage
    print(f"\nExporting to {args.output}...")
    args.output.parent.mkdir(parents=True, exist_ok=True)

    gdf.to_file(args.output, driver='GPKG', layer='zip_codes')

    file_size_mb = args.output.stat().st_size / 1024 / 1024
    print(f"Saved {len(gdf):,} polygons ({file_size_mb:.2f} MB)")

    print("=" * 60)
    print("Step 2 completed successfully!")
    print(f"Output: {args.output}")
    print("=" * 60)


if __name__ == "__main__":
    main()
