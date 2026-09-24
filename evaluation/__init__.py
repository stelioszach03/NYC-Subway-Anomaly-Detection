"""Evaluation entry points; heavy replay dependencies are loaded only on demand."""


def __getattr__(name):
    if name in __all__:
        from . import replay

        return getattr(replay, name)
    raise AttributeError(name)


__all__ = [
    "METHOD_COLUMNS",
    "load_replay_dataset",
    "replay_online_model",
    "run_replay_evaluation",
]
