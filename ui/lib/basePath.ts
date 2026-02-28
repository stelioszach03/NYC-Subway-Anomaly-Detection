const rawBasePath = process.env.NEXT_PUBLIC_BASE_PATH || '';
const baseWithLeadingSlash = rawBasePath
  ? (rawBasePath.startsWith('/') ? rawBasePath : `/${rawBasePath}`)
  : '';

export const BASE_PATH = baseWithLeadingSlash === '/'
  ? ''
  : baseWithLeadingSlash.replace(/\/+$/, '');

export function withBasePath(path: string): string {
  if (!path) return BASE_PATH || '/';
  const normalized = path.startsWith('/') ? path : `/${path}`;
  if (!BASE_PATH) return normalized;
  if (normalized === BASE_PATH || normalized.startsWith(`${BASE_PATH}/`)) {
    return normalized;
  }
  return `${BASE_PATH}${normalized}`;
}
