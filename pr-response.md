# PR Response Doc — CineLog Watchlist Feature

This document responds to all six review comments from @dev-lead on the
`feature/watchlist` PR. For each comment it records what changed, why, and how
I verified it. Comments 4 and 5 are design decisions and are argued in full.

**Verification baseline:** `pytest tests/` → 13 passed (4 collection + 9 watchlist).

---

## AI Usage

I used an AI assistant for orientation and hygiene, not for the design decisions:

- **Orientation:** summarizing what `collection_service.py` and `models.py` do,
  and confirming how `add_to_collection()` handles deduplication and what it
  returns when a film is missing, before writing the watchlist equivalents.
- **Commit hygiene:** after rewriting history, I gave the AI my `git log
  --oneline` output and asked whether the messages follow Conventional Commits
  and whether any commit bundled multiple logical changes. It flagged nothing;
  I re-checked each prefix against the table in `CONTRIBUTING.md` myself.
- **Stress-testing the design arguments (Comments 4 and 5):** after I wrote my
  own positions, I asked the AI: *"What counterargument would a careful reviewer
  raise against this, and what tradeoff am I not acknowledging?"*
  - For **Comment 4** it pushed the "CineLog is a *community* app, so public
    default drives discovery" line. I had already anticipated that, so I kept my
    position but sharpened the tradeoff paragraph to name discovery explicitly
    and explain why consent still wins here.
  - For **Comment 5** it argued "consistency between endpoints matters more than
    you think." That was fair, so I added the concrete mitigation (documenting
    the difference in the docstring + a pinning test) and the `?sort=` follow-up
    offer rather than just asserting alphabetical is better.

  The positions and reasoning below are my own, grounded in CineLog's actual
  code (no `public` field on `CollectionEntry`, the app's self-description as a
  "community film tracking app", `get_collection`'s newest-first sort).

---

## Comment 1 — Rename

**What I did:** Renamed the service function `save_to_watchlist()` to
`add_to_watchlist()` and updated its call site in
`routes/watchlist/watchlist.py` (both the `import` and the call inside
`add_film`). Commit: `fix: rename save_to_watchlist to add_to_watchlist per
naming convention`.

**Where I looked for call sites / how I confirmed none were missed:** I ran a
project-wide search for the old name (`git grep save_to_watchlist`). Before the
rename it appeared in exactly two places — the definition in
`services/watchlist_service.py` and the import + call in
`routes/watchlist/watchlist.py`. After the rename, `git grep save_to_watchlist`
returns matches only inside this doc (where I reference the old name); there are
no remaining references in code, and the app imports cleanly.

**Reasoning:** `CONTRIBUTING.md` and `README.md` both document a `verb_to_noun`
naming convention, and the existing collection API uses `add_to_collection()`,
`remove_from_collection()`, `get_collection()`. `save_to_watchlist` broke that
pattern with a different verb (`save` vs `add`). Matching `add_to_*` keeps the
two features symmetrical and set up the naming for the stretch
`remove_from_watchlist()`.

---

## Comment 2 — Deduplication

**What I did:** Added deduplication to `add_to_watchlist()`, mirroring
`add_to_collection()`. Commit: `fix: add deduplication check to prevent
duplicate watchlist entries`.

**What the logic does (the check and what happens on a duplicate):** Before
inserting, `add_to_watchlist()` queries for an existing `WatchlistEntry` with
the same `(user_id, film_id)`:
```python
existing = WatchlistEntry.query.filter_by(user_id=user_id, film_id=film_id).first()
if existing:
    raise AlreadyInWatchlistError(...)
```
If a row already exists, it raises the new `AlreadyInWatchlistError` instead of
creating a second row; the `/add` route catches it and returns HTTP 409. If no
row exists, it inserts and commits as before. I also added a
`UniqueConstraint("user_id", "film_id", name="unique_user_film_watchlist")` to
the model as a database-level safety net.

**Where I looked / the pattern I followed:** I read `add_to_collection()` in
`services/collection_service.py`. It does the same two-layer thing: an
application-level `filter_by(...).first()` check that raises
`AlreadyInCollectionError`, backed by a `UniqueConstraint` on
`CollectionEntry`. I copied that structure exactly (typed error + 409 + unique
constraint) so the watchlist behaves like the collection a contributor already
knows.

**How I verified:** `test_add_to_watchlist_duplicate_raises` adds the same film
twice, asserts `AlreadyInWatchlistError`, and confirms exactly one row exists.
`test_watchlist_dedup_is_per_user` confirms the guard is scoped to
`(user, film)` and doesn't block a second user.

---

## Comment 3 — Missing test

**What I did:** Added `tests/test_watchlist.py`. Commit: `test: add watchlist
tests for add_to_watchlist (happy, duplicate, nonexistent)`. It covers the three
cases `CONTRIBUTING.md` requires for a new service function:
1. Happy path — `test_add_to_watchlist_creates_entry`
2. Duplicate/conflict — `test_add_to_watchlist_duplicate_raises`
3. Nonexistent ID — `test_add_to_watchlist_nonexistent_film_raises`

**What the nonexistent-ID test checks and which test it was modeled after:**
`test_add_to_watchlist_nonexistent_film_raises` was modeled directly on
`test_add_to_collection_nonexistent_film_raises` in `tests/test_collection.py`.
It uses the same `app` / `sample_user` fixtures, passes a `film_id` that isn't
in the database (a UUID string that was never inserted), and asserts that
`add_to_watchlist()` raises `FilmNotFoundError` — i.e., the service catches the
missing film itself rather than letting a database integrity error surface.

**How I verified:** `pytest tests/` → 13 passed.

---

## Comment 4 — Default visibility

**My position:** Watchlist entries should default to **private**
(`public=False`). I changed the model default from `True` to `False` and made
`add_to_watchlist()` default `public=False`.

**Reasoning (grounded in CineLog):** A watchlist is a list of films a user
*plans* to watch — it exposes intent and future behavior, which is more
sensitive than a log of films already watched. Two facts about CineLog make
public-by-default the wrong call here:

1. **There is no precedent for public-by-default in this codebase.**
   `CollectionEntry` — the app's older, central feature — has *no* visibility
   field at all. Nothing in CineLog currently broadcasts a user's activity to
   the "community." Shipping the watchlist with `public=True` would silently
   make it the first feature that opts every user into sharing, without them
   asking. That's a surprising default to introduce through a single feature PR.
2. **The failure modes are asymmetric.** If we default to private and a user
   wants to share, they flip a flag — mildly annoying. If we default to public
   and a user didn't realize it, their "want to watch" list is exposed until
   they discover the setting and turn it off — a privacy regression that can't
   be undone after the fact. When the costs are lopsided like this, the safer
   default is the reversible one.

**Tradeoff acknowledged:** CineLog describes itself as a "community film
tracking app," and community/discovery features (seeing what others plan to
watch, recommendations) are stronger when more lists are public. Private-by-
default means those features start with less data and depend on users opting
in. I think that's the right price: discovery built on data users didn't
knowingly share isn't really community, it's exposure. To keep the discovery
path open, I paired this with the visibility toggle (stretch) so a caller can
set `public=True` explicitly at add time — sharing stays a deliberate choice
rather than a default.

