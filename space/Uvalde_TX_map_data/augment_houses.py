from __future__ import annotations

from pathlib import Path
import math

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, MultiLineString, Point
from shapely.ops import unary_union


BASE_DIR = Path(__file__).resolve().parent
RAW_DIR = BASE_DIR / "raw"
PROCESSED_DIR = BASE_DIR / "processed"
AOI_FILE = BASE_DIR / "uvalde_aoi.geojson"
BUILDINGS_FILE = PROCESSED_DIR / "abm_places.gpkg"
HOUSES_OUT_FILE = PROCESSED_DIR / "houses_augmented.geojson"

TARGET_POPULATION = 15_455
PERSONS_PER_HOUSEHOLD = 2.83
TARGET_HOUSEHOLDS = int(round(TARGET_POPULATION / PERSONS_PER_HOUSEHOLD))
BUILDING_BUFFER_M = 120.0
ROAD_OFFSET_M = 12.0
HOUSE_HALF_SIZE_M = 6.0
MIN_ROAD_LENGTH_M = 12.0

LOCAL_ROAD_TYPES = {
    "residential",
    "living_street",
    "service",
    "unclassified",
    "tertiary",
    "tertiary_link",
    "secondary",
    "secondary_link",
}


def read_gdf(path: Path, layer: str | None = None) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(path, layer=layer) if layer else gpd.read_file(path)
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")
    return gdf


def _highway_text(value) -> str:
    if isinstance(value, (list, tuple)):
        value = value[0] if value else ""
    return str(value or "").strip().lower()


def load_local_roads() -> gpd.GeoDataFrame:
    roads = read_gdf(RAW_DIR / "osm_roads.geojson")
    roads = roads[roads.geometry.notnull() & ~roads.geometry.is_empty].copy()
    roads["highway_type"] = roads["highway"].map(_highway_text)
    roads = roads[roads["highway_type"].isin(LOCAL_ROAD_TYPES)].copy()
    return roads


def _extract_lines(geometry) -> list[LineString]:
    if geometry is None or geometry.is_empty:
        return []
    if isinstance(geometry, LineString):
        return [geometry]
    if isinstance(geometry, MultiLineString):
        return [line for line in geometry.geoms if line.length > 0]
    if hasattr(geometry, "geoms"):
        lines = []
        for part in geometry.geoms:
            lines.extend(_extract_lines(part))
        return lines
    return []


def _point_along_with_offset(line: LineString, distance_m: float, offset_m: float) -> Point:
    distance_m = max(0.0, min(float(distance_m), max(0.0, line.length - 0.01)))
    base = line.interpolate(distance_m)

    delta = min(2.0, max(0.5, line.length * 0.05))
    before = line.interpolate(max(0.0, distance_m - delta))
    after = line.interpolate(min(line.length, distance_m + delta))
    dx = after.x - before.x
    dy = after.y - before.y
    norm = math.hypot(dx, dy)
    if norm <= 1e-6:
        return base

    nx = -dy / norm
    ny = dx / norm
    return Point(base.x + nx * offset_m, base.y + ny * offset_m)


def _sample_house_geometries(roads: gpd.GeoDataFrame, sample_count: int, aoi_geom) -> list:
    line_items: list[tuple[LineString, float]] = []
    total_length = 0.0
    for geom in roads.geometry:
        for line in _extract_lines(geom):
            if line.length >= MIN_ROAD_LENGTH_M:
                line_items.append((line, line.length))
                total_length += line.length

    if sample_count <= 0 or total_length <= 0.0:
        return []

    step = total_length / float(sample_count)
    geometries = []
    line_index = 0
    traversed = 0.0
    current_line, current_len = line_items[line_index]

    for idx in range(sample_count):
        target_distance = (idx + 0.5) * step
        while traversed + current_len < target_distance and line_index < len(line_items) - 1:
            traversed += current_len
            line_index += 1
            current_line, current_len = line_items[line_index]

        local_distance = max(0.0, target_distance - traversed)
        side = -1.0 if idx % 2 else 1.0
        pt = _point_along_with_offset(current_line, local_distance, side * ROAD_OFFSET_M)
        if not aoi_geom.contains(pt):
            pt = current_line.interpolate(max(0.0, min(local_distance, current_len)))
        geom = pt.buffer(HOUSE_HALF_SIZE_M, cap_style=3)
        geometries.append(geom)
    return geometries


def main() -> None:
    aoi = read_gdf(AOI_FILE).to_crs(3857)
    aoi_geom = aoi.geometry.iloc[0]

    existing_houses = read_gdf(BUILDINGS_FILE, layer="houses").to_crs(3857)
    existing_houses = existing_houses[existing_houses.geometry.notnull() & ~existing_houses.geometry.is_empty].copy()

    roads = load_local_roads().to_crs(3857)

    developed_mask = roads.geometry.intersects(unary_union(existing_houses.geometry.buffer(BUILDING_BUFFER_M)))
    developed_roads = roads[developed_mask].copy()
    if developed_roads.empty:
        developed_roads = roads.copy()

    additional_needed = max(0, TARGET_HOUSEHOLDS - len(existing_houses))
    synthetic_geoms = _sample_house_geometries(developed_roads, additional_needed, aoi_geom)

    synthetic = gpd.GeoDataFrame(
        {
            "category": ["house"] * len(synthetic_geoms),
            "building_tag": ["synthetic_house"] * len(synthetic_geoms),
            "name_clean": [""] * len(synthetic_geoms),
            "source": ["synthetic_roads"] * len(synthetic_geoms),
        },
        geometry=synthetic_geoms,
        crs="EPSG:3857",
    )

    existing = existing_houses.copy()
    if "source" not in existing.columns:
        existing["source"] = "osm_building"
    for col in ["category", "building_tag", "name_clean"]:
        if col not in existing.columns:
            existing[col] = "house" if col == "category" else ""

    keep_cols = ["category", "building_tag", "name_clean", "source", "geometry"]
    combined = pd.concat([existing[keep_cols], synthetic[keep_cols]], ignore_index=True)
    combined = gpd.GeoDataFrame(combined, geometry="geometry", crs="EPSG:3857").to_crs(4326)

    HOUSES_OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    combined.to_file(HOUSES_OUT_FILE, driver="GeoJSON")

    print(
        {
            "existing_houses": int(len(existing_houses)),
            "synthetic_houses_added": int(len(synthetic)),
            "total_houses": int(len(combined)),
            "target_households": int(TARGET_HOUSEHOLDS),
            "target_population": int(TARGET_POPULATION),
        }
    )


if __name__ == "__main__":
    main()