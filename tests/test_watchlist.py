"""
tests/test_watchlist.py — CineLog

Tests for the watchlist service. Mirrors the structure and fixtures used in
tests/test_collection.py, per CONTRIBUTING.md (happy path, duplicate/conflict,
nonexistent ID).
"""

import pytest
from app import create_app, db
from models import User, Film, WatchlistEntry
from services.watchlist_service import (
    add_to_watchlist,
    remove_from_watchlist,
    get_watchlist,
    AlreadyInWatchlistError,
    NotInWatchlistError,
)
from services.collection_service import FilmNotFoundError


@pytest.fixture
def app():
    """Create an isolated test app with an in-memory database."""
    app = create_app(config={
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
    })
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def sample_user(app):
    """A user to use in tests."""
    with app.app_context():
        user = User(username="testuser", email="test@example.com")
        db.session.add(user)
        db.session.commit()
        return user.id


@pytest.fixture
def sample_film(app):
    """A film to use in tests."""
    with app.app_context():
        film = Film(title="Paddington 2", year=2017, genre="Comedy")
        db.session.add(film)
        db.session.commit()
        return film.id


# ── Basic add (happy path) ───────────────────────────────────────────────────

def test_add_to_watchlist_creates_entry(app, sample_user, sample_film):
    """
    Adding a valid film should create a WatchlistEntry in the database.
    """
    with app.app_context():
        entry = add_to_watchlist(user_id=sample_user, film_id=sample_film)

        assert entry is not None
        assert entry.user_id == sample_user
        assert entry.film_id == sample_film

        # Verify it persisted
        in_db = WatchlistEntry.query.filter_by(
            user_id=sample_user, film_id=sample_film
        ).first()
        assert in_db is not None


# ── Deduplication ────────────────────────────────────────────────────────────

def test_add_to_watchlist_duplicate_raises(app, sample_user, sample_film):
    """
    Adding the same film twice should raise AlreadyInWatchlistError,
    not silently create a duplicate entry.
    """
    with app.app_context():
        add_to_watchlist(user_id=sample_user, film_id=sample_film)

        with pytest.raises(AlreadyInWatchlistError):
            add_to_watchlist(user_id=sample_user, film_id=sample_film)

        # Confirm only one entry exists
        count = WatchlistEntry.query.filter_by(
            user_id=sample_user, film_id=sample_film
        ).count()
        assert count == 1


# ── Nonexistent film (modeled on test_add_to_collection_nonexistent_film_raises)

def test_add_to_watchlist_nonexistent_film_raises(app, sample_user):
    """
    Adding a film_id that doesn't exist in the database should raise
    FilmNotFoundError, not a database integrity error.
    """
    with app.app_context():
        fake_film_id = "00000000-0000-0000-0000-000000000000"

        with pytest.raises(FilmNotFoundError):
            add_to_watchlist(user_id=sample_user, film_id=fake_film_id)


# ── get_watchlist sort order (Comment 5) ─────────────────────────────────────

def test_get_watchlist_returns_alphabetical(app, sample_user):
    """
    get_watchlist() should return films sorted alphabetically by title,
    unlike get_collection() which sorts newest-first. See Comment 5.
    """
    with app.app_context():
        film_a = Film(title="Alien", year=1979, genre="Horror")
        film_z = Film(title="Zodiac", year=2007, genre="Thriller")
        # Add Zodiac first so insertion order differs from alphabetical order.
        db.session.add_all([film_z, film_a])
        db.session.commit()

        add_to_watchlist(user_id=sample_user, film_id=film_z.id)
        add_to_watchlist(user_id=sample_user, film_id=film_a.id)

        titles = [f["title"] for f in get_watchlist(sample_user)]
        assert titles == ["Alien", "Zodiac"]


# ── remove_from_watchlist (stretch) ──────────────────────────────────────────

def test_remove_from_watchlist_deletes_entry(app, sample_user, sample_film):
    """
    Removing a film that is on the watchlist should delete the entry.
    """
    with app.app_context():
        add_to_watchlist(user_id=sample_user, film_id=sample_film)

        result = remove_from_watchlist(user_id=sample_user, film_id=sample_film)
        assert result is True

        remaining = WatchlistEntry.query.filter_by(
            user_id=sample_user, film_id=sample_film
        ).count()
        assert remaining == 0


def test_remove_from_watchlist_not_present_raises(app, sample_user, sample_film):
    """
    Removing a film that isn't on the watchlist should raise
    NotInWatchlistError, matching remove_from_collection's behavior.
    """
    with app.app_context():
        with pytest.raises(NotInWatchlistError):
            remove_from_watchlist(user_id=sample_user, film_id=sample_film)


# ── Default visibility / toggle (Comment 4 + stretch) ────────────────────────

def test_add_to_watchlist_defaults_to_private(app, sample_user, sample_film):
    """
    A new watchlist entry should default to private (public=False) so users
    aren't opted into sharing their viewing intentions without asking.
    """
    with app.app_context():
        entry = add_to_watchlist(user_id=sample_user, film_id=sample_film)
        assert entry.public is False


def test_add_to_watchlist_public_override(app, sample_user, sample_film):
    """
    Callers can explicitly opt in to public visibility (visibility toggle).
    """
    with app.app_context():
        entry = add_to_watchlist(
            user_id=sample_user, film_id=sample_film, public=True
        )
        assert entry.public is True


# ── Extra edge case (stretch): dedup is scoped per user ──────────────────────

def test_watchlist_dedup_is_per_user(app, sample_film):
    """
    Edge case: the "already on watchlist" guard is scoped to (user, film),
    not to the film alone. Two different users must both be able to add the
    same film. This protects against an over-broad unique constraint that
    would let one user's watchlist block another's.
    """
    with app.app_context():
        user_a = User(username="ada", email="ada@example.com")
        user_b = User(username="bob", email="bob@example.com")
        db.session.add_all([user_a, user_b])
        db.session.commit()
        a_id, b_id = user_a.id, user_b.id

        add_to_watchlist(user_id=a_id, film_id=sample_film)
        # Should NOT raise — different user, same film.
        add_to_watchlist(user_id=b_id, film_id=sample_film)

        assert WatchlistEntry.query.filter_by(film_id=sample_film).count() == 2
