import fs from 'fs';
import path from 'path';

import type { GetStaticProps, InferGetStaticPropsType } from 'next';
import Link from 'next/link';
import { useMemo, useState } from 'react';
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceDot,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import { Card, CardBody, CardTitle } from '../components/ui/Card';
import { scoreBand, scoreToColor, scoreToTextColor } from '../lib/utils';

type ReplayPageProps = {
  initialSummary: any;
  initialIncidents: any[];
  initialTimeline: any[];
  initialIncidentDetails: Record<string, any>;
};

function shortTime(iso?: string) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  }).format(d);
}

function MetricCard({ title, value, sub }: { title: string; value: string; sub?: string }) {
  return (
    <Card>
      <CardBody className="p-4">
        <CardTitle>{title}</CardTitle>
        <div className="mt-2 text-2xl font-semibold text-slate-900">{value}</div>
        {sub ? <div className="mt-1 text-xs text-slate-500">{sub}</div> : null}
      </CardBody>
    </Card>
  );
}

export default function ReplayPage({
  initialSummary,
  initialIncidents,
  initialTimeline,
  initialIncidentDetails,
}: InferGetStaticPropsType<typeof getStaticProps>) {
  const [selectedIncidentId, setSelectedIncidentId] = useState<string | undefined>(initialIncidents[0]?.incident_id);
  const [selectedIndex, setSelectedIndex] = useState(0);

  const incidentDetail = selectedIncidentId ? initialIncidentDetails[selectedIncidentId] : undefined;
  const timeline = selectedIncidentId ? incidentDetail?.points || [] : initialTimeline;

  const chartData = useMemo(
    () =>
      (timeline || []).map((point: any) => ({
        ...point,
        timeLabel: shortTime(point.observed_ts),
      })),
    [timeline],
  );

  const safeIndex = Math.min(selectedIndex, Math.max(chartData.length - 1, 0));
  const currentPoint = chartData[safeIndex];
  const currentTopStop = currentPoint?.top_stops?.[0];
  const currentBand = scoreBand(currentPoint?.model_peak_score || 0);
  const onlineMetrics = initialSummary?.metrics?.online_model || {};
  const zscoreMetrics = initialSummary?.metrics?.zscore_baseline || {};

  return (
    <main className="min-h-screen bg-slate-950 text-slate-100">
      <div className="mx-auto flex max-w-7xl flex-col gap-6 px-4 py-6 sm:px-6 lg:px-8">
        <section className="rounded-[28px] border border-cyan-400/20 bg-[radial-gradient(circle_at_top_left,_rgba(34,211,238,0.18),_transparent_34%),linear-gradient(180deg,_rgba(15,23,42,0.96),_rgba(2,6,23,0.96))] p-6 shadow-2xl shadow-cyan-950/40">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
            <div className="max-w-3xl">
              <div className="mb-3 inline-flex rounded-full border border-cyan-400/25 bg-cyan-400/10 px-3 py-1 text-[11px] uppercase tracking-[0.2em] text-cyan-100">
                Historical Replay Command Center
              </div>
              <h1 className="text-3xl font-semibold tracking-tight text-white sm:text-4xl">Replay how the anomaly stack behaves before an operator ever clicks refresh.</h1>
              <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-300 sm:text-base">
                This view replays representative subway incidents in timestamp order, compares the online model against transparent baselines, and surfaces the route-stop context behind each flag.
              </p>
            </div>

            <div className="flex flex-wrap gap-3">
              <Link href="/map" className="inline-flex items-center justify-center rounded-lg border border-slate-600 bg-slate-900 px-3 py-1.5 text-sm font-medium text-slate-100 transition hover:bg-slate-800">
                Open Live Map
              </Link>
              <Link href="/" className="inline-flex items-center justify-center rounded-lg border border-cyan-500 bg-cyan-500 px-3 py-1.5 text-sm font-medium text-slate-950 transition hover:bg-cyan-400">
                Project Home
              </Link>
            </div>
          </div>
        </section>

        <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <MetricCard
            title="Replay Rows"
            value={String(initialSummary?.dataset?.rows || 0)}
            sub={`${initialSummary?.dataset?.routes || 0} routes · ${initialSummary?.dataset?.stops || 0} stops`}
          />
          <MetricCard
            title="Incidents"
            value={String(initialSummary?.dataset?.incidents || 0)}
            sub="Representative labeled scenarios for portfolio evaluation"
          />
          <MetricCard
            title="Online Precision@10"
            value={`${(((onlineMetrics?.precision_at_k || {})['p@10'] || 0) * 100).toFixed(0)}%`}
            sub={`Z-score baseline: ${((((zscoreMetrics?.precision_at_k || {})['p@10'] || 0) as number) * 100).toFixed(0)}%`}
          />
          <MetricCard
            title="Incident Detection"
            value={`${(((onlineMetrics?.incident_detection_rate || 0) as number) * 100).toFixed(0)}%`}
            sub={`Avg time-to-detect: ${Number(onlineMetrics?.average_time_to_detect_min || 0).toFixed(1)} min`}
          />
        </section>

        <section className="grid gap-5 xl:grid-cols-[1.7fr_1fr]">
          <Card className="border-slate-800 bg-slate-900/90 text-slate-100 shadow-xl shadow-slate-950/30">
            <CardBody className="space-y-5 p-5">
              <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                <div>
                  <CardTitle className="text-cyan-300">Replay Timeline</CardTitle>
                  <div className="mt-1 text-lg font-semibold text-white">
                    {selectedIncidentId ? incidentDetail?.incident_title || selectedIncidentId : 'All replay points'}
                  </div>
                </div>
                <div className="rounded-full border border-slate-700 bg-slate-950/70 px-3 py-1 text-xs text-slate-300">
                  {chartData.length} snapshots
                </div>
              </div>

              <div className="h-[300px] w-full">
                <ResponsiveContainer>
                  <LineChart data={chartData} margin={{ top: 10, right: 14, left: -20, bottom: 0 }}>
                    <CartesianGrid stroke="#1e293b" strokeDasharray="4 4" />
                    <XAxis dataKey="timeLabel" tick={{ fill: '#94a3b8', fontSize: 11 }} minTickGap={22} />
                    <YAxis domain={[0, 1]} tick={{ fill: '#94a3b8', fontSize: 11 }} />
                    <Tooltip
                      contentStyle={{ background: '#020617', borderColor: '#334155', borderRadius: 14 }}
                      labelStyle={{ color: '#e2e8f0' }}
                    />
                    <Line type="monotone" dataKey="model_peak_score" name="Online model" stroke="#22d3ee" strokeWidth={2.8} dot={false} />
                    <Line type="monotone" dataKey="baseline_zscore_peak" name="Z-score" stroke="#fb7185" strokeWidth={1.9} dot={false} strokeDasharray="4 4" />
                    <Line type="monotone" dataKey="baseline_ewma_peak" name="EWMA" stroke="#60a5fa" strokeWidth={1.9} dot={false} strokeDasharray="4 4" />
                    <Line type="monotone" dataKey="baseline_threshold_peak" name="Threshold" stroke="#c084fc" strokeWidth={1.9} dot={false} strokeDasharray="4 4" />
                    {currentPoint ? (
                      <ReferenceDot
                        x={currentPoint.timeLabel}
                        y={currentPoint.model_peak_score}
                        r={5}
                        fill="#ffffff"
                        stroke="#22d3ee"
                        strokeWidth={2}
                      />
                    ) : null}
                  </LineChart>
                </ResponsiveContainer>
              </div>

              <div>
                <div className="mb-2 flex items-center justify-between text-xs text-slate-400">
                  <span>Time scrubber</span>
                  <span>{currentPoint ? shortTime(currentPoint.observed_ts) : 'No replay data'}</span>
                </div>
                <input
                  type="range"
                  min={0}
                  max={Math.max(chartData.length - 1, 0)}
                  step={1}
                  value={safeIndex}
                  onChange={(e) => setSelectedIndex(Number(e.target.value))}
                  className="w-full accent-cyan-400"
                />
              </div>

              <div className="grid gap-4 lg:grid-cols-[1.2fr_0.8fr]">
                <div className="rounded-2xl border border-slate-800 bg-slate-950/70 p-4">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <div className="text-sm font-semibold text-white">Current operator snapshot</div>
                      <div className="text-xs text-slate-400">Top-scoring route-stop pair at the selected replay timestamp</div>
                    </div>
                    <span
                      className="rounded-full px-3 py-1 text-xs font-semibold"
                      style={{ background: scoreToColor(currentPoint?.model_peak_score || 0), color: scoreToTextColor(currentPoint?.model_peak_score || 0) }}
                    >
                      {(currentPoint?.model_peak_score || 0).toFixed(2)} · {currentBand.tone}
                    </span>
                  </div>

                  <div className="mt-4 grid gap-3 sm:grid-cols-3">
                    <div className="rounded-xl border border-slate-800 bg-slate-900/90 p-3">
                      <div className="text-[11px] uppercase tracking-[0.14em] text-slate-500">Route</div>
                      <div className="mt-2 text-xl font-semibold text-white">{currentTopStop?.route_id || '—'}</div>
                    </div>
                    <div className="rounded-xl border border-slate-800 bg-slate-900/90 p-3">
                      <div className="text-[11px] uppercase tracking-[0.14em] text-slate-500">Observed Headway</div>
                      <div className="mt-2 text-xl font-semibold text-white">{Number(currentTopStop?.headway_sec || 0).toFixed(0)}s</div>
                    </div>
                    <div className="rounded-xl border border-slate-800 bg-slate-900/90 p-3">
                      <div className="text-[11px] uppercase tracking-[0.14em] text-slate-500">Expected Headway</div>
                      <div className="mt-2 text-xl font-semibold text-white">{Number(currentTopStop?.predicted_headway_sec || 0).toFixed(0)}s</div>
                    </div>
                  </div>

                  <div className="mt-4 rounded-xl border border-cyan-500/20 bg-cyan-500/5 p-3 text-sm text-slate-200">
                    <div className="font-medium text-cyan-100">Why flagged?</div>
                    <div className="mt-2 flex flex-wrap gap-2">
                      {(currentTopStop?.reasons || []).length > 0 ? (
                        currentTopStop.reasons.map((reason: string) => (
                          <span key={reason} className="rounded-full border border-cyan-400/20 bg-cyan-400/10 px-3 py-1 text-xs text-cyan-50">
                            {reason}
                          </span>
                        ))
                      ) : (
                        <span className="text-xs text-slate-400">No contributing factors captured for this point.</span>
                      )}
                    </div>
                  </div>
                </div>

                <div className="rounded-2xl border border-slate-800 bg-slate-950/70 p-4">
                  <div className="text-sm font-semibold text-white">Model vs baselines</div>
                  <div className="mt-3 space-y-3">
                    {[
                      { label: 'Online model', value: currentPoint?.model_peak_score || 0, color: '#22d3ee' },
                      { label: 'Z-score', value: currentPoint?.baseline_zscore_peak || 0, color: '#fb7185' },
                      { label: 'EWMA', value: currentPoint?.baseline_ewma_peak || 0, color: '#60a5fa' },
                      { label: 'Threshold', value: currentPoint?.baseline_threshold_peak || 0, color: '#c084fc' },
                    ].map((row) => (
                      <div key={row.label}>
                        <div className="mb-1 flex items-center justify-between text-xs text-slate-300">
                          <span>{row.label}</span>
                          <span>{Number(row.value).toFixed(2)}</span>
                        </div>
                        <div className="h-2 rounded-full bg-slate-800">
                          <div className="h-2 rounded-full" style={{ width: `${Math.max(4, Number(row.value) * 100)}%`, background: row.color }} />
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              <div className="rounded-2xl border border-slate-800 bg-slate-950/70 p-4">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <div className="text-sm font-semibold text-white">Top affected stops</div>
                    <div className="text-xs text-slate-400">A lightweight corridor view for the currently selected replay step</div>
                  </div>
                </div>

                <div className="mt-4 flex flex-wrap gap-3">
                  {(currentPoint?.top_stops || []).map((stop: any) => (
                    <div key={`${stop.route_id}-${stop.stop_id}`} className="min-w-[180px] rounded-xl border border-slate-800 bg-slate-900/90 p-3">
                      <div className="text-[11px] uppercase tracking-[0.14em] text-slate-500">{stop.route_id}</div>
                      <div className="mt-1 text-sm font-semibold text-white">{stop.stop_name}</div>
                      <div className="mt-2 text-xs text-slate-400">{Number(stop.headway_sec).toFixed(0)}s observed · {Number(stop.predicted_headway_sec).toFixed(0)}s expected</div>
                    </div>
                  ))}
                </div>
              </div>
            </CardBody>
          </Card>

          <div className="space-y-5">
            <Card className="border-slate-800 bg-slate-900/90 text-slate-100 shadow-xl shadow-slate-950/30">
              <CardBody className="p-5">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <CardTitle className="text-cyan-300">Incident Library</CardTitle>
                    <div className="mt-1 text-lg font-semibold text-white">Three replayable case-study scenarios</div>
                  </div>
                </div>
                <div className="mt-4 space-y-3">
                  {initialIncidents.map((incident: any) => {
                    const active = incident.incident_id === selectedIncidentId;
                    return (
                      <button
                        key={incident.incident_id}
                        onClick={() => {
                          setSelectedIncidentId(incident.incident_id);
                          setSelectedIndex(0);
                        }}
                        className={`w-full rounded-2xl border p-4 text-left transition ${active ? 'border-cyan-400/50 bg-cyan-400/10' : 'border-slate-800 bg-slate-950/60 hover:border-slate-700'}`}
                      >
                        <div className="text-sm font-semibold text-white">{incident.incident_title}</div>
                        <div className="mt-1 text-xs text-slate-400">{shortTime(incident.window_start)} → {shortTime(incident.window_end)}</div>
                        <div className="mt-3 flex flex-wrap gap-2">
                          {(incident.affected_routes || []).map((route: string) => (
                            <span key={route} className="rounded-full border border-slate-700 px-2 py-0.5 text-[11px] text-slate-300">{route}</span>
                          ))}
                        </div>
                      </button>
                    );
                  })}
                </div>
              </CardBody>
            </Card>

            <Card className="border-slate-800 bg-slate-900/90 text-slate-100 shadow-xl shadow-slate-950/30">
              <CardBody className="space-y-4 p-5">
                <div>
                  <CardTitle className="text-cyan-300">Incident Summary</CardTitle>
                  <div className="mt-1 text-lg font-semibold text-white">{incidentDetail?.incident_title || 'Select an incident'}</div>
                </div>

                <p className="text-sm leading-6 text-slate-300">{incidentDetail?.what_happened || 'Pick an incident to inspect the replay context and contributing factors.'}</p>

                <div className="grid gap-3 sm:grid-cols-2">
                  <div className="rounded-xl border border-slate-800 bg-slate-950/70 p-3">
                    <div className="text-[11px] uppercase tracking-[0.14em] text-slate-500">Peak score</div>
                    <div className="mt-2 text-xl font-semibold text-white">{Number(incidentDetail?.peak_score || 0).toFixed(2)}</div>
                  </div>
                  <div className="rounded-xl border border-slate-800 bg-slate-950/70 p-3">
                    <div className="text-[11px] uppercase tracking-[0.14em] text-slate-500">Detection delay</div>
                    <div className="mt-2 text-xl font-semibold text-white">{Number(incidentDetail?.detection_delay_min || 0).toFixed(1)} min</div>
                  </div>
                </div>

                <div>
                  <div className="text-[11px] uppercase tracking-[0.14em] text-slate-500">What the model saw</div>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {(incidentDetail?.top_reasons || []).map((reason: string) => (
                      <span key={reason} className="rounded-full border border-cyan-400/20 bg-cyan-400/10 px-3 py-1 text-xs text-cyan-50">{reason}</span>
                    ))}
                  </div>
                </div>

                <div>
                  <div className="text-[11px] uppercase tracking-[0.14em] text-slate-500">Most affected stops</div>
                  <div className="mt-3 space-y-2">
                    {(incidentDetail?.top_stops || []).map((stop: any) => (
                      <div key={`${stop.route_id}-${stop.stop_id}`} className="rounded-xl border border-slate-800 bg-slate-950/70 p-3 text-sm text-slate-200">
                        <div className="font-medium text-white">{stop.route_id} · {stop.stop_name || stop.stop_id}</div>
                        <div className="mt-1 text-xs text-slate-400">Observed {Number(stop.headway_sec || 0).toFixed(0)}s · expected {Number(stop.predicted_headway_sec || 0).toFixed(0)}s</div>
                      </div>
                    ))}
                  </div>
                </div>
              </CardBody>
            </Card>
          </div>
        </section>
      </div>
    </main>
  );
}

function findReplayArtifactDir() {
  const candidates = [
    path.join(process.cwd(), 'docs', 'generated', 'replay'),
    path.join(process.cwd(), '..', 'docs', 'generated', 'replay'),
  ];
  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) return candidate;
  }
  throw new Error('Replay artifact directory not found');
}

export const getStaticProps: GetStaticProps<ReplayPageProps> = async () => {
  const artifactDir = findReplayArtifactDir();
  const readJson = (relativePath: string) => JSON.parse(fs.readFileSync(path.join(artifactDir, relativePath), 'utf-8'));

  const summary = readJson('summary.json');
  const incidentsPayload = readJson('incidents.json');
  const timelinePayload = readJson('timeline.json');
  const incidentDetails: Record<string, any> = {};

  for (const incident of incidentsPayload.incidents || []) {
    if (!incident?.incident_id || !incident?.detail_path) continue;
    incidentDetails[incident.incident_id] = readJson(incident.detail_path);
  }

  return {
    props: {
      initialSummary: summary,
      initialIncidents: incidentsPayload.incidents || [],
      initialTimeline: timelinePayload.points || [],
      initialIncidentDetails: incidentDetails,
    },
  };
};
