## Uvalde, Texas Map Prep

This folder is the compact Uvalde case-study scaffold for this project.

- Current flood context was confirmed from live reporting and active south-central Texas/NWS flood messaging on 2026-07-16.
- The Texas Flood Information Viewer was usable for current conditions and centered Uvalde at roughly `29.21278, -99.77514`.
- A small AOI was chosen on purpose so app runs stay lightweight enough for interactive use.

Local files in this folder:

- `create_aoi.py`: writes the compact Uvalde AOI GeoJSON.
- `build_view_aoi_map.py`: writes HTML preview maps for the AOI and any local flood GeoJSON dropped into this folder later.
- `build_twdb_cursory_flood.py`: downloads the official TWDB 2025 Scenario 5 flood raster tile for the Uvalde AOI, polygonizes flooded cells, and writes a local flood GeoJSON.
- `download_osm_layers.py`: optional OSM pull for buildings, POIs, and land use within the compact AOI.

Current local inundation workflow:

- `python .\space\Uvalde_TX_map_data\build_twdb_cursory_flood.py` builds `uvalde_twdb_scenario5_1in100_flood.geojson` from the TWDB 2025 cursory floodplain tile covering Uvalde.
- `python .\space\Uvalde_TX_map_data\build_view_aoi_map.py` refreshes `view_aoi_flood_map.html` so the local TWDB flood layer appears in blue.

## Flood-data provenance and model interpretation

The active flood footprint is derived from the Texas Water Development Board
(TWDB) 2025 Cursory Floodplain Data distribution. The build script downloads
the `Scenario_5_Existing_Conditions` Fathom 3 m combined-peril depth raster
tile `n29w100`, extracts the selected return-period cells with positive depth,
and clips the result to the compact Uvalde AOI. The current runtime uses the
`1in100` output. TWDB distributes this product as planning-level flood-risk
information; it is not a time-resolved hydraulic simulation.

The ABM therefore uses one flood footprint and applies a documented directional
rise-and-recession envelope during the event. This provides spatially staggered
exposure for behavioral and health experiments without claiming that the
inundation file contains observed arrival times or flow velocities.

Recommended supporting sources for calibration and future improvement:

- TWDB Texas Flood Information Viewer: https://map.texasflood.org/
- USGS Water Data for the Nation and real-time gauges: https://waterdata.usgs.gov/nwis/rt
- USGS Real-Time Flood Impact Map: https://apps.usgs.gov/rtfi-map/
- NOAA/NWS precipitation-frequency estimates: https://hdsc.nws.noaa.gov/hdsc/pfds/
- USACE HEC-RAS, including one- and two-dimensional unsteady-flow modeling:
	https://www.hec.usace.army.mil/software/hec-ras/

For a hydraulically calibrated future version, combine a Uvalde-area digital
elevation model, channel and drainage data, rainfall or gauge hydrographs, and
HEC-RAS 2D or an equivalent hydraulic model. Export depth grids or polygons at
successive times and use those outputs to replace the conceptual wave envelope.

Useful live sources:

- https://map.texasflood.org/
- https://www.weather.gov/
- https://apps.usgs.gov/rtfi-map/#/