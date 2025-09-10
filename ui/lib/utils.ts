export function scoreToColor(score: number): string {
  if (score == null || isNaN(score as any)) return '#94a3b8'; // slate-400
  if (score > 0.85) return '#ef4444';   // red-500
  if (score > 0.6)  return '#fb923c';   // orange-400
  if (score > 0.4)  return '#fbbf24';   // amber-400
  return '#7dd3fc';                     // sky-300
}
