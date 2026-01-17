#!/usr/bin/env python3
"""
ETL Step 2: Polygon Generation using Voronoi Tessellation
- Load processed points from Parquet
- Generate Voronoi cells for each address point
- Clip to country boundary (from GeoJSON file)
- Dissolve cells by ZIP code
- Simplify with Douglas-Peucker algorithm
- Greedy algorithm coloring
- Export to GeoPackage

This approach (similar to Google's method):
- Fills entire space with no gaps
- Shows clear neighbor relationships
- Creates cartographically natural boundaries
"""

import sys
from pathlib import Path

import pandas as pd
import geopandas as gpd
from shapely.geometry import Point, Polygon, MultiPolygon, box
from shapely.ops import unary_union
from scipy.spatial import Voronoi, ConvexHull
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
    """
    return meters / 91000


def voronoi_finite_polygons(vor, radius=None):
    """
    Reconstruct infinite Voronoi regions as finite polygons.

    Args:
        vor: scipy.spatial.Voronoi object
        radius: Distance to extend infinite edges (if None, uses 10x the extent)

    Returns:
        List of (region_index, polygon) tuples
    """
    if vor.points.shape[1] != 2:
        raise ValueError("Requires 2D input")

    new_regions = []
    new_vertices = vor.vertices.tolist()

    center = vor.points.mean(axis=0)
    if radius is None:
        radius = np.ptp(vor.points, axis=0).max() * 10

    # Construct a map of point index to Voronoi region
    all_ridges = {}
    for (p1, p2), (v1, v2) in zip(vor.ridge_points, vor.ridge_vertices):
        all_ridges.setdefault(p1, []).append((p2, v1, v2))
        all_ridges.setdefault(p2, []).append((p1, v1, v2))

    # Reconstruct each region
    for p1, region_idx in enumerate(vor.point_region):
        vertices = vor.regions[region_idx]

        if all(v >= 0 for v in vertices):
            # Finite region - use as-is
            new_regions.append(vertices)
            continue

        # Infinite region - reconstruct
        ridges = all_ridges.get(p1, [])
        new_region = [v for v in vertices if v >= 0]

        for p2, v1, v2 in ridges:
            if v2 < 0:
                v1, v2 = v2, v1
            if v1 >= 0:
                continue

            # Compute the direction to extend
            t = vor.points[p2] - vor.points[p1]
            t = t / np.linalg.norm(t)
            n = np.array([-t[1], t[0]])  # Normal

            midpoint = vor.points[[p1, p2]].mean(axis=0)
            direction = np.sign(np.dot(midpoint - center, n)) * n

            far_point = vor.vertices[v2] + direction * radius
            new_region.append(len(new_vertices))
            new_vertices.append(far_point.tolist())

        # Sort region vertices by angle
        vs = np.asarray([new_vertices[v] for v in new_region])
        c = vs.mean(axis=0)
        angles = np.arctan2(vs[:, 1] - c[1], vs[:, 0] - c[0])
        new_region = np.array(new_region)[np.argsort(angles)].tolist()

        new_regions.append(new_region)

    return new_regions, np.asarray(new_vertices)


def generate_voronoi_polygons(df: pd.DataFrame, clip_boundary: Polygon) -> gpd.GeoDataFrame:
    """
    Generate Voronoi polygons for all points, clipped to boundary.

    Args:
        df: DataFrame with lon, lat, zip_code columns
        clip_boundary: Polygon to clip Voronoi cells to

    Returns:
        GeoDataFrame with one row per point, containing Voronoi cell geometry
    """
    coords = df[['lon', 'lat']].values

    # Handle edge case: very few points
    if len(coords) < 4:
        # Just buffer the points
        geometries = [Point(c).buffer(meters_to_degrees(config.BUFFER_RADIUS_METERS)) for c in coords]
        return gpd.GeoDataFrame({
            'zip_code': df['zip_code'].values,
            'geometry': geometries
        }, crs=config.CRS_TARGET)

    # Generate Voronoi diagram
    vor = Voronoi(coords)

    # Get finite polygons
    regions, vertices = voronoi_finite_polygons(vor)

    # Create polygons and clip to boundary
    polygons = []
    for i, region in enumerate(regions):
        if len(region) < 3:
            # Invalid region - use buffer
            poly = Point(coords[i]).buffer(meters_to_degrees(config.BUFFER_RADIUS_METERS))
        else:
            poly = Polygon([vertices[v] for v in region])

        # Clip to boundary
        if clip_boundary is not None:
            poly = poly.intersection(clip_boundary)

        # Ensure valid geometry
        if not poly.is_valid:
            poly = poly.buffer(0)

        polygons.append(poly)

    return gpd.GeoDataFrame({
        'zip_code': df['zip_code'].values,
        'geometry': polygons
    }, crs=config.CRS_TARGET)


def load_boundary_from_file(boundary_path: Path) -> Polygon:
    """
    Load clipping boundary from a GeoJSON file.

    Args:
        boundary_path: Path to GeoJSON file containing boundary polygon

    Returns:
        Polygon boundary, or None if file doesn't exist
    """
    if not boundary_path.exists():
        return None

    print(f"Loading boundary from {boundary_path}...")
    boundary_gdf = gpd.read_file(boundary_path)

    if len(boundary_gdf) == 0:
        print("  Warning: Boundary file is empty")
        return None

    # Get the first geometry (assumes single polygon for country boundary)
    boundary = boundary_gdf.geometry.iloc[0]

    # Handle MultiPolygon by taking the union
    if isinstance(boundary, MultiPolygon):
        boundary = unary_union(boundary)

    if not boundary.is_valid:
        boundary = boundary.buffer(0)

    original_vertices = len(boundary.exterior.coords)

    # Simplify boundary for faster intersection operations (~50m tolerance)
    simplify_tolerance = meters_to_degrees(50)
    boundary = boundary.simplify(simplify_tolerance, preserve_topology=True)

    if not boundary.is_valid:
        boundary = boundary.buffer(0)

    simplified_vertices = len(boundary.exterior.coords)
    print(f"  Loaded boundary: {original_vertices:,} -> {simplified_vertices:,} vertices (simplified ~50m)")
    return boundary


def create_clip_boundary_from_hull(df: pd.DataFrame, buffer_meters: float) -> Polygon:
    """
    Create a clipping boundary from the convex hull of all points with a buffer.
    Used as fallback when no boundary file is available.

    Args:
        df: DataFrame with lon, lat columns
        buffer_meters: Buffer distance in meters

    Returns:
        Polygon boundary
    """
    coords = df[['lon', 'lat']].values

    if len(coords) < 3:
        # Use bounding box with buffer
        minx, miny = coords.min(axis=0)
        maxx, maxy = coords.max(axis=0)
        buffer_deg = meters_to_degrees(buffer_meters)
        return box(minx - buffer_deg, miny - buffer_deg,
                   maxx + buffer_deg, maxy + buffer_deg)

    # Create convex hull
    hull = ConvexHull(coords)
    hull_polygon = Polygon(coords[hull.vertices])

    # Add buffer
    buffer_deg = meters_to_degrees(buffer_meters)
    return hull_polygon.buffer(buffer_deg)


def dissolve_by_zip_code(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Dissolve (merge) Voronoi cells by ZIP code.

    Args:
        gdf: GeoDataFrame with zip_code and geometry columns

    Returns:
        GeoDataFrame with one row per ZIP code
    """
    # Group by ZIP code and union geometries
    dissolved = gdf.dissolve(by='zip_code', as_index=False)

    # Count points per ZIP code
    point_counts = gdf.groupby('zip_code').size().reset_index(name='point_count')
    dissolved = dissolved.merge(point_counts, on='zip_code')

    return dissolved


