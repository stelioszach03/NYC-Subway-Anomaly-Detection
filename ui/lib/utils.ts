export type ScoreBand = {
  id: 'low' | 'watch' | 'elevated' | 'critical';
  min: number;
  max: number;
  color: string;
  label: string;
  tone: string;
};

// Single source of truth for anomaly severity colors and thresholds.
export const SCORE_BANDS: ScoreBand[] = [
  { id: 'low', min: 0.0, max: 0.35, color: '#60a5fa', label: '0.00 - 0.34', tone: 'Low' },
  { id: 'watch', min: 0.35, max: 0.6, color: '#facc15', label: '0.35 - 0.59', tone: 'Watch' },
  { id: 'elevated', min: 0.6, max: 0.85, color: '#fb923c', label: '0.60 - 0.84', tone: 'Elevated' },
  { id: 'critical', min: 0.85, max: 1.01, color: '#ef4444', label: '0.85 - 1.00', tone: 'Critical' },
];

export function clampScore(score: number | null | undefined): number {
  if (score == null || Number.isNaN(score)) return 0;
  if (score < 0) return 0;
  if (score > 1) return 1;
  return Number(score);
}

export function scoreBand(score: number | null | undefined): ScoreBand {
  const s = clampScore(score);
  for (const b of SCORE_BANDS) {
    if (s >= b.min && s < b.max) return b;
  }
  return SCORE_BANDS[SCORE_BANDS.length - 1];
}

export function scoreToColor(score: number): string {
  return scoreBand(score).color;
}

export function scoreToTone(score: number): string {
  return scoreBand(score).tone;
}

export function scoreToTextColor(score: number): string {
  const b = scoreBand(score);
  return b.id === 'watch' ? '#1f2937' : '#ffffff';
}

// Mapbox `step` expression using the exact same thresholds/colors as badges and legend.
export function mapboxScoreColorExpression(): unknown[] {
  return [
    'step',
    ['to-number', ['get', 'anomaly_score'], 0],
    SCORE_BANDS[0].color,
    SCORE_BANDS[1].min,
    SCORE_BANDS[1].color,
    SCORE_BANDS[2].min,
    SCORE_BANDS[2].color,
    SCORE_BANDS[3].min,
    SCORE_BANDS[3].color,
  ];
}
