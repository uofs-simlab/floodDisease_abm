from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
import requests
from rasterio.features import shapes
from rasterio.windows import from_bounds
from shapely.geometry import shape
from shapely.ops import unary_union


ROOT = Path(__file__).resolve().parent
AOI_FILE = ROOT / "uvalde_aoi.geojson"
CACHE_DIR = ROOT / "raw" / "twdb_cursory"
OUTPUT_TEMPLATE = "uvalde_twdb_scenario5_{return_period}_flood.geojson"

TWDB_TILE_TEMPLATE = (
    "https://s3.amazonaws.com/twdb-gis-data/"
    "Staged/office-of-planning/flood-planning/flood-data/flood-risk/"
    "cursory-floodplain-data-2025/Scenario_5_Existing_Conditions/"
    "Fathom_3m_Combined_Peril_Scenario_5_Depth_Raster_Tiles/{folder}/"
    "n29w100_2020_0p50_combined_{folder}.zip"
)

RETURN_PERIOD_FOLDERS = {
    "1in5": "1in5",
    "1in10": "1in10",
    "1in25": "1in25",
    "1in100": "1in100",
    "1in500": "1in500",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a compact Uvalde flood polygon from the official TWDB 2025 "
            "Scenario 5 cursory flood raster tile."
        )
    )
    parser.add_argument(
        "--return-period",
        default="1in100",
        choices=sorted(RETURN_PERIOD_FOLDERS),
        help="Flood frequency folder to extract from the TWDB Scenario 5 dataset.",
    )
    parser.add_argument(
        "--force-download",
        action="store_true",
        help="Re-download the source zip even if it already exists locally.",
    )
    return parser.parse_args()


def download_file(url: str, destination: Path, force: bool) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and not force:
        return destination

    with requests.get(url, stream=True, timeout=120) as response:
        response.raise_for_status()
        with destination.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=8 * 1024 * 1024):
                if chunk:
                    handle.write(chunk)
    return destination


def find_raster_member(zip_path: Path) -> str:
    with zipfile.ZipFile(zip_path) as archive:
        raster_members = [
            name
            for name in archive.namelist()
            if name.lower().endswith((".tif", ".tiff"))
        ]
    if not raster_members:
        raise FileNotFoundError(f"No GeoTIFF found inside {zip_path}")
    if len(raster_members) > 1:
        raster_members.sort(key=lambda name: ("combined" not in name.lower(), len(name)))
    return raster_members[0]


def raster_zip_uri(zip_path: Path, member: str) -> str:
    return f"zip://{zip_path.as_posix()}!{member}"


def build_flood_polygons(
    zip_path: Path,
    member: str,
    aoi: gpd.GeoDataFrame,
    return_period: str,
) -> gpd.GeoDataFrame:
    aoi_4326 = aoi.to_crs("EPSG:4326")
    aoi_geom = unary_union(aoi_4326.geometry)

    with rasterio.open(raster_zip_uri(zip_path, member)) as src:
        if src.crs is None:
            raise ValueError("Source raster has no CRS")

        aoi_src = aoi_4326.to_crs(src.crs)
        min_x, min_y, max_x, max_y = aoi_src.total_bounds
        window = from_bounds(min_x, min_y, max_x, max_y, src.transform)
        window = window.round_offsets().round_lengths()
        data = src.read(1, window=window, masked=True)
        transform = src.window_transform(window)

        filled = np.ma.filled(data, np.nan)
        valid = np.isfinite(filled)
        flooded = valid & (filled > 0)
        if not flooded.any():
            raise ValueError("No flooded cells were found for the AOI in the selected tile")

        polygon_geoms = []
        for geom, value in shapes(flooded.astype(np.uint8), mask=flooded, transform=transform):
            if value != 1:
                continue
            polygon_geoms.append(shape(geom))

    if not polygon_geoms:
        raise ValueError("Polygonization produced no flooded geometry")

    dissolved = unary_union(polygon_geoms)
    clipped = dissolved.intersection(aoi_geom)
    if clipped.is_empty:
        raise ValueError("Flood geometry does not intersect the AOI after clipping")

    clipped = clipped.buffer(0)
    result = gpd.GeoDataFrame(
        {
            "source": ["TWDB Cursory Floodplain Data 2025"],
            "scenario": ["Scenario 5 Existing Conditions"],
            "tile_id": ["n29w100"],
            "return_period": [return_period],
            "description": [
                "Official TWDB/Fathom statewide 3 m combined-peril flood depth tile clipped to the compact Uvalde AOI"
            ],
        },
        geometry=[clipped],
        crs="EPSG:4326",
    )
    return result


def main(args: argparse.Namespace) -> None:
    aoi = gpd.read_file(AOI_FILE)
    if aoi.empty:
        raise ValueError(f"AOI file has no geometry: {AOI_FILE}")

    folder = RETURN_PERIOD_FOLDERS[args.return_period]
    url = TWDB_TILE_TEMPLATE.format(folder=folder)
    zip_name = Path(url).name
    zip_path = CACHE_DIR / zip_name

    print(f"Downloading or reusing TWDB tile: {zip_name}")
    download_file(url, zip_path, force=args.force_download)
    print(f"Tile zip: {zip_path}")

    member = find_raster_member(zip_path)
    print(f"Raster member: {member}")

    flood = build_flood_polygons(zip_path, member, aoi, args.return_period)
    output_path = ROOT / OUTPUT_TEMPLATE.format(return_period=args.return_period)
    flood.to_file(output_path, driver="GeoJSON")

    area_sqkm = flood.to_crs("EPSG:3857").area.iloc[0] / 1_000_000
    print(f"Wrote flood GeoJSON: {output_path}")
    print(f"Return period: {args.return_period}")
    print(f"Approximate clipped area (sq km): {area_sqkm:.3f}")


if __name__ == "__main__":
    args = parse_args()
    main(args)