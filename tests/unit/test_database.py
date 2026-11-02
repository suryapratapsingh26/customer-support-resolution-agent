from unittest.mock import MagicMock, patch

from app.db.session import get_db


def test_get_db_closes_session():
    mock_session = MagicMock()

    with patch("app.db.session.SessionLocal", return_value=mock_session):
        db_generator = get_db()

        db = next(db_generator)

        assert db is mock_session

        db_generator.close()

        mock_session.close.assert_called_once()