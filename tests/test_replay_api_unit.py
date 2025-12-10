from __future__ import annotations

from pathlib import Path

import anyio
import httpx

from evaluation.replay import run_replay_evaluation


SAMPLE_DATASET = Path('evaluation/data/sample_subway_headways.csv')


class _Client:
    def __init__(self, app) -> None:
        self._transport = httpx.ASGITransport(app=app)
        self._client = httpx.AsyncClient(transport=self._transport, base_url='http://test')

    async def _get_async(self, path: str):
        return await self._client.get(path)

    def get(self, path: str):
        return anyio.run(self._get_async, path)

    async def _aclose(self) -> None:
        await self._client.aclose()

    def close(self) -> None:
        anyio.run(self._aclose)


def test_replay_api_serves_generated_artifacts(monkeypatch, tmp_path):
    run_replay_evaluation(SAMPLE_DATASET, tmp_path)
    monkeypatch.setenv('REPLAY_ARTIFACT_DIR', str(tmp_path))

    from api.app.main import app

    client = _Client(app)
    try:
        summary = client.get('/api/replay/summary')
        assert summary.status_code == 200
        assert summary.json()['dataset']['incidents'] == 3

        incidents = client.get('/api/replay/incidents')
        assert incidents.status_code == 200
        incident_list = incidents.json()['incidents']
        assert len(incident_list) == 3

        timeline = client.get('/api/replay/timeline?incident_id=signal-delay-midtown')
        assert timeline.status_code == 200
        assert len(timeline.json()['points']) >= 1

        detail = client.get('/api/replay/incidents/signal-delay-midtown')
        assert detail.status_code == 200
        assert detail.json()['incident_id'] == 'signal-delay-midtown'
        assert detail.json()['peak_score'] >= 0.9
    finally:
        client.close()
