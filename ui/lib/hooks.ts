import { useEffect, useState } from 'react';
import { withBasePath } from './basePath';

const SNAPSHOT_SUMMARY = {
  window: '15m',
  stations_total: 472,
  trains_active: 291,
  anomalies_count: 14,
  anomalies_high: 4,
  anomaly_rate_perc: 4.81,
  scored_rows: 12840,
  last_updated_epoch_ms: 1772383200000,
};

const SNAPSHOT_HEATMAP = {
  type: 'FeatureCollection',
  features: [
    {
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [-73.9911, 40.7309] },
      properties: {
        stop_id: 'L14S',
        stop_name: '14 St - Union Sq',
        route_id: 'L',
        anomaly_score: 0.91,
        residual: 184.0,
        headway_sec: 512.0,
        predicted_headway_sec: 302.0,
        observed_ts_epoch_ms: 1772383169000,
        event_ts_epoch_ms: 1772383229000,
      },
    },
    {
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [-73.9816, 40.7681] },
      properties: {
        stop_id: 'N57S',
        stop_name: '57 St - 7 Av',
        route_id: 'N',
        anomaly_score: 0.87,
        residual: 151.0,
        headway_sec: 476.0,
        predicted_headway_sec: 319.0,
        observed_ts_epoch_ms: 1772383091000,
        event_ts_epoch_ms: 1772383151000,
      },
    },
    {
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [-74.0048, 40.7128] },
      properties: {
        stop_id: 'A34S',
        stop_name: 'Fulton St',
        route_id: 'A',
        anomaly_score: 0.74,
        residual: 96.0,
        headway_sec: 428.0,
        predicted_headway_sec: 343.0,
        observed_ts_epoch_ms: 1772383040000,
        event_ts_epoch_ms: 1772383100000,
      },
    },
  ],
};

const SNAPSHOT_MODEL_TELEMETRY = {
  status: 'available',
  rows_seen: 187402,
  rows_updated: 12840,
  drift_events: 6,
  mae_ema: 10.7,
  residual_q90: 86.4,
  residual_q99: 174.2,
  last_batch_processed: 256,
  unscored_backlog: 0,
  last_run_utc: '2026-03-01T16:40:00Z',
};

const SNAPSHOT_DL_TELEMETRY = {
  status: 'available',
  model: 'shadow-ae-v4',
  device: 'cpu',
  samples_used: 18000,
  train_epochs: 4,
  loss_last: 0.0413,
  recon_error_p90: 0.1284,
  recon_error_p99: 0.2419,
  shadow_alerts_high: 9,
  corr_with_online_score: 0.71,
  last_run_utc: '2026-03-01T16:38:00Z',
  top_shadow_events: [
    { route_id: 'L', stop_id: 'L14S', stop_name: '14 St - Union Sq', dl_error: 0.2438, online_score: 0.91 },
    { route_id: 'N', stop_id: 'N57S', stop_name: '57 St - 7 Av', dl_error: 0.2191, online_score: 0.87 },
    { route_id: 'A', stop_id: 'A34S', stop_name: 'Fulton St', dl_error: 0.1872, online_score: 0.74 },
  ],
};

export function useRoutes() {
  const [routes, setRoutes] = useState<string[]>([]);
  useEffect(() => {
    const ctrl = new AbortController();
    fetch(withBasePath('/api/routes'), { signal: ctrl.signal })
      .then((r) => r.json())
      .then((d) => setRoutes(d.routes || []))
      .catch(() => {});
    return () => ctrl.abort();
  }, []);
  return routes;
}

export function useSummary(win = '15m', tickMs?: number) {
  const [summary, setSummary] = useState<any>(SNAPSHOT_SUMMARY);
  useEffect(() => {
    let aborted = false;
    const ctrl = new AbortController();
    let interval: any;
    const run = async () => {
      const url = new URL(withBasePath('/api/summary'), window.location.origin);
      url.searchParams.set('window', win);
      try {
        const r = await fetch(url.toString(), { signal: ctrl.signal });
        if (!r.ok) return;
        const d = await r.json();
        if (!aborted) setSummary(d);
      } catch {
        // no-op
      }
    };
    run();
    if (tickMs && tickMs > 0) interval = setInterval(run, tickMs);
    return () => {
      aborted = true;
      ctrl.abort();
      if (interval) clearInterval(interval);
    };
  }, [win, tickMs]);
  return summary;
}

export function useStops() {
  const [stops, setStops] = useState<any[]>([]);
  useEffect(() => {
    const ctrl = new AbortController();
    fetch(withBasePath('/api/stops'), { signal: ctrl.signal })
      .then((r) => r.json())
      .then(setStops)
      .catch(() => {});
    return () => ctrl.abort();
  }, []);
  return stops;
}