**How I verified:** `test_add_to_watchlist_defaults_to_private` and
`test_add_to_watchlist_public_override`.

---

## Comment 5 — Sort order

**My position:** I'm keeping `get_watchlist()` sorted **alphabetically by title**
(`Film.title.asc()`) rather than switching it to `get_collection()`'s
newest-first order. This is a respectful disagreement with the review.

**Engagement with the reviewer's point:** The reviewer's point — "most users
want to see what they added recently," and two similar endpoints returning data
in different orders is a real cost — is legitimate. Inconsistency between
sibling endpoints is a small tax every time someone reads or consumes both, and
I don't want to wave that away.

**Reasoning (grounded in CineLog):** But consistency should follow from the data
meaning the same thing, and here it doesn't. The two lists answer different
questions:

- A **collection** is a *log of past activity* — "what have I watched, most
  recently?" Recency is the natural axis, which is exactly why
  `get_collection()` sorts `date_added.desc()`.
- A **watchlist** is a *planning/browsing tool* — "what should I watch next?"
  The user scans the whole list to pick a title. The date they happened to add
  something carries little signal for that task, and newest-first actively
  buries older entries the user may have been meaning to get to. Alphabetical
  order makes a specific title findable by scanning, which is the actual job of
  this screen.

So the difference isn't an inconsistency to paper over — it reflects that a
"to-watch" list and a "have-watched" list are used differently. Forcing them to
match would make the watchlist worse to use in exchange for surface symmetry.

