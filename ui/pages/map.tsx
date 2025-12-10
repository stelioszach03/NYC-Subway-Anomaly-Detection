import { useEffect, useMemo, useRef, useState } from 'react';
import mapboxgl, { LngLatLike, Map, Popup } from 'mapbox-gl';
import { clsx } from 'clsx';

import { AnomalyTable } from '../components/AnomalyTable';
import { DlShadowTelemetry } from '../components/DlShadowTelemetry';
import { Legend } from '../components/Legend';
import { ModelTelemetry } from '../components/ModelTelemetry';
import { Button } from '../components/ui/Button';
import { Select } from '../components/ui/Select';
import { Switch } from '../components/ui/Switch';
import {
  useDlShadowTelemetry,
  useHeatmap,
  useModelTelemetry,
  useRoutes,
  useStops,
  useSummary,
} from '../lib/hooks';
import { formatNYFromEpoch, fromNowEpoch } from '../lib/time';
import { SCORE_BANDS, mapboxScoreColorExpression, scoreBand, scoreToColor, scoreToTextColor } from '../lib/utils';

const MAPBOX_TOKEN = process.env.NEXT_PUBLIC_MAPBOX_TOKEN as string | undefined;
const NYC_CENTER: LngLatLike = [-73.9851, 40.7589];

const FALLBACK_STYLE: any = {
  version: 8,
  sources: {
    carto_light: {
      type: 'raster',
      tiles: ['https://basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png'],
      tileSize: 256,
      attribution: 'OpenStreetMap contributors, CARTO',
    },
  },
  layers: [
    {
      id: 'carto_light',
      type: 'raster',
      source: 'carto_light',
      minzoom: 0,
      maxzoom: 20,
    },
  ],
};

function percentile(values: number[], ratio: number): number {
  if (values.length === 0) return 0.0;
  const idx = Math.min(values.length - 1, Math.max(0, Math.round((values.length - 1) * ratio)));
  return values[idx];
}

