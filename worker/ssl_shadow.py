"""PyTorch self-supervised shadow model for subway anomaly intelligence.

The module runs in shadow mode and does not modify production anomaly scores.
It trains a denoising autoencoder over recent scored rows and publishes
telemetry JSON for dashboard observability.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from api.app.core.logging import get_logger
from api.app.models import Score
from api.app.storage.session import get_engine


log = get_logger(__name__)
DEFAULT_MODELS_DIR = "/data/gtfs/models"
DEFAULT_TELEMETRY_FILENAME = "dl_shadow_telemetry.json"
DEFAULT_MODEL_FILENAME = "dl_shadow_autoencoder.pt"


@dataclass
class DlShadowTelemetry:
    status: str = "unavailable"
    model: str = "denoising_autoencoder_v1"
    device: str = "cpu"
    samples_used: int = 0
    train_epochs: int = 0
    loss_last: float = 0.0
    recon_error_p90: float = 0.0
    recon_error_p99: float = 0.0
    recon_error_max: float = 0.0
    shadow_alerts_high: int = 0
    corr_with_online_score: float = 0.0
    top_shadow_events: list[dict] | None = None
    last_run_utc: str | None = None
    note: str | None = None


class DenoisingAutoEncoder(nn.Module):
    def __init__(self, input_dim: int) -> None:
        super().__init__()
        hidden = max(24, input_dim * 4)
        latent = max(8, input_dim * 2)
        self.encoder = nn.Sequential(
            nn.Linear(input_dim, hidden),
            nn.ReLU(),
            nn.Linear(hidden, latent),
            nn.ReLU(),
        )
        self.decoder = nn.Sequential(
            nn.Linear(latent, hidden),
            nn.ReLU(),
            nn.Linear(hidden, input_dim),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        z = self.encoder(x)
        return self.decoder(z)


def _stable_hash_unit(value: str, mod: int) -> float:
    if not value:
        return 0.0
    digest = hashlib.md5(value.encode("utf-8")).hexdigest()
    return float(int(digest[:8], 16) % mod) / float(mod)


def _write_json(path: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=True, indent=2)


def _fetch_recent_rows(window_minutes: int, limit: int) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=max(5, window_minutes))
    engine = get_engine()
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    with SessionLocal() as session:
        stmt = (
            select(
                Score.observed_ts,
                Score.route_id,
                Score.stop_id,
                Score.headway_sec,
                Score.predicted_headway_sec,
                Score.residual,
                Score.anomaly_score,
            )
            .where(Score.observed_ts >= cutoff)
            .where(Score.headway_sec.is_not(None))
            .where(Score.predicted_headway_sec.is_not(None))
            .order_by(Score.observed_ts.desc())
            .limit(max(256, int(limit)))
        )
        rows = session.execute(stmt).all()

    data: list[dict] = []
    for observed_ts, route_id, stop_id, headway, predicted, residual, anomaly in rows:
        if headway is None or predicted is None:
            continue
        ts = observed_ts
        if ts is None:
            continue
        hour_utc = int(ts.astimezone(timezone.utc).hour)
        minute_utc = int(ts.astimezone(timezone.utc).minute)
        data.append(
            {
                "observed_ts": ts,
                "route_id": str(route_id or ""),
                "stop_id": str(stop_id or ""),
                "headway_sec": float(headway),
                "predicted_headway_sec": float(predicted),
                "residual": float(residual or 0.0),
                "online_score": float(anomaly or 0.0),
                "hour_sin": float(np.sin(2.0 * np.pi * hour_utc / 24.0)),
                "hour_cos": float(np.cos(2.0 * np.pi * hour_utc / 24.0)),
                "minute_sin": float(np.sin(2.0 * np.pi * minute_utc / 60.0)),
                "minute_cos": float(np.cos(2.0 * np.pi * minute_utc / 60.0)),
                "route_hash": _stable_hash_unit(str(route_id or ""), mod=997),
                "stop_hash": _stable_hash_unit(str(stop_id or ""), mod=4093),
            }
        )

    data.reverse()
    return data


def _build_feature_matrix(rows: list[dict]) -> tuple[np.ndarray, list[str]]:
    feature_names = [
        "headway_sec",
        "predicted_headway_sec",
        "residual",
        "online_score",
        "hour_sin",
        "hour_cos",
        "minute_sin",
        "minute_cos",
        "route_hash",
        "stop_hash",
    ]
    if not rows:
        return np.zeros((0, len(feature_names)), dtype=np.float32), feature_names

    mat = np.array([[float(r.get(name, 0.0)) for name in feature_names] for r in rows], dtype=np.float32)
    return mat, feature_names


def _normalize(x: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    mean = x.mean(axis=0)
    std = x.std(axis=0)
    std = np.where(std < 1e-6, 1.0, std)
    x_norm = (x - mean) / std
    return x_norm.astype(np.float32), mean.astype(np.float32), std.astype(np.float32)


def _load_checkpoint(model: DenoisingAutoEncoder, checkpoint_path: str, device: str) -> None:
    if not os.path.exists(checkpoint_path):
        return
    try:
        payload = torch.load(checkpoint_path, map_location=device)
        state_dict = payload.get("state_dict") if isinstance(payload, dict) else None
        if isinstance(state_dict, dict):
            model.load_state_dict(state_dict, strict=False)
    except Exception as e:
        log.warning("failed loading dl shadow checkpoint: {}", repr(e))


def process_once(
    models_dir: str,
    telemetry_filename: str,
    model_filename: str,
    window_minutes: int,
    limit: int,
    epochs: int,
    batch_size: int,
    lr: float,
    noise_std: float,
    mask_ratio: float,
) -> dict:
    telemetry = DlShadowTelemetry(top_shadow_events=[])
    telemetry_path = os.path.join(models_dir, telemetry_filename)
    model_path = os.path.join(models_dir, model_filename)

    rows = _fetch_recent_rows(window_minutes=window_minutes, limit=limit)
    telemetry.samples_used = len(rows)

    if len(rows) < 256:
        telemetry.status = "unavailable"
        telemetry.note = "insufficient_scored_rows"
        telemetry.last_run_utc = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        payload = asdict(telemetry)
        _write_json(telemetry_path, payload)
        return payload

    x_raw, feature_names = _build_feature_matrix(rows)
    x_norm, mean, std = _normalize(x_raw)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    telemetry.device = device

    x = torch.from_numpy(x_norm).to(device)
    model = DenoisingAutoEncoder(input_dim=x.shape[1]).to(device)
    _load_checkpoint(model, checkpoint_path=model_path, device=device)

    optimizer = torch.optim.Adam(model.parameters(), lr=max(1e-5, float(lr)))
    model.train()

    n = x.shape[0]
    bsz = max(32, int(batch_size))
    epochs_i = max(1, int(epochs))
    telemetry.train_epochs = epochs_i

    last_loss = 0.0
    for _ in range(epochs_i):
        order = torch.randperm(n, device=device)
        for start in range(0, n, bsz):
            idx = order[start : start + bsz]
            batch = x[idx]
            mask = (torch.rand_like(batch) > float(mask_ratio)).float()
            noisy = batch + torch.randn_like(batch) * float(noise_std)
            corrupted = noisy * mask

            optimizer.zero_grad(set_to_none=True)
            recon = model(corrupted)
            loss = F.mse_loss(recon, batch)
            loss.backward()
            optimizer.step()
            last_loss = float(loss.detach().item())

    model.eval()
    with torch.no_grad():
        recon = model(x)
        err = torch.mean((recon - x) ** 2, dim=1).detach().cpu().numpy()

    p90 = float(np.percentile(err, 90.0))
    p99 = float(np.percentile(err, 99.0))
    mx = float(np.max(err))
    high = int(np.sum(err >= p99))

    online_scores = x_raw[:, 3]
    if np.std(err) > 1e-8 and np.std(online_scores) > 1e-8:
        corr = float(np.corrcoef(err, online_scores)[0, 1])
    else:
        corr = 0.0

    order_idx = np.argsort(err)[::-1][:5]
    top_events: list[dict] = []
    for idx in order_idx.tolist():
        row = rows[idx]
        top_events.append(
            {
                "route_id": row.get("route_id"),
                "stop_id": row.get("stop_id"),
                "stop_name": row.get("stop_id"),
                "dl_error": round(float(err[idx]), 6),
                "online_score": round(float(row.get("online_score", 0.0)), 6),
            }
        )

    telemetry.status = "available"
    telemetry.loss_last = float(last_loss)
    telemetry.recon_error_p90 = p90
    telemetry.recon_error_p99 = p99
    telemetry.recon_error_max = mx
    telemetry.shadow_alerts_high = high
    telemetry.corr_with_online_score = corr
    telemetry.top_shadow_events = top_events
    telemetry.last_run_utc = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

    payload = asdict(telemetry)

    try:
        os.makedirs(models_dir, exist_ok=True)
        torch.save(
            {
                "state_dict": model.state_dict(),
                "feature_names": feature_names,
                "feature_mean": mean.tolist(),
                "feature_std": std.tolist(),
                "saved_at_utc": telemetry.last_run_utc,
            },
            model_path,
        )
    except Exception as e:
        log.warning("failed to save dl shadow model: {}", repr(e))

    _write_json(telemetry_path, payload)
    return payload


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="PyTorch SSL shadow model for subway anomaly signals")
    parser.add_argument("--tick", type=int, default=120, help="Seconds between shadow cycles")
    parser.add_argument("--window-minutes", type=int, default=240, help="History horizon in minutes")
    parser.add_argument("--limit", type=int, default=18000, help="Maximum rows loaded per cycle")
    parser.add_argument("--epochs", type=int, default=4, help="Training epochs per cycle")
    parser.add_argument("--batch-size", type=int, default=1024, help="Training mini-batch size")
    parser.add_argument("--lr", type=float, default=0.0012, help="Learning rate")
    parser.add_argument("--noise-std", type=float, default=0.08, help="Gaussian noise std for denoising objective")
    parser.add_argument("--mask-ratio", type=float, default=0.2, help="Mask ratio for denoising objective")
    parser.add_argument("--models-dir", type=str, default=DEFAULT_MODELS_DIR, help="Directory for model artifacts")
    parser.add_argument(
        "--telemetry-filename",
        type=str,
        default=DEFAULT_TELEMETRY_FILENAME,
        help="Telemetry JSON filename under models-dir",
    )
    parser.add_argument(
        "--model-filename",
        type=str,
        default=DEFAULT_MODEL_FILENAME,
        help="Model checkpoint filename under models-dir",
    )
    args = parser.parse_args(argv)

    os.makedirs(args.models_dir, exist_ok=True)
    log.info(
        "dl_shadow starting: tick={}s window={}m limit={} epochs={} batch={} models_dir={}",
        args.tick,
        args.window_minutes,
        args.limit,
        args.epochs,
        args.batch_size,
        args.models_dir,
    )

    while True:
        try:
            out = process_once(
                models_dir=args.models_dir,
                telemetry_filename=args.telemetry_filename,
                model_filename=args.model_filename,
                window_minutes=args.window_minutes,
                limit=args.limit,
                epochs=args.epochs,
                batch_size=args.batch_size,
                lr=args.lr,
                noise_std=args.noise_std,
                mask_ratio=args.mask_ratio,
            )
            log.info(
                "dl shadow cycle: status={} samples={} p99={} corr={} alerts={}",
                out.get("status"),
                out.get("samples_used"),
                out.get("recon_error_p99"),
                out.get("corr_with_online_score"),
                out.get("shadow_alerts_high"),
            )
        except Exception as e:
            log.warning("dl shadow cycle error: {}", repr(e))
        time.sleep(max(5, int(args.tick)))


if __name__ == "__main__":
    main()