export function useHeatmap(route = 'All', win = '60m', tickMs?: number) {
  const [data, setData] = useState<any>(SNAPSHOT_HEATMAP);
  useEffect(() => {
    let aborted = false;
    let interval: any;
    let inFlight = false;
    const run = async () => {
      if (inFlight) return;
      if (typeof document !== 'undefined' && document.hidden) return;
      inFlight = true;
      try {
        const url = new URL(withBasePath('/api/heatmap'), window.location.origin);
        url.searchParams.set('ts', 'now');
        url.searchParams.set('window', win);
        url.searchParams.set('route_id', route || 'All');
        const r = await fetch(url.toString());
        if (!r.ok) return;
        const d = await r.json();
        if (!aborted) setData(d);
      } finally {
        inFlight = false;
      }
    };
    run();
    if (tickMs && tickMs > 0) interval = setInterval(run, tickMs);
    return () => {
      aborted = true;
      if (interval) clearInterval(interval);
    };
  }, [route, win, tickMs]);
  return data;
}

export function useModelTelemetry(tickMs?: number) {
  const [telemetry, setTelemetry] = useState<any>(SNAPSHOT_MODEL_TELEMETRY);
  useEffect(() => {
    let aborted = false;
    let interval: any;
    const run = async () => {
      if (typeof document !== 'undefined' && document.hidden) return;
      try {
        const r = await fetch(withBasePath('/api/model/telemetry'));
        if (!r.ok) return;
        const d = await r.json();
        if (!aborted) setTelemetry(d);
      } catch {
        // no-op
      }
    };
    run();
    if (tickMs && tickMs > 0) interval = setInterval(run, tickMs);
    return () => {
      aborted = true;
      if (interval) clearInterval(interval);
    };
  }, [tickMs]);
  return telemetry;
}

export function useDlShadowTelemetry(tickMs?: number) {
  const [telemetry, setTelemetry] = useState<any>(SNAPSHOT_DL_TELEMETRY);
  useEffect(() => {
    let aborted = false;
    let interval: any;
    const run = async () => {
      if (typeof document !== 'undefined' && document.hidden) return;
      try {
        const r = await fetch(withBasePath('/api/model/telemetry/dl-shadow'));
        if (!r.ok) return;
        const d = await r.json();
        if (!aborted) setTelemetry(d);
      } catch {
        // no-op
      }
    };
    run();
    if (tickMs && tickMs > 0) interval = setInterval(run, tickMs);
    return () => {
      aborted = true;
      if (interval) clearInterval(interval);
    };
  }, [tickMs]);
  return telemetry;
}

function useJsonResource<T = any>(path: string, tickMs?: number) {
  const [payload, setPayload] = useState<T>();

  useEffect(() => {
    let aborted = false;
    let interval: any;
    const run = async () => {
      if (typeof document !== 'undefined' && document.hidden) return;
      try {
        const r = await fetch(withBasePath(path));
        if (!r.ok) return;
        const d = await r.json();
        if (!aborted) setPayload(d);
      } catch {
        // no-op
      }
    };
    run();
    if (tickMs && tickMs > 0) interval = setInterval(run, tickMs);
    return () => {
      aborted = true;
      if (interval) clearInterval(interval);
    };
  }, [path, tickMs]);

  return payload;
}

export function useReplaySummary() {
  return useJsonResource('/api/replay/summary');
}

export function useReplayIncidents() {
  const payload = useJsonResource<{ incidents?: any[] }>('/api/replay/incidents');
  return payload?.incidents || [];
}

export function useReplayTimeline(incidentId?: string) {
  const path = incidentId
    ? `/api/replay/timeline?incident_id=${encodeURIComponent(incidentId)}`
    : '/api/replay/timeline';
  const payload = useJsonResource<{ points?: any[] }>(path);
  return payload?.points || [];
}

export function useReplayIncident(incidentId?: string) {
  const path = incidentId ? `/api/replay/incidents/${encodeURIComponent(incidentId)}` : '';
  const [payload, setPayload] = useState<any>();

  useEffect(() => {
    let aborted = false;
    if (!path) {
      setPayload(undefined);
      return;
    }
    const run = async () => {
      try {
        const r = await fetch(withBasePath(path));
        if (!r.ok) return;
        const d = await r.json();
        if (!aborted) setPayload(d);
      } catch {
        // no-op
      }
    };
    run();
    return () => {
      aborted = true;
    };
  }, [path]);

  return payload;
}
