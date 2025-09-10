import { useEffect, useState } from 'react';

export function useRoutes() {
  const [routes, setRoutes] = useState<string[]>([]);
  useEffect(() => {
    const ctrl = new AbortController();
    fetch('/api/routes', { signal: ctrl.signal })
      .then((r) => r.json())
      .then((d) => setRoutes(d.routes || []))
      .catch(() => {});
    return () => ctrl.abort();
  }, []);
  return routes;
}

export function useSummary(win = '15m') {
  const [summary, setSummary] = useState<any>();
  useEffect(() => {
    const ctrl = new AbortController();
    const url = new URL('/api/summary', window.location.origin);
    url.searchParams.set('window', win);
    fetch(url.toString(), { signal: ctrl.signal })
      .then((r) => r.json())
      .then(setSummary)
      .catch(() => {});
    return () => ctrl.abort();
  }, [win]);
  return summary;
}

export function useStops() {
  const [stops, setStops] = useState<any[]>([]);
  useEffect(() => {
    const ctrl = new AbortController();
    fetch('/api/stops', { signal: ctrl.signal })
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
      if (inFlight) return; // debounce: skip if request in flight
      if (typeof document !== 'undefined' && document.hidden) return; // skip in background tab
      inFlight = true;
      try {
        const url = new URL('/api/heatmap', window.location.origin);
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
