import { useEffect, useState } from 'react';
import { withBasePath } from './basePath';

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
  const [summary, setSummary] = useState<any>();
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
  const [data, setData] = useState<any>({ type: 'FeatureCollection', features: [] });
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
  const [telemetry, setTelemetry] = useState<any>();
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
  const [telemetry, setTelemetry] = useState<any>();
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
