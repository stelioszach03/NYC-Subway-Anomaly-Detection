from sqlalchemy import create_engine


def test_scores_metadata_creates():
    from api.app.models import Base

    engine = create_engine("sqlite:///:memory:", future=True)
    # Should not raise
    Base.metadata.create_all(engine)

