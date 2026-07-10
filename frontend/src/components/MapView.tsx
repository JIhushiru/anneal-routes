import maplibregl, { Map as MLMap, MapMouseEvent, Marker } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useReducer, useRef } from "react";
import { routeColorMap, routeDashArray } from "../lib/colors";
import type { Stop } from "../lib/types";
import { useStore } from "../state/store";
import { StopPopover } from "./StopPopover";

const MAP_STYLE = "https://tiles.openfreemap.org/styles/positron";
const PH_CENTER: [number, number] = [121.0, 14.58];

export function MapView() {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MLMap | null>(null);
  const depotMarkerRef = useRef<Marker | null>(null);
  const loadedRef = useRef(false);
  const [, tick] = useReducer((x: number) => x + 1, 0);

  const stops = useStore((s) => s.stops);
  const depot = useStore((s) => s.depot);
  const editMode = useStore((s) => s.editMode);
  const selectedStopId = useStore((s) => s.selectedStopId);
  const viewRun = useStore((s) => s.viewRun);
  const liveRoutes = useStore((s) => s.runs[s.viewRun].liveRoutes);

  // ------------------------------------------------------------- map creation
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: MAP_STYLE,
      center: PH_CENTER,
      zoom: 10.3,
      attributionControl: { compact: true },
    });
    mapRef.current = map;
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");

    map.on("load", () => {
      map.addSource("routes", { type: "geojson", data: emptyFC() });
      map.addSource("stops", { type: "geojson", data: emptyFC() });

      // Casing under the colored lines: the palette's sub-3:1 hues need a
      // surface ring to separate from the light map (dataviz relief rule).
      map.addLayer({
        id: "route-casing",
        type: "line",
        source: "routes",
        paint: { "line-color": "#ffffff", "line-width": 6, "line-opacity": 0.9 },
        layout: { "line-join": "round", "line-cap": "round" },
      });
      map.addLayer({
        id: "route-line",
        type: "line",
        source: "routes",
        filter: ["==", ["get", "dashed"], 0],
        paint: { "line-color": ["get", "color"], "line-width": 3 },
        layout: { "line-join": "round", "line-cap": "round" },
      });
      map.addLayer({
        id: "route-line-dashed",
        type: "line",
        source: "routes",
        filter: ["==", ["get", "dashed"], 1],
        paint: { "line-color": ["get", "color"], "line-width": 3, "line-dasharray": [2, 1.2] },
        layout: { "line-join": "round" },
      });

      map.addLayer({
        id: "stops-circle",
        type: "circle",
        source: "stops",
        paint: {
          "circle-radius": ["case", ["get", "selected"], 12, 10],
          "circle-color": [
            "case",
            ["get", "selected"], "#2a78d6",
            ["get", "windowed"], "#334155",
            "#64748b",
          ],
          "circle-stroke-color": "#ffffff",
          "circle-stroke-width": 2,
        },
      });
      map.addLayer({
        id: "stops-label",
        type: "symbol",
        source: "stops",
        layout: {
          "text-field": ["to-string", ["get", "id"]],
          "text-font": ["Noto Sans Regular"],
          "text-size": 11,
          "text-allow-overlap": true,
        },
        paint: { "text-color": "#ffffff" },
      });

      loadedRef.current = true;
      tick(); // flush initial data into the freshly created sources
    });

    // Cursor feedback over stops.
    map.on("mousemove", (e) => {
      const over = map.queryRenderedFeatures(e.point, { layers: layersIfReady(map) }).length > 0;
      map.getCanvas().style.cursor = over ? "pointer" : "crosshair";
    });

    // One click handler decides: select a stop, set the depot, or add a stop.
    map.on("click", (e: MapMouseEvent) => {
      const state = useStore.getState();
      const hits = map.queryRenderedFeatures(e.point, { layers: layersIfReady(map) });
      if (hits.length > 0) {
        state.selectStop(hits[0].properties.id as number);
        return;
      }
      if (state.editMode === "set-depot") {
        state.setDepot(e.lngLat.lat, e.lngLat.lng);
        state.setEditMode("add-stop");
      } else {
        state.addStop(e.lngLat.lat, e.lngLat.lng);
      }
    });

    // Drag-to-move stops: grab on the circle layer, pan disabled while dragging.
    map.on("mousedown", "stops-circle", (e) => {
      e.preventDefault();
      const id = e.features?.[0]?.properties.id as number | undefined;
      if (id === undefined) return;
      map.dragPan.disable();
      const onMove = (ev: MapMouseEvent) => {
        useStore.getState().moveStop(id, ev.lngLat.lat, ev.lngLat.lng);
      };
      map.on("mousemove", onMove);
      map.once("mouseup", () => {
        map.off("mousemove", onMove);
        map.dragPan.enable();
      });
    });

    // Keep the popover glued to its stop while panning/zooming.
    map.on("move", () => tick());

    return () => {
      map.remove();
      mapRef.current = null;
      loadedRef.current = false;
    };
  }, []);

  // ------------------------------------------------------------- depot marker
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (!depotMarkerRef.current) {
      const el = document.createElement("div");
      el.className = "depot-marker";
      el.textContent = "▲";
      el.title = "Depot (drag to move)";
      const marker = new maplibregl.Marker({ element: el, draggable: true })
        .setLngLat([depot.lon, depot.lat])
        .addTo(map);
      marker.on("dragend", () => {
        const pos = marker.getLngLat();
        useStore.getState().setDepot(pos.lat, pos.lng);
      });
      depotMarkerRef.current = marker;
    } else {
      depotMarkerRef.current.setLngLat([depot.lon, depot.lat]);
    }
  }, [depot]);

  // --------------------------------------------------------------- data sync
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !loadedRef.current) return;

    (map.getSource("stops") as maplibregl.GeoJSONSource).setData({
      type: "FeatureCollection",
      features: stops.map((s) => ({
        type: "Feature",
        geometry: { type: "Point", coordinates: [s.lon, s.lat] },
        properties: {
          id: s.id,
          selected: s.id === selectedStopId,
          windowed: s.tw_start !== null || s.tw_end !== null,
        },
      })),
    });

    const stopById = new Map(stops.map((s) => [s.id, s]));
    (map.getSource("routes") as maplibregl.GeoJSONSource).setData({
      type: "FeatureCollection",
      features: liveRoutes
        .map((stopIds, vehicle) => {
          const pts = stopIds
            .map((id) => stopById.get(id))
            .filter((s): s is Stop => s !== undefined);
          if (pts.length === 0) return null;
          return {
            type: "Feature" as const,
            geometry: {
              type: "LineString" as const,
              coordinates: [
                [depot.lon, depot.lat],
                ...pts.map((s) => [s.lon, s.lat]),
                [depot.lon, depot.lat],
              ],
            },
            properties: {
              color: routeColorMap(vehicle),
              dashed: routeDashArray(vehicle) ? 1 : 0,
            },
          };
        })
        .filter((f): f is NonNullable<typeof f> => f !== null),
    });
  });

  const selectedStop = stops.find((s) => s.id === selectedStopId) ?? null;
  const anchor =
    selectedStop && mapRef.current
      ? mapRef.current.project([selectedStop.lon, selectedStop.lat])
      : null;

  return (
    <div className="map-wrap" data-mode={editMode} data-view-run={viewRun}>
      <div ref={containerRef} className="map-container" />
      {selectedStop && anchor && (
        <StopPopover stop={selectedStop} x={anchor.x} y={anchor.y} />
      )}
    </div>
  );
}

function emptyFC(): GeoJSON.FeatureCollection {
  return { type: "FeatureCollection", features: [] };
}

function layersIfReady(map: MLMap): string[] {
  return map.getLayer("stops-circle") ? ["stops-circle"] : [];
}
