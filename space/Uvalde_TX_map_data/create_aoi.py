from pathlib import Path

import geopandas as gpd
from shapely.geometry import box


def main() -> None:
    out_dir = Path(__file__).resolve().parent

    # Compact Uvalde corridor sized so the
    # map remains responsive in the app while still covering the city core and
    # the nearby Nueces River flood corridor.
    min_lon = -99.83
    min_lat = 29.16
    max_lon = -99.72
    max_lat = 29.26

    aoi = gpd.GeoDataFrame(
        {
            "name": ["uvalde_nueces_corridor"],
            "description": [
                "Compact flood-focused AOI for Uvalde, Texas centered on the urban core and nearby Nueces River corridor"
            ],
        },
        geometry=[box(min_lon, min_lat, max_lon, max_lat)],
        crs="EPSG:4326",
    )

    out_file = out_dir / "uvalde_aoi.geojson"
    aoi.to_file(out_file, driver="GeoJSON")

    print(f"Wrote AOI: {out_file}")
    print(f"CRS: {aoi.crs}")
    print(f"Bounds lon/lat: {aoi.total_bounds.tolist()}")


if __name__ == "__main__":
    main()