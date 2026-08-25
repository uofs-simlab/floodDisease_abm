from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd


ROOT = Path(__file__).resolve().parent
AOI_FILE = ROOT / "uvalde_aoi.geojson"
VIEW_FILE = ROOT / "view_aoi_map.html"
FLOOD_VIEW_FILE = ROOT / "view_aoi_flood_map.html"


def load_geojson(path: Path) -> dict | None:
    if not path.exists():
        return None
    gdf = gpd.read_file(path)
    if gdf.empty:
        return None
    return json.loads(gdf.to_json())


def render_html(aoi_js: str, flood_js: str, include_flood: bool) -> str:
    title = "Uvalde AOI Flood Preview" if include_flood else "Uvalde AOI Preview"
    flood_note = (
        "Local flood GeoJSON layers found in this folder are shown in blue."
        if include_flood
        else "This view shows the compact AOI only. Open view_aoi_flood_map.html to inspect the inundation layer."
    )
    active_flood_js = flood_js if include_flood else "[]"

    return f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title}</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" crossorigin="" />
  <style>
    html, body, #map {{ height: 100%; margin: 0; }}
    .panel {{
      background: rgba(255, 255, 255, 0.95);
      border: 1px solid #999;
      border-radius: 6px;
      box-shadow: 0 1px 4px rgba(0,0,0,.25);
      color: #222;
      font: 13px/1.4 sans-serif;
      max-width: 320px;
      padding: 10px 12px;
    }}
    .panel b {{ display: block; margin-bottom: 4px; }}
    .panel a {{ color: #0f4c81; }}
  </style>
</head>
<body>
  <div id="map"></div>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" crossorigin=""></script>
  <script>
    const aoi = {aoi_js};
    const floodLayers = {active_flood_js};
    const map = L.map("map").setView([29.21278, -99.77514], 13);
    L.tileLayer("https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png", {{
      maxZoom: 19,
      attribution: "&copy; OpenStreetMap contributors"
    }}).addTo(map);

    const bounds = [];
    const aoiLayer = L.geoJSON(aoi, {{
      style: {{ color: "#b42318", weight: 3, fillColor: "#f59e0b", fillOpacity: 0.12 }}
    }}).addTo(map);
    if (aoiLayer.getLayers().length) {{
      bounds.push(aoiLayer.getBounds());
      aoiLayer.eachLayer((feature) => {{
        const props = feature.feature && feature.feature.properties ? feature.feature.properties : {{}};
        feature.bindPopup(`<b>${{props.name || "Uvalde AOI"}}</b><br/>${{props.description || "Compact study area"}}`);
      }});
    }}

    const centerMarker = L.circleMarker([29.21278, -99.77514], {{
      radius: 6,
      color: "#0f172a",
      weight: 2,
      fillColor: "#22c55e",
      fillOpacity: 0.95,
    }}).addTo(map);
    centerMarker.bindPopup("<b>Uvalde city center</b><br/>Reference point for compact AOI");

    floodLayers.forEach((layerDef) => {{
      const data = layerDef.data || {{ type: "FeatureCollection", features: [] }};
      const layer = L.geoJSON(data, {{
        style: {{
          color: "#1d4ed8",
          weight: 2,
          opacity: 0.9,
          fillColor: "rgba(29, 78, 216, 0.08)",
          fillOpacity: 0.12,
        }}
      }}).addTo(map);
      if (layer.getLayers().length) {{
        bounds.push(layer.getBounds());
      }}
      layer.eachLayer((feature) => {{
        const props = feature.feature && feature.feature.properties ? feature.feature.properties : {{}};
        feature.bindPopup(`<b>${{layerDef.name}}</b><br/>${{props.flood_stage || props.source || "local flood layer"}}`);
      }});
    }});

    if (bounds.length) {{
      const combined = L.latLngBounds([]);
      bounds.forEach((item) => combined.extend(item));
      map.fitBounds(combined, {{ padding: [24, 24] }});
    }}

    const panel = L.control({{ position: "topright" }});
    panel.onAdd = function () {{
      const div = L.DomUtil.create("div", "panel");
      div.innerHTML = `
        <b>Uvalde Study Area</b>
        Compact corridor around central Uvalde and the nearby Nueces River flood pathway.<br/><br/>
        {flood_note}<br/><br/>
        Current flood context:<br/>
        <a href="https://map.texasflood.org/" target="_blank" rel="noreferrer">Texas Flood Information Viewer</a><br/>
        <a href="https://www.weather.gov/" target="_blank" rel="noreferrer">NWS weather alerts</a><br/>
        <a href="https://apps.usgs.gov/rtfi-map/#/" target="_blank" rel="noreferrer">USGS Real-Time Flood Impact Map</a>
      `;
      return div;
    }};
    panel.addTo(map);
  </script>
</body>
</html>'''


def main() -> None:
    aoi = load_geojson(AOI_FILE)
    aoi_js = json.dumps(aoi or {"type": "FeatureCollection", "features": []})

    flood_source_paths = sorted(
        path
        for path in ROOT.glob("*flood*.geojson")
        if path.name != AOI_FILE.name
    )

    flood_layers = []
    for path in flood_source_paths:
        data = load_geojson(path)
        flood_layers.append(
            {
                "name": path.stem,
                "data": data or {"type": "FeatureCollection", "features": []},
            }
        )
    flood_js = json.dumps(flood_layers)

    VIEW_FILE.write_text(render_html(aoi_js, flood_js, include_flood=False), encoding="utf-8")
    FLOOD_VIEW_FILE.write_text(render_html(aoi_js, flood_js, include_flood=True), encoding="utf-8")
    print(f"Wrote {VIEW_FILE}")
    print(f"Wrote {FLOOD_VIEW_FILE}")


if __name__ == "__main__":
    main()