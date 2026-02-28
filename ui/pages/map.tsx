import { useEffect, useRef, useState } from 'react';
import mapboxgl, { Map, LngLatLike, Popup } from 'mapbox-gl';
import { Button } from '../components/ui/Button';
import { Select } from '../components/ui/Select';
import { Switch } from '../components/ui/Switch';
import { Kpis } from '../components/Kpis';
import { Legend } from '../components/Legend';
import { AnomalyTable } from '../components/AnomalyTable';
import { ModelTelemetry } from '../components/ModelTelemetry';
import { useRoutes, useSummary, useStops, useHeatmap, useModelTelemetry } from '../lib/hooks';
import { scoreToColor } from '../lib/utils';
import { formatNYFromEpoch, fromNowEpoch } from '../lib/time';

const MAPBOX_TOKEN = process.env.NEXT_PUBLIC_MAPBOX_TOKEN as string | undefined;
const NYC_CENTER: LngLatLike = [-73.9851, 40.7589];

export default function MapPage() {
  const mapRef = useRef<Map | null>(null);
  const mapContainer = useRef<HTMLDivElement | null>(null);
  const [routeId, setRouteId] = useState<string>('All');
  const [autoRefresh, setAutoRefresh] = useState<boolean>(true);

  const routes = useRoutes();
  const summary = useSummary('15m', autoRefresh ? 15000 : undefined);
  const stops = useStops();
  const heatmap = useHeatmap(routeId, '60m', autoRefresh ? 15000 : undefined);
  const telemetry = useModelTelemetry(autoRefresh ? 30000 : undefined);

  useEffect(() => {
    if (!MAPBOX_TOKEN) return;
    mapboxgl.accessToken = MAPBOX_TOKEN;
    if (mapRef.current || !mapContainer.current) return;
    const map = new mapboxgl.Map({
      container: mapContainer.current,
      style: 'mapbox://styles/mapbox/light-v11',
      center: NYC_CENTER,
      zoom: 10.5,
      attributionControl: true,
    });
    map.addControl(new mapboxgl.NavigationControl({ showCompass: false }));
    map.on('load', () => {
      // stations source
      map.addSource('srcStations', {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] },
        cluster: true,
        clusterRadius: 25,
      } as any);
      map.addLayer({ id: 'stations', type: 'circle', source: 'srcStations', paint: { 'circle-radius': 3.5, 'circle-opacity': 0.8, 'circle-color': '#34d399' } });

      // anomalies
      map.addSource('srcAnoms', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } as any });
      map.addLayer({
        id: 'anomalies',
        type: 'circle',
        source: 'srcAnoms',
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['get','anomaly_score'], 0, 4, 0.5, 6, 0.85, 8, 1, 10],
          'circle-color': ['interpolate', ['linear'], ['get','anomaly_score'], 0, '#7dd3fc', 0.4, '#fbbf24', 0.6, '#fb923c', 0.85, '#ef4444'],
          'circle-opacity': 0.8,
          'circle-stroke-width': 1,
          'circle-stroke-color': '#333'
        }
      });

      // Hover tooltip for anomalies
      const hoverPopup = new Popup({ closeButton: false, closeOnClick: false, offset: 12 });
      map.on('mousemove', 'anomalies', (e) => {
        const f = (e.features && e.features[0]) as any;
        if (!f) return;
        const p = f.properties || {};
        const name = p.stop_name || p.stop_id;
        const score = Number(p.anomaly_score ?? 0).toFixed(2);
        hoverPopup.setLngLat((e.lngLat as any)).setHTML(`<div style="font-size:12px">${name} — score: ${score}</div>`).addTo(map);
      });
      map.on('mouseleave', 'anomalies', () => hoverPopup.remove());

      // Click popup for anomalies
      map.on('click', 'anomalies', (e) => {
        const f = (e.features && e.features[0]) as any;
        if (!f) return;
        const g = f.geometry && f.geometry.coordinates;
        const p = f.properties || {};
        const obsEpoch = (p.observed_ts_epoch_ms as number | undefined) ?? undefined;
        const evtEpoch = (p.event_ts_epoch_ms as number | undefined) ?? undefined;
        const timeRow = obsEpoch !== undefined && obsEpoch !== null
          ? `Observed: ${formatNYFromEpoch(obsEpoch)} • ${fromNowEpoch(obsEpoch)}`
          : '';
        const color = scoreToColor(Number(p.anomaly_score ?? 0));
        const html = `
          <div style="min-width:220px">
            <div style="font-weight:600">${p.stop_name || p.stop_id}</div>
            <div style="font-size:12px;color:#444">Route: ${p.route_id || '-'}</div>
            <div style="font-size:12px;margin-top:4px">Score: <span style="background:${color};padding:2px 6px;border-radius:10px">${Number(p.anomaly_score ?? 0).toFixed(2)}</span></div>
            <div style="font-size:12px">Residual: ${(Number(p.residual ?? 0)).toFixed(0)}</div>
            ${timeRow ? `<div style="font-size:12px;color:#555;margin-top:4px">${timeRow}</div>` : ''}
            ${evtEpoch ? `<div style="font-size:12px;color:#777;margin-top:2px">ETA: ${formatNYFromEpoch(evtEpoch)} (NYC)</div>` : ''}
            <div style="display:flex;gap:6px;margin-top:8px">
              <button id="btn-center-here" style="font-size:12px;padding:4px 6px;border:1px solid #ddd;border-radius:6px">Center here</button>
              <button id="btn-show-table" style="font-size:12px;padding:4px 6px;border:1px solid #ddd;border-radius:6px">Show in table</button>
            </div>
          </div>`;
        new Popup({ closeButton: true, offset: 12 })
          .setLngLat(g as any)
          .setHTML(html)
          .addTo(map);
        setTimeout(() => {
          const centerBtn = document.getElementById('btn-center-here');
          const showBtn = document.getElementById('btn-show-table');
          if (centerBtn) centerBtn.onclick = () => map.flyTo({ center: g as any, zoom: map.getZoom() + 1, essential: true });
          if (showBtn) showBtn.onclick = () => window.dispatchEvent(new CustomEvent('focusStopId', { detail: p.stop_id }));
        }, 0);
      });
    });
    mapRef.current = map;

    const onFocus = (ev: any) => {
      const detail = ev.detail;
      if (!detail) return;
      const id = typeof detail === 'string' ? detail : detail.stop_id;
      const s = stops.find((x) => x.stop_id === id);
      if (s && mapRef.current) {
        mapRef.current.flyTo({ center: [s.lon, s.lat], zoom: 12.5 });
      }
    };
    window.addEventListener('focus-stop', onFocus as any); // backwards compat
    window.addEventListener('focusStopId', onFocus as any);
    return () => {
      window.removeEventListener('focus-stop', onFocus as any);
      window.removeEventListener('focusStopId', onFocus as any);
      map.remove();
      mapRef.current = null;
    };
  }, [stops]);

  // Update sources on data change
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const stationFeatures = stops.map((s) => ({ type: 'Feature', geometry: { type: 'Point', coordinates: [s.lon, s.lat] }, properties: { stop_id: s.stop_id, stop_name: s.stop_name } }));
    if (map.getSource('srcStations')) (map.getSource('srcStations') as mapboxgl.GeoJSONSource).setData({ type: 'FeatureCollection', features: stationFeatures } as any);
  }, [stops]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (map.getSource('srcAnoms') && map.isStyleLoaded()) (map.getSource('srcAnoms') as mapboxgl.GeoJSONSource).setData(heatmap as any);
  }, [heatmap]);

  if (!MAPBOX_TOKEN) {
    return (
      <main className="p-6">
        <h2 className="text-xl font-semibold">Map cannot load</h2>
        <p>Missing NEXT_PUBLIC_MAPBOX_TOKEN.</p>
      </main>
    );
  }

  return (
    <div className="h-screen w-full flex">
      <aside className="w-[340px] max-w-full border-r border-gray-200 p-4 flex flex-col gap-4">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-semibold">NYC Subway Anomalies</h1>
          {autoRefresh && <span className="blink rounded-full bg-green-500 text-white px-2 py-0.5 text-xs">LIVE</span>}
        </div>
        <div className="flex items-center gap-3">
          <div className="text-sm text-gray-700">Route</div>
          <Select
            value={routeId}
            onChange={(v) => setRouteId(v)}
            options={[{ label: 'All', value: 'All' }].concat(routes.map((r) => ({ label: r, value: r })))}
          />
          <div className="text-sm text-gray-700">Auto</div>
          <Switch checked={autoRefresh} onChange={setAutoRefresh} />
          <Button onClick={() => location.reload()} className="ml-auto" variant="ghost">Refresh now</Button>
        </div>
        <Kpis summary={summary} />
        <ModelTelemetry telemetry={telemetry} />
        <Legend />
        <AnomalyTable route={routeId} />
        {Array.isArray(heatmap?.features) && heatmap.features.length === 0 && (
          <div className="text-xs text-gray-600 bg-gray-50 border border-gray-200 rounded-lg p-2">No anomalies in the last 60m. Showing stations only.</div>
        )}
      </aside>
      <div ref={mapContainer} className="flex-1" />
    </div>
  );
}
