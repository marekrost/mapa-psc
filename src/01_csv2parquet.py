#!/usr/bin/env python3
"""
ETL Step 1: Data Preparation
- Load RÚIAN CSV with CP-1250 encoding
- Filter required attributes
- Transform S-JTSK (EPSG:5514) to WGS84 (EPSG:4326)
- Export to Parquet format
"""

import sys
from pathlib import Path

import pandas as pd
from pyproj import Transformer

# Add project root to path for config import
sys.path.insert(0, str(Path(__file__).parent))
import config


def load_ruian_csv(csv_path: Path) -> pd.DataFrame:
    """
    Load RÚIAN CSV with proper encoding.

    Args:
        csv_path: Path to input CSV file

    Returns:
        DataFrame with raw data
    """
    print(f"Loading CSV from {csv_path}...")

    # RÚIAN CSV uses semicolon delimiter
    df = pd.read_csv(
        csv_path,
        encoding=config.CSV_ENCODING,
        delimiter=';',
        low_memory=False,
    )

    print(f"Loaded {len(df):,} rows, {len(df.columns)} columns")
    print(f"Columns: {df.columns.tolist()[:5]}...")  # Show first 5 columns
    return df


def filter_and_validate(df: pd.DataFrame) -> pd.DataFrame:
    """
    Filter rows with required attributes and validate data.

    Args:
        df: Raw DataFrame

    Returns:
        Filtered DataFrame with valid records
    """
    print("Filtering and validating data...")

    initial_count = len(df)

    # RÚIAN VFR CSV structure:
    # Expected columns (by position in standard RÚIAN format):
    # 0: Kód ADM (ID)
    # 15: PSČ
    # 16: Souřadnice Y
    # 17: Souřadnice X

    # Normalize column names for pattern matching
    df.columns = df.columns.str.strip()
    cols_lower = [col.lower() for col in df.columns]

    # Try to find PSČ column by pattern
    psc_col = None
    for i, col in enumerate(cols_lower):
        # Look for 'psc' or 'ps' followed by special char (encoding issues)
        if 'psc' in col or (col.startswith('ps') and len(col) <= 4):
            psc_col = df.columns[i]
            print(f"Found PSČ column: '{psc_col}' at position {i}")
            break

    # Fallback to known position if pattern matching fails
    if psc_col is None and len(df.columns) > 15:
        psc_col = df.columns[15]
        print(f"Using position-based PSČ column: '{psc_col}' at position 15")

    # Try to find Y coordinate column
    y_col = None
    for i, col in enumerate(cols_lower):
        if 'souradnice' in col and 'y' in col:
            y_col = df.columns[i]
            print(f"Found Y coordinate column: '{y_col}' at position {i}")
            break
        elif col == 'souřadnice y':
            y_col = df.columns[i]
            print(f"Found Y coordinate column: '{y_col}' at position {i}")
            break

    # Fallback to known position
    if y_col is None and len(df.columns) > 16:
        y_col = df.columns[16]
        print(f"Using position-based Y column: '{y_col}' at position 16")

    # Try to find X coordinate column
    x_col = None
    for i, col in enumerate(cols_lower):
        if 'souradnice' in col and 'x' in col:
            x_col = df.columns[i]
            print(f"Found X coordinate column: '{x_col}' at position {i}")
            break
        elif col == 'souřadnice x':
            x_col = df.columns[i]
            print(f"Found X coordinate column: '{x_col}' at position {i}")
            break

    # Fallback to known position
    if x_col is None and len(df.columns) > 17:
        x_col = df.columns[17]
        print(f"Using position-based X column: '{x_col}' at position 17")

    # Try to find ID column (first column with 'kod' or 'kód')
    id_col = None
    for i, col in enumerate(cols_lower):
        if 'kod' in col and 'adm' in col:
            id_col = df.columns[i]
            print(f"Found ID column: '{id_col}' at position {i}")
            break

    # Fallback to first column
    if id_col is None and len(df.columns) > 0:
        id_col = df.columns[0]
        print(f"Using position-based ID column: '{id_col}' at position 0")

    # Validate we found all required columns
    if not all([psc_col, x_col, y_col]):
        raise ValueError(
            f"Could not find required columns.\n"
            f"PSČ: {psc_col}\n"
            f"X: {x_col}\n"
            f"Y: {y_col}\n"
            f"Available columns: {df.columns.tolist()}"
        )

    # Rename to standard names
    rename_map = {
        psc_col: 'psc',
        x_col: 'x',
        y_col: 'y',
    }
    if id_col:
        rename_map[id_col] = 'id_adresniho_mista'

    df = df.rename(columns=rename_map)

    # Keep only necessary columns
    keep_cols = ['psc', 'x', 'y']
    if 'id_adresniho_mista' in df.columns:
        keep_cols.append('id_adresniho_mista')

    df = df[keep_cols].copy()

    # Remove rows with missing values
    df = df.dropna(subset=['psc', 'x', 'y'])

    # Remove invalid coordinates (zeros or obviously wrong values)
    df = df[(df['x'] != 0) & (df['y'] != 0)]

    # Clean PSČ - remove spaces and ensure 5 digits
    df['psc'] = df['psc'].astype(str).str.replace(' ', '').str.strip()

    # Filter to valid 5-digit PSČ
    valid_psc_mask = df['psc'].str.match(r'^\d{5}$', na=False)
    df = df[valid_psc_mask]

    print(f"Filtered: {initial_count:,} -> {len(df):,} rows ({len(df)/initial_count*100:.1f}%)")
    print(f"Unique PSČ: {df['psc'].nunique():,}")

    return df