**Tradeoff / path forward:** The cost is the cognitive overhead the reviewer
flagged. I've mitigated it by (a) documenting the deliberate difference in the
`get_watchlist()` docstring so it doesn't read like an oversight, and (b) adding
`test_get_watchlist_returns_alphabetical`, which pins the ordering as intended
behavior. If we later find users actually want recency ("what did I just add?"),
the cleanest resolution isn't to flip the default but to add a `?sort=` query
param — that serves both needs without making either list lie about what it's
for. I'm happy to do that in a follow-up if you'd prefer.

---

## Comment 6 — Rebase

**What conflicted:** While the PR was open, `refactor: migrate film IDs from
integer to UUID` merged to `main`. My branch was cut before that refactor, so it
still modeled films with integer IDs. The conflict was in `models.py`: my
`WatchlistEntry.film_id` was `db.Integer` with a foreign key to `Film.id`, but on
`main` `Film.id` is now `db.String(36)` (a UUID). An integer foreign key
pointing at a UUID primary key is broken.

This one had a trap. Because `main` had rewritten large parts of `models.py`,
`git rebase origin/main` reported success **without conflict markers** — and in
doing so silently dropped my `WatchlistEntry` class entirely rather than merging
it. I only caught this by reading the rebased file instead of trusting the
"rebased successfully" message.

**How I resolved it:** I rebased `feature/watchlist` onto `origin/main`, then
corrected the (semantic) conflict by hand and captured it as its own commit,
`fix: update WatchlistEntry film_id to UUID after main branch refactor`:
- Changed `WatchlistEntry.film_id` from `db.Integer` to
  `db.String(36), db.ForeignKey("film.id")` so it matches the UUID `Film.id`.
- Updated the service docstrings/type notes from `int` to UUID (`str`).
- Kept the `db.session.get(Film, film_id)` lookup style `main` had also moved to.

The feature history is linear — I rebased rather than merging — so the branch
contains **no merge commits** (`git log --graph` shows no "Merge branch" nodes
introduced by my work).

**How I verified no conflict remains:** `git status` is clean with no rebase in
progress; `git grep` finds no conflict markers (`<<<<<<<`, `=======`,
`>>>>>>>`); the app imports and creates its tables cleanly with a UUID
`Film.id`; and all 13 tests pass against the UUID schema (the `sample_film`
fixture yields a UUID string and the nonexistent-ID test uses a UUID).

---

## Stretch Features

### `remove_from_watchlist()`
Commit: `feat: add remove_from_watchlist function and endpoint`. Implemented
`remove_from_watchlist(user_id, film_id)` following the collection pattern: it
looks up the `(user_id, film_id)` entry and, **when the film isn't on the
watchlist, raises `NotInWatchlistError`** (matching how
`remove_from_collection()` raises `NotInCollectionError`); otherwise it deletes
the row and returns `True`. Exposed as `DELETE /watchlist/<user_id>/remove`,
which returns 404 on `NotInWatchlistError`. Tests:
`test_remove_from_watchlist_deletes_entry` and
`test_remove_from_watchlist_not_present_raises`.

### Second (unrequested) test
Commit: `test: add per-user deduplication edge-case test for watchlist`
(`test_watchlist_dedup_is_per_user`). I chose this edge case because Comment 2
introduced a unique constraint, and the subtle way to get that constraint wrong
is to scope it to the film alone instead of `(user, film)` — which would let one
user's watchlist block everyone else's. The happy-path and duplicate tests
wouldn't catch that regression; this one does, by asserting two different users
can both hold the same film.