def simplify_and_smooth(gdf: gpd.GeoDataFrame, tolerance_meters: float) -> gpd.GeoDataFrame:
    """
    Simplify geometries using Douglas-Peucker algorithm.

    Args:
        gdf: GeoDataFrame with geometries
        tolerance_meters: Simplification tolerance in meters

    Returns:
        GeoDataFrame with simplified geometries
    """
    tolerance_deg = meters_to_degrees(tolerance_meters)

    simplified_geometries = []
    for geom in gdf.geometry:
        # Douglas-Peucker simplification
        simplified = geom.simplify(tolerance_deg, preserve_topology=True)

        # Ensure valid
        if not simplified.is_valid:
            simplified = simplified.buffer(0)

        simplified_geometries.append(simplified)

    gdf = gdf.copy()
    gdf['geometry'] = simplified_geometries
    return gdf


def apply_graph_coloring(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Apply Welsh-Powell greedy graph coloring to ensure adjacent polygons
    have different colors.
    """
    n = len(gdf)
    print(f"Building adjacency graph for {n} polygons...")

    # Build adjacency using spatial index
    spatial_index = gdf.sindex
    adjacency = {i: set() for i in range(n)}

    # Find all geometries that touch (not just intersect - we want shared borders)
    for i in range(n):
        geom = gdf.geometry.iloc[i]
        # Get candidates from spatial index
        candidates = list(spatial_index.intersection(geom.bounds))
        for j in candidates:
            if i != j:
                other_geom = gdf.geometry.iloc[j]
                # Check if they actually touch/intersect
                if geom.touches(other_geom) or geom.intersects(other_geom):
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
    gdf = gdf.copy()
    gdf['color_index'] = [colors[i] for i in range(n)]

    max_colors = gdf['color_index'].max() + 1
    print(f"Coloring complete using {max_colors} colors.")
    print(f"Color distribution: {gdf['color_index'].value_counts().to_dict()}")

    return gdf


def main():
    """Main polygon generation pipeline."""
    import argparse

    parser = argparse.ArgumentParser(description='ETL Step 2: Polygon Generation (Voronoi)')
    parser.add_argument('--input', type=Path, default=config.POINTS_PARQUET,
                        help='Input Parquet file path')
    parser.add_argument('--output', type=Path, default=config.POLYGONS_GPKG,
                        help='Output GeoPackage file path')
    parser.add_argument('--boundary', type=Path, default=config.BOUNDARY_GEOJSON,
                        help='Boundary GeoJSON file path')
    args = parser.parse_args()

    # Check if input file exists
    if not args.input.exists():
        print(f"Error: Input file not found: {args.input}")
        print(f"Please run 01_csv2parquet.py first")
        sys.exit(1)

    # Load points
    df = load_points(args.input)

    # Load clipping boundary from file, fallback to convex hull
    print(f"\nLoading clip boundary...")
    clip_boundary = load_boundary_from_file(args.boundary)
    if clip_boundary is None:
        print(f"  Boundary file not found, falling back to convex hull + {config.VORONOI_CLIP_BUFFER_METERS}m buffer...")
        clip_boundary = create_clip_boundary_from_hull(df, config.VORONOI_CLIP_BUFFER_METERS)

    # Generate Voronoi cells
    print("Generating Voronoi cells for all points...")
    voronoi_gdf = generate_voronoi_polygons(df, clip_boundary)
    print(f"  Created {len(voronoi_gdf):,} Voronoi cells")

    # Dissolve by ZIP code
    print("\nDissolving cells by ZIP code...")
    dissolved_gdf = dissolve_by_zip_code(voronoi_gdf)
    print(f"  Merged into {len(dissolved_gdf):,} ZIP code polygons")

    # Simplify geometries
    print(f"\nSimplifying geometries (tolerance: {config.SIMPLIFY_TOLERANCE_METERS}m)...")
    simplified_gdf = simplify_and_smooth(dissolved_gdf, config.SIMPLIFY_TOLERANCE_METERS)

    # Calculate areas
    simplified_gdf['area_km2'] = simplified_gdf.geometry.area * 111 * 71
    simplified_gdf['area_km2'] = simplified_gdf['area_km2'].round(2)

    # Add method column
    simplified_gdf['method'] = 'voronoi'

    # Apply graph coloring
    result_gdf = apply_graph_coloring(simplified_gdf)

    # Summary statistics
    print("\nSummary:")
    print(f"  Total polygons: {len(result_gdf):,}")
    print(f"  Total points: {result_gdf['point_count'].sum():,}")
    print(f"  Average points per ZIP code: {result_gdf['point_count'].mean():.1f}")
    print(f"  Median area: {result_gdf['area_km2'].median():.2f} km²")
    print(f"  Total area: {result_gdf['area_km2'].sum():.0f} km²")

    # Export to GeoPackage
    print(f"\nExporting to {args.output}...")
    args.output.parent.mkdir(parents=True, exist_ok=True)

    result_gdf.to_file(args.output, driver='GPKG', layer='zip_codes')

    file_size_mb = args.output.stat().st_size / 1024 / 1024
    print(f"Saved {len(result_gdf):,} polygons ({file_size_mb:.2f} MB)")
    print(f"Output: {args.output}")


if __name__ == "__main__":
    main()
