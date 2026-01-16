#!/usr/bin/env python3
"""
ETL Step 2: Polygon Generation
- Load processed points from Parquet
- Generate concave hull (Alpha Shapes) for each ZIP code
- Adaptive alpha based on point density
- Fallback logic for small point counts
- Topological validation
- Greedy algorithm coloring
- Export to GeoPackage
"""

import sys
from pathlib import Path
from typing import List, Tuple

import pandas as pd
import geopandas as gpd
from shapely.geometry import Point, Polygon, MultiPolygon
from shapely.ops import unary_union
import alphashape
import numpy as np

# Add project root to path for config import
sys.path.insert(0, str(Path(__file__).parent))
import config


def load_points(parquet_path: Path) -> pd.DataFrame:
    """Load processed points from Parquet."""
    print(f"Loading points from {parquet_path}...")
    df = pd.read_parquet(parquet_path)
    print(f"Loaded {len(df):,} points for {df['zip_code'].nunique():,} unique ZIP code")
    return df


def calculate_adaptive_alpha(points: np.ndarray, point_count: int) -> float:
    """
    Calculate adaptive alpha based on point density.

    Args:
        points: Array of (lon, lat) coordinates
        point_count: Number of points

    Returns:
        Optimal alpha value
    """
    if point_count < 4:
        return 0  # Will use fallback logic

    # Calculate approximate area using convex hull
    from scipy.spatial import ConvexHull
    try:
        hull = ConvexHull(points)
        # Approximate area in degrees squared
        area_deg2 = hull.volume  # In 2D, volume is area

        # Convert to km² (rough approximation for Czech Republic latitude ~50°)
        # 1 degree latitude ≈ 111 km
        # 1 degree longitude at 50° ≈ 71 km
        area_km2 = area_deg2 * 111 * 71

        # Calculate density
        density = point_count / area_km2 if area_km2 > 0 else 0

        # Map density to alpha
        # High density (urban) -> low alpha (tight fit)
        # Low density (rural) -> high alpha (loose fit)
        if density > config.ALPHA_DENSITY_THRESHOLD:
            # Urban area
            alpha = config.ALPHA_MIN
        elif density < 10:
            # Very sparse rural
            alpha = config.ALPHA_MAX
        else:
            # Interpolate logarithmically
            log_density = np.log10(density + 1)
            log_threshold = np.log10(config.ALPHA_DENSITY_THRESHOLD)
            ratio = log_density / log_threshold
            alpha = config.ALPHA_MAX - (ratio * (config.ALPHA_MAX - config.ALPHA_MIN))
            alpha = np.clip(alpha, config.ALPHA_MIN, config.ALPHA_MAX)

        return alpha

    except Exception as e:
        print(f"  Warning: Could not calculate adaptive alpha: {e}")
        return (config.ALPHA_MIN + config.ALPHA_MAX) / 2


def create_buffer_polygon(point: Tuple[float, float], radius_meters: float) -> Polygon:
    """
    Create a circular buffer around a point.

    Args:
        point: (lon, lat) tuple
        radius_meters: Buffer radius in meters

    Returns:
        Buffered polygon
    """
    # Convert meters to degrees (rough approximation)
    # At latitude 50°, 1 degree lat ≈ 111 km, 1 degree lon ≈ 71 km
    lat_deg = radius_meters / 111000
    lon_deg = radius_meters / 71000

    pt = Point(point)
    # Use average of lat/lon degrees for circular buffer
    buffer_deg = (lat_deg + lon_deg) / 2
    return pt.buffer(buffer_deg)


def generate_polygon_for_zip_code(zip_code: str, points_df: pd.DataFrame) -> dict:
    """
    Generate polygon for a single ZIP.

    Args:
        zip_code: ZIP code
        points_df: DataFrame with points for this ZIP code

    Returns:
        Dictionary with polygon geometry and attributes
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

        elif point_count in [2, 3]:
            # Few points: use convex hull
            from scipy.spatial import ConvexHull
            hull = ConvexHull(coords)
            hull_points = coords[hull.vertices]
            geometry = Polygon(hull_points)
            method = 'convex_hull'

        else:
            # Many points: use alpha shape with adaptive alpha
            alpha = calculate_adaptive_alpha(coords, point_count)

            # Try alpha shape
            try:
                geometry = alphashape.alphashape(coords, alpha)
                method = f'alpha_shape(α={alpha:.3f})'

                # If result is not a valid polygon, fall back to convex hull
                if not isinstance(geometry, (Polygon, MultiPolygon)):
                    raise ValueError("Alpha shape did not produce polygon")

            except Exception as e:
                print(f"  ZIP code {zip_code}: Alpha shape failed ({e}), using convex hull")
                from scipy.spatial import ConvexHull
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


def apply_color_theorem(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    n = len(gdf)
    print(f"Building adjacency graph for {n} polygons...")

    # 1. Efficient Adjacency Building
    spatial_index = gdf.sindex
    adjacency = {i: set() for i in range(n)}

    # Using a spatial join approach is often faster than manual loops
    # We find all geometries that intersect/touch
    possible_matches = spatial_index.query(gdf.geometry, predicate="intersects")

    # results of query are (array_of_origin_indices, array_of_target_indices)
    for i, j in zip(possible_matches[0], possible_matches[1]):
        if i != j:
            adjacency[i].add(j)

    # 2. Welsh-Powell Greedy Ordering
    # Sort nodes by degree (number of neighbors) descending
    nodes = sorted(range(n), key=lambda x: len(adjacency[x]), reverse=True)

    colors = {}

    # 3. Open-ended Greedy Coloring
    for node in nodes:
        # Find colors already taken by neighbors
        used_neighbor_colors = {colors[neighbor] for neighbor in adjacency[node] if neighbor in colors}

        # Assign the smallest available non-negative integer color
        color = 0
        while color in used_neighbor_colors:
            color += 1

        colors[node] = color

    # Map colors back to original order and add to GDF
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
        print(f"Please run 01_prep.py first")
        sys.exit(1)

    # Load points
    df = load_points(args.input)

    # Generate polygons for each ZIP code
    print(f"\nGenerating polygons for {df['zip_code'].nunique():,} ZIP code...")
    print(f"Adaptive alpha range: {config.ALPHA_MIN} - {config.ALPHA_MAX}")
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

    # Apply graph coloring (Welsh-Powell greedy algorithm)
    gdf = apply_color_theorem(gdf)

    # Summary statistics
    print("\nSummary:")
    print(f"  Total polygons: {len(gdf):,}")
    print(f"  Total points: {gdf['point_count'].sum():,}")
    print(f"  Average points per ZIP code: {gdf['point_count'].mean():.1f}")
    print(f"  Median area: {gdf['area_km2'].median():.2f} km²")
    print(f"  Total area: {gdf['area_km2'].sum():.0f} km²")

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