### Visibility toggle
Commit: `feat: add public visibility toggle to add_to_watchlist, default
private`. Added a `public` parameter to `add_to_watchlist(user_id, film_id,
public=False)` and threaded it through the `POST /watchlist/<user_id>/add`
endpoint via `data.get("public", False)`. **The default is `False` (private).**
A caller opts in to sharing by sending `{"film_id": "...", "public": true}`.
This is what makes the private-by-default decision in Comment 4 practical —
sharing becomes an intentional opt-in rather than a silent default. Tests:
`test_add_to_watchlist_defaults_to_private` and
`test_add_to_watchlist_public_override`.

---

## Commit History (screenshot)

Final `git log --oneline` on `feature/watchlist` (relative to `main`) — nine
conventional commits, each one logical change, no merge commits:

```
1c604a5 test: add per-user deduplication edge-case test for watchlist
0e26b0d feat: add public visibility toggle to add_to_watchlist, default private
a0cd70b feat: add remove_from_watchlist function and endpoint
e9844ae test: add watchlist tests for add_to_watchlist (happy, duplicate, nonexistent)
f91bd3a fix: update WatchlistEntry film_id to UUID after main branch refactor
2c83e17 fix: add deduplication check to prevent duplicate watchlist entries
47162cb fix: rename save_to_watchlist to add_to_watchlist per naming convention
b5c7bbd feat: add watchlist model, service, and view/add endpoints
5f66e68 refactor: use db.session.get for film lookup in collection service
```

> Replace this code block with a screenshot of your own `git log --oneline`
> output before submitting (the commit hashes will match the block above).

Comment → commit map: rename → `47162cb`; deduplication → `2c83e17`; missing
test → `e9844ae`; UUID rebase fix → `f91bd3a`; `remove_from_watchlist` →
`a0cd70b`; visibility toggle → `0e26b0d`; second test → `1c604a5`. Comments 4
and 5 are decisions documented here (private default is realized in `0e26b0d`;
alphabetical sort is unchanged from the original feature and defended above).

---

## PR Description

**What the watchlist feature does:** Adds a personal watchlist to CineLog — films
a user wants to watch later, kept separate from their collection of
already-watched films. Users can add a film (`POST /watchlist/<user_id>/add`),
remove one (`DELETE /watchlist/<user_id>/remove`), and view the list
(`GET /watchlist/<user_id>`), returned alphabetically by title. Adding a film
that's already on the list returns 409; adding a film that doesn't exist returns
404. Deduplication and error handling mirror the existing collection feature.

**Design decisions:**
- **Default visibility — private.** New watchlist entries default to
  `public=False`; callers opt in to public sharing explicitly per entry, so no
  one is opted into exposing their viewing intentions by default.
- **Sort order — alphabetical by title.** A deliberate departure from the
  collection's newest-first order, because a watchlist is a browse-to-pick list
  rather than an activity log; alphabetical order makes titles findable.

**How to manually test end to end:**
```bash
pip install -r requirements.txt
python app.py                       # serves http://127.0.0.1:5000

# 1. Find a real film UUID (film data is seeded):
curl http://127.0.0.1:5000/films/

# 2. Add it to a user's watchlist (private by default) — expect 201:
curl -X POST http://127.0.0.1:5000/watchlist/<user_id>/add \
     -H "Content-Type: application/json" \
     -d '{"film_id": "<film_uuid>"}'

# 3. Add the SAME film again — expect 409 (deduplication):
#    {"error": "Film '<uuid>' is already on this user's watchlist"}

# 4. Add a film with an unknown id — expect 404 (FilmNotFound):
curl -X POST http://127.0.0.1:5000/watchlist/<user_id>/add \
     -H "Content-Type: application/json" \
     -d '{"film_id": "does-not-exist"}'

# 5. Add another film publicly, then view the list (alphabetical by title):
curl -X POST http://127.0.0.1:5000/watchlist/<user_id>/add \
     -H "Content-Type: application/json" \
     -d '{"film_id": "<other_film_uuid>", "public": true}'
curl http://127.0.0.1:5000/watchlist/<user_id>

# 6. Remove a film — expect 200; removing one not on the list — expect 404:
curl -X DELETE http://127.0.0.1:5000/watchlist/<user_id>/remove \
     -H "Content-Type: application/json" \
     -d '{"film_id": "<film_uuid>"}'
```
Automated: `pytest tests/` → 13 passed.
