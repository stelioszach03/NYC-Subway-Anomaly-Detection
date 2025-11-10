import type { AppProps } from 'next/app';
import 'mapbox-gl/dist/mapbox-gl.css';
import '../styles/globals.css';

export default function App({ Component, pageProps }: AppProps) {
  return <Component {...pageProps} />;
}