export default function MapPage() {
  const mapRef = useRef<Map | null>(null);
  const mapContainer = useRef<HTMLDivElement | null>(null);
  const stopsRef = useRef<any[]>([]);
  const headerRef = useRef<HTMLElement | null>(null);

  const [routeId, setRouteId] = useState<string>('All');
  const [autoRefresh, setAutoRefresh] = useState<boolean>(true);
  const [panelOpen, setPanelOpen] = useState<boolean>(true);
  const [drawerOpen, setDrawerOpen] = useState<boolean>(true);
  const [drawerTall, setDrawerTall] = useState<boolean>(false);
  const [compactViewport, setCompactViewport] = useState<boolean>(false);
  const [headerHeight, setHeaderHeight] = useState<number>(120);

  const routes = useRoutes();
  const summary = useSummary('15m', autoRefresh ? 10000 : undefined);
  const stops = useStops();
  const heatmap = useHeatmap(routeId, '15m', autoRefresh ? 10000 : undefined);
  const telemetry = useModelTelemetry(autoRefresh ? 15000 : undefined);
  const dlTelemetry = useDlShadowTelemetry(autoRefresh ? 30000 : undefined);

  const sideRailWidth = panelOpen && !compactViewport ? 372 : 0;
  const drawerHeight = drawerOpen ? (drawerTall ? (compactViewport ? 400 : 470) : (compactViewport ? 260 : 330)) : 56;

  const scoreOverview = useMemo(() => {
    const features = Array.isArray(heatmap?.features) ? heatmap.features : [];
    const counts = { low: 0, watch: 0, elevated: 0, critical: 0 };
    const routeCounts = new globalThis.Map<string, number>();
    const scores: number[] = [];
    let exactOne = 0;

    for (const feature of features) {
      const props = feature?.properties || {};
      const score = Number(props.anomaly_score ?? 0);
      const route = String(props.route_id || 'Unknown');
      const band = scoreBand(score);
      counts[band.id] += 1;
      routeCounts.set(route, (routeCounts.get(route) || 0) + 1);
      scores.push(score);
      if (score >= 0.9995) exactOne += 1;
    }

    scores.sort((a, b) => a - b);

    return {
      total: features.length,
      exactOne,
      counts,
      p50: percentile(scores, 0.5),
      p90: percentile(scores, 0.9),
      topRoutes: Array.from(routeCounts.entries())
        .sort((a, b) => b[1] - a[1])
        .slice(0, 5),
    };
  }, [heatmap]);

  const headerRight = compactViewport || !panelOpen ? 12 : sideRailWidth + 24;
  const drawerRight = compactViewport || !panelOpen ? 12 : sideRailWidth + 24;

  useEffect(() => {
    stopsRef.current = stops;
  }, [stops]);

  useEffect(() => {
    const onResize = () => {
      const compact = window.innerWidth < 1280;
      setCompactViewport(compact);
      if (compact) {
        setPanelOpen(false);
        setDrawerOpen(false);
        setDrawerTall(false);
      }
    };
    onResize();
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  useEffect(() => {
    const updateHeaderHeight = () => {
      if (!headerRef.current) return;
      setHeaderHeight(Math.ceil(headerRef.current.getBoundingClientRect().height));
    };

    updateHeaderHeight();
    window.addEventListener('resize', updateHeaderHeight);

    let ro: ResizeObserver | null = null;
    if (typeof ResizeObserver !== 'undefined' && headerRef.current) {
      ro = new ResizeObserver(() => updateHeaderHeight());
      ro.observe(headerRef.current);
    }

    return () => {
      window.removeEventListener('resize', updateHeaderHeight);
      if (ro) ro.disconnect();
    };
  }, []);

  useEffect(() => {
    if (MAPBOX_TOKEN) {
      mapboxgl.accessToken = MAPBOX_TOKEN;
    }
    if (mapRef.current || !mapContainer.current) return;

    let fallbackApplied = !MAPBOX_TOKEN;
    let popupHandlersAttached = false;
    const initialStyle: any = MAPBOX_TOKEN ? 'mapbox://styles/mapbox/light-v11' : FALLBACK_STYLE;

    const map = new mapboxgl.Map({
      container: mapContainer.current,
      style: initialStyle,
      center: NYC_CENTER,
      zoom: 10.5,
      attributionControl: true,
    });

    map.addControl(new mapboxgl.NavigationControl({ showCompass: false }));

    const ensureDataLayers = () => {
      if (!map.getSource('srcStations')) {
        map.addSource('srcStations', {
          type: 'geojson',
          data: { type: 'FeatureCollection', features: [] },
          cluster: true,
          clusterRadius: 28,
        } as any);
      }

      if (!map.getLayer('stations')) {
        map.addLayer({
          id: 'stations',
          type: 'circle',
          source: 'srcStations',
          paint: {
            'circle-radius': 3,
            'circle-opacity': 0.55,
            'circle-color': '#64748b',
          },
        });
      }

      if (!map.getSource('srcAnoms')) {
        map.addSource('srcAnoms', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } as any });
      }

      if (!map.getLayer('anomalies')) {
        map.addLayer({
          id: 'anomalies',
          type: 'circle',
          source: 'srcAnoms',
          paint: {
            'circle-radius': ['interpolate', ['linear'], ['to-number', ['get', 'anomaly_score'], 0], 0, 4, 0.6, 7.4, 0.85, 10, 1, 12],
            'circle-color': mapboxScoreColorExpression() as any,
            'circle-opacity': 0.92,
            'circle-stroke-width': 1,
            'circle-stroke-color': '#1f2937',
          },
        });
      }
    };

    const attachPopupHandlers = () => {
      if (popupHandlersAttached) return;
      popupHandlersAttached = true;

      const hoverPopup = new Popup({ closeButton: false, closeOnClick: false, offset: 12 });
      map.on('mousemove', 'anomalies', (e) => {
        const f = (e.features && e.features[0]) as any;
        if (!f) return;
        const p = f.properties || {};
        const score = Number(p.anomaly_score ?? 0);
        const band = scoreBand(score);
        hoverPopup
          .setLngLat(e.lngLat)
          .setHTML(`<div style="font-size:12px"><strong>${p.stop_name || p.stop_id}</strong> · ${score.toFixed(2)} (${band.tone})</div>`)
          .addTo(map);
      });
      map.on('mouseleave', 'anomalies', () => hoverPopup.remove());

      map.on('click', 'anomalies', (e) => {
        const f = (e.features && e.features[0]) as any;
        if (!f) return;
        const g = f.geometry && f.geometry.coordinates;
        const p = f.properties || {};
        const score = Number(p.anomaly_score ?? 0);
        const band = scoreBand(score);
        const obsEpoch = (p.observed_ts_epoch_ms as number | undefined) ?? undefined;
        const evtEpoch = (p.event_ts_epoch_ms as number | undefined) ?? undefined;
        const timeRow = obsEpoch !== undefined && obsEpoch !== null
          ? `Observed: ${formatNYFromEpoch(obsEpoch)} • ${fromNowEpoch(obsEpoch)}`
          : '';
        const color = scoreToColor(score);
        const textColor = scoreToTextColor(score);

        const delta = Number(p.headway_sec ?? 0) - Number(p.predicted_headway_sec ?? 0);
        const html = `
          <div style="min-width:255px">
            <div style="font-weight:600">${p.stop_name || p.stop_id}</div>
            <div style="font-size:12px;color:#475569">Route: ${p.route_id || '-'}</div>
            <div style="font-size:12px;margin-top:4px">Score: <span style="background:${color};color:${textColor};padding:2px 7px;border-radius:999px">${score.toFixed(3)} · ${band.tone}</span></div>
            <div style="font-size:12px">Headway: ${Number(p.headway_sec ?? 0).toFixed(0)}s • Pred: ${Number(p.predicted_headway_sec ?? 0).toFixed(0)}s</div>
            <div style="font-size:12px">Gap vs model: ${delta >= 0 ? '+' : ''}${delta.toFixed(0)}s</div>
            <div style="font-size:12px">Residual: ${Number(p.residual ?? 0).toFixed(0)}</div>
            ${timeRow ? `<div style="font-size:12px;color:#64748b;margin-top:4px">${timeRow}</div>` : ''}
            ${evtEpoch ? `<div style="font-size:12px;color:#94a3b8;margin-top:2px">ETA: ${formatNYFromEpoch(evtEpoch)} (NYC)</div>` : ''}
            <div style="display:flex;gap:6px;margin-top:8px">
              <button id="btn-center-here" style="font-size:12px;padding:4px 6px;border:1px solid #cbd5e1;border-radius:6px">Center here</button>
              <button id="btn-show-table" style="font-size:12px;padding:4px 6px;border:1px solid #cbd5e1;border-radius:6px">Focus table</button>
            </div>
          </div>`;

        new Popup({ closeButton: true, offset: 12 }).setLngLat(g as any).setHTML(html).addTo(map);

        setTimeout(() => {
          const centerBtn = document.getElementById('btn-center-here');
          const showBtn = document.getElementById('btn-show-table');
          if (centerBtn) centerBtn.onclick = () => map.flyTo({ center: g as any, zoom: map.getZoom() + 1, essential: true });
          if (showBtn) showBtn.onclick = () => window.dispatchEvent(new CustomEvent('focusStopId', { detail: p.stop_id }));
        }, 0);
      });
    };

    map.on('load', () => {
      ensureDataLayers();
      attachPopupHandlers();
    });

    map.on('style.load', ensureDataLayers);

    map.on('error', (ev: any) => {
      if (fallbackApplied) return;
      const msg = String(ev?.error?.message || '');
      if (/(401|403|unauthorized|forbidden|access token|style)/i.test(msg)) {
        fallbackApplied = true;
        map.setStyle(FALLBACK_STYLE);
      }
    });

    mapRef.current = map;

    const onFocus = (ev: Event) => {
      const detail = (ev as CustomEvent).detail as string | { stop_id?: string } | undefined;
      if (!detail) return;
      const id = typeof detail === 'string' ? detail : detail.stop_id;
      if (!id) return;
      const stop = stopsRef.current.find((x) => x.stop_id === id);
      if (!stop || !mapRef.current) return;
      mapRef.current.flyTo({ center: [stop.lon, stop.lat], zoom: 12.6, essential: true });
    };

    window.addEventListener('focus-stop', onFocus as EventListener);
    window.addEventListener('focusStopId', onFocus as EventListener);

    return () => {
      window.removeEventListener('focus-stop', onFocus as EventListener);
      window.removeEventListener('focusStopId', onFocus as EventListener);
      map.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.getSource('srcStations')) return;
    const stationFeatures = stops.map((s) => ({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [s.lon, s.lat] },
      properties: { stop_id: s.stop_id, stop_name: s.stop_name },
    }));

    (map.getSource('srcStations') as mapboxgl.GeoJSONSource).setData({
      type: 'FeatureCollection',
      features: stationFeatures,
    } as any);
  }, [stops]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.getSource('srcAnoms') || !map.isStyleLoaded()) return;
    (map.getSource('srcAnoms') as mapboxgl.GeoJSONSource).setData(heatmap as any);
  }, [heatmap]);

  const noAnomalyFeatures = Array.isArray(heatmap?.features) && heatmap.features.length === 0;

  return (
    <div className="relative h-screen w-full overflow-hidden">
      <div
        ref={mapContainer}
        className="absolute inset-0"
        style={{ position: 'absolute', inset: 0, width: '100%', height: '100%' }}
      />

      <div className="pointer-events-none absolute inset-0">
        <header
          ref={headerRef}
          className="panel-glass pointer-events-auto absolute left-3 top-3 rounded-2xl px-4 py-3"
          style={{ right: `${headerRight}px` }}
        >
          <div className="flex flex-wrap items-center gap-3 text-slate-800">
            <div className="min-w-[220px]">
              <div className="flex items-center gap-2">
                <div className="text-sm font-semibold tracking-wide sm:text-base">NYC Subway Anomaly Command Center</div>
                {autoRefresh && <span className="live-dot inline-block h-2 w-2 rounded-full bg-emerald-500" />}
              </div>
              <div className="mt-1 text-xs text-slate-500">
                Live transit anomaly triage across routes, stations, and model residuals.
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs text-slate-600">Route</span>
              <Select
                value={routeId}
                onChange={(v) => setRouteId(v)}
                options={[{ label: 'All', value: 'All' }].concat(routes.map((r) => ({ label: r, value: r })))}
              />

              <span className="ml-1 text-xs text-slate-600">Auto</span>
              <Switch checked={autoRefresh} onChange={setAutoRefresh} />
            </div>

            <div className="ml-auto flex flex-wrap items-center gap-2">
              {!MAPBOX_TOKEN && (
                <div className="rounded-md border border-amber-300 bg-amber-50 px-2 py-0.5 text-[11px] text-amber-700">
                  Fallback basemap
                </div>
              )}
              <Button onClick={() => window.location.reload()} variant="ghost" className="text-xs">
                Refresh
              </Button>
              <Button onClick={() => setPanelOpen((x) => !x)} variant="ghost" className="text-xs">
                {panelOpen ? 'Hide Rail' : 'Show Rail'}
              </Button>
            </div>
          </div>

          <div className="mt-3 flex flex-wrap gap-2 text-[11px]">
            <span className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-slate-600">
              Stations <span className="font-semibold text-slate-900">{summary?.stations_total ?? 0}</span>
            </span>
            <span className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-slate-600">
              Active <span className="font-semibold text-slate-900">{summary?.trains_active ?? 0}</span>
            </span>
            <span className="rounded-full border border-amber-200 bg-amber-50 px-2.5 py-1 text-amber-700">
              Critical window <span className="font-semibold">{scoreOverview.counts.critical}</span>
            </span>
            <span className="rounded-full border border-rose-200 bg-rose-50 px-2.5 py-1 text-rose-700">
              Exact 1.000 <span className="font-semibold">{scoreOverview.exactOne}</span>
            </span>
            <span className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-slate-600">
              P90 <span className="font-semibold text-slate-900">{scoreOverview.p90.toFixed(3)}</span>
            </span>
            <a className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-slate-600 no-underline transition hover:border-slate-300 hover:text-slate-900" href="/nyc-subway-anomaly/api/summary?window=15m" target="_blank" rel="noopener noreferrer">summary</a>
            <a className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-slate-600 no-underline transition hover:border-slate-300 hover:text-slate-900" href="/nyc-subway-anomaly/api/model/telemetry" target="_blank" rel="noopener noreferrer">model</a>
            <a className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-slate-600 no-underline transition hover:border-slate-300 hover:text-slate-900" href="/nyc-subway-anomaly/api/heatmap?ts=now&window=15m&route_id=All" target="_blank" rel="noopener noreferrer">heatmap</a>
          </div>
        </header>

        <aside
          className={clsx(
            'panel-glass pointer-events-auto absolute right-3 z-20 w-[min(92vw,360px)] overflow-hidden rounded-2xl transition duration-200',
            panelOpen ? 'translate-x-0 opacity-100' : 'translate-x-[110%] opacity-0',
          )}
          style={{ top: Math.max(86, headerHeight + 18), bottom: 12 }}
        >
          <div className="h-full overflow-auto p-3">
            <div className="space-y-3">
              <div className="rounded-xl border border-slate-200 bg-white p-3 text-xs text-slate-600 shadow-sm">
                <div className="mb-2 flex items-center justify-between">
                  <div className="text-[11px] uppercase tracking-[0.14em] text-slate-500">Live window</div>
                  <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-500">15m</span>
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
                    <div className="text-[11px] text-slate-500">Visible points</div>
                    <div className="mt-1 text-lg font-semibold text-slate-900">{scoreOverview.total}</div>
                  </div>
                  <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
                    <div className="text-[11px] text-slate-500">Median score</div>
                    <div className="mt-1 text-lg font-semibold text-slate-900">{scoreOverview.p50.toFixed(3)}</div>
                  </div>
                </div>
                <div className="mt-3 space-y-2">
                  {SCORE_BANDS.map((band) => {
                    const count = scoreOverview.counts[band.id];
                    const share = scoreOverview.total > 0 ? (count / scoreOverview.total) * 100.0 : 0.0;
                    return (
                      <div key={band.id}>
                        <div className="mb-1 flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: band.color }} />
                            <span className="font-medium text-slate-700">{band.tone}</span>
                          </div>
                          <span className="text-slate-500">{count} · {share.toFixed(1)}%</span>
                        </div>
                        <div className="h-2 overflow-hidden rounded-full bg-slate-100">
                          <div className="h-full rounded-full" style={{ width: `${Math.max(0, Math.min(100, share))}%`, backgroundColor: band.color }} />
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>

              <div className="rounded-xl border border-slate-200 bg-white p-3 text-xs text-slate-600 shadow-sm">
                <div className="text-[11px] uppercase tracking-[0.14em] text-slate-500">Routes under pressure</div>
                <div className="mt-2 flex flex-wrap gap-2">
                  {scoreOverview.topRoutes.map(([route, count]) => (
                    <div key={route} className="rounded-lg border border-slate-200 bg-slate-50 px-2 py-1.5">
                      <div className="text-[11px] text-slate-500">Route</div>
                      <div className="flex items-center gap-2">
                        <span className="inline-flex min-w-7 items-center justify-center rounded-md bg-slate-900 px-1.5 py-0.5 text-[11px] font-semibold text-white">
                          {route}
                        </span>
                        <span className="font-semibold text-slate-900">{count}</span>
                      </div>
                    </div>
                  ))}
                  {scoreOverview.topRoutes.length === 0 ? <div className="text-slate-500">No active route clusters.</div> : null}
                </div>
              </div>

              <ModelTelemetry telemetry={telemetry} />
              <DlShadowTelemetry telemetry={dlTelemetry} />
              <Legend />
            </div>
          </div>
        </aside>

        <section
          className="panel-glass pointer-events-auto absolute bottom-3 left-3 z-30 overflow-hidden rounded-2xl transition-[height] duration-200"
          style={{ height: drawerHeight, right: `${drawerRight}px` }}
        >
          <div className="flex flex-wrap items-center gap-2 border-b border-slate-200 px-3 py-2 text-slate-700">
            <div>
              <div className="text-[11px] uppercase tracking-[0.14em] text-slate-500">Incident console</div>
              <div className="mt-0.5 text-xs text-slate-500">Ranked by model score, then observed time.</div>
            </div>
            <div className="ml-auto flex flex-wrap items-center gap-2 text-[11px]">
              <span className="rounded-full bg-slate-100 px-2 py-0.5 text-slate-600">{scoreOverview.total} visible</span>
              <span className="rounded-full bg-rose-50 px-2 py-0.5 text-rose-700">{scoreOverview.exactOne} exact 1.000</span>
              <span className="rounded-full bg-amber-50 px-2 py-0.5 text-amber-700">p90 {scoreOverview.p90.toFixed(3)}</span>
              <Button onClick={() => setDrawerTall((x) => !x)} variant="ghost" className="text-xs">
                {drawerTall ? 'Compact' : 'Expanded'}
              </Button>
              <Button onClick={() => setDrawerOpen((x) => !x)} variant="ghost" className="text-xs">
                {drawerOpen ? 'Collapse' : 'Open'}
              </Button>
            </div>
          </div>

          {drawerOpen ? (
            <div className="flex h-[calc(100%-45px)] min-h-0 flex-col p-2">
              {noAnomalyFeatures && (
                <div className="mb-2 rounded-lg border border-slate-200 bg-slate-50 p-2 text-xs text-slate-600">
                  No anomalies in the current window. Stream is live and this table updates when high-residual events appear.
                </div>
              )}
              <div className="min-h-0 flex-1">
                <AnomalyTable route={routeId} tickMs={autoRefresh ? 10000 : undefined} />
              </div>
            </div>
          ) : (
            <div className="px-3 py-2 text-xs text-slate-600">
              Drawer collapsed. Click <span className="font-semibold text-slate-800">Open</span> to inspect ranked anomalies.
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
