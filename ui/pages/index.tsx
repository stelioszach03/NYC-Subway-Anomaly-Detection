import Link from 'next/link';

export default function Home() {
  return (
    <main style={{ padding: 24 }}>
      <h1>MTA Subway Anomaly Scan UI</h1>
      <p>
        Go to the{' '}
        <Link href="/map">Map</Link>
      </p>
    </main>
  );
}