def transform_coordinates(df: pd.DataFrame) -> pd.DataFrame:
    """
    Transform coordinates from S-JTSK to WGS84.

    Args:
        df: DataFrame with x, y in S-JTSK

    Returns:
        DataFrame with lon, lat in WGS84
    """
    print("Transforming coordinates S-JTSK -> WGS84...")

    # Create transformer
    transformer = Transformer.from_crs(
        config.CRS_SOURCE,
        config.CRS_TARGET,
        always_xy=True
    )

    # Transform coordinates
    # Note: RÚIAN provides positive values, but S-JTSK uses negative coordinates
    # (Krovak projection with southing/westing). We need to negate both values.
    # Also, RÚIAN's 'Souřadnice Y' is easting and 'Souřadnice X' is northing in S-JTSK terms.
    lon, lat = transformer.transform(-df['y'].values, -df['x'].values)

    df['lon'] = lon
    df['lat'] = lat

    # Drop original coordinates
    df = df.drop(columns=['x', 'y'])

    # Validate transformed coordinates (rough Czech Republic bounds)
    valid_lon = (df['lon'] >= 12) & (df['lon'] <= 19)
    valid_lat = (df['lat'] >= 48) & (df['lat'] <= 52)

    invalid_count = (~(valid_lon & valid_lat)).sum()
    if invalid_count > 0:
        print(f"Warning: {invalid_count} coordinates outside expected bounds (will be kept)")

    return df


def export_to_parquet(df: pd.DataFrame, output_path: Path):
    """
    Export DataFrame to Parquet format.

    Args:
        df: Processed DataFrame
        output_path: Output Parquet file path
    """
    print(f"Exporting to {output_path}...")

    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Export with compression
    df.to_parquet(
        output_path,
        engine='pyarrow',
        compression='snappy',
        index=False
    )

    file_size_mb = output_path.stat().st_size / 1024 / 1024
    print(f"Saved {len(df):,} rows ({file_size_mb:.2f} MB)")


def main():
    """Main ETL pipeline."""
    import argparse

    parser = argparse.ArgumentParser(description='ETL Step 1: Data Preparation')
    parser.add_argument('--input', type=Path, default=config.INPUT_CSV,
                        help='Input CSV file path')
    parser.add_argument('--output', type=Path, default=config.POINTS_PARQUET,
                        help='Output Parquet file path')
    args = parser.parse_args()

    print("=" * 60)
    print("ETL Step 1: Data Preparation")
    print("=" * 60)

    # Check if input file exists
    if not args.input.exists():
        print(f"Error: Input file not found: {args.input}")
        print(f"Please place RÚIAN CSV file at: {args.input}")
        sys.exit(1)

    # Load data
    df = load_ruian_csv(args.input)

    # Filter and validate
    df = filter_and_validate(df)

    # Transform coordinates
    df = transform_coordinates(df)

    # Export to Parquet
    export_to_parquet(df, args.output)

    print("=" * 60)
    print("Step 1 completed successfully!")
    print(f"Output: {args.output}")
    print("=" * 60)


if __name__ == "__main__":
    main()
