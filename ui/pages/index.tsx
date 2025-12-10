import Link from 'next/link';

export default function Home() {
  return (
    <main className="min-h-screen bg-slate-950 px-6 py-10 text-slate-100">
      <div className="mx-auto max-w-5xl rounded-[30px] border border-cyan-400/20 bg-[radial-gradient(circle_at_top_left,_rgba(34,211,238,0.18),_transparent_36%),linear-gradient(180deg,_rgba(15,23,42,0.96),_rgba(2,6,23,0.98))] p-8 shadow-2xl shadow-cyan-950/30">
        <div className="max-w-3xl">
          <div className="inline-flex rounded-full border border-cyan-400/20 bg-cyan-400/10 px-3 py-1 text-[11px] uppercase tracking-[0.2em] text-cyan-100">
            NYC Subway Anomaly Detection
          </div>
          <h1 className="mt-4 text-4xl font-semibold tracking-tight text-white">Operational anomaly intelligence for GTFS-RT subway operations.</h1>
          <p className="mt-4 text-base leading-7 text-slate-300">
            Explore the live map command center or inspect representative incident replays with baseline comparisons, explanation context, and portfolio-grade evaluation artifacts.
          </p>
        </div>

        <div className="mt-8 flex flex-wrap gap-3">
          <Link href="/map" className="inline-flex items-center justify-center rounded-lg border border-cyan-500 bg-cyan-500 px-3 py-1.5 text-sm font-medium text-slate-950 transition hover:bg-cyan-400">
            Open Live Map
          </Link>
          <Link href="/replay" className="inline-flex items-center justify-center rounded-lg border border-slate-600 bg-slate-900 px-3 py-1.5 text-sm font-medium text-slate-100 transition hover:bg-slate-800">
            Open Replay Command Center
          </Link>
        </div>
      </div>
    </main>
  );
}
