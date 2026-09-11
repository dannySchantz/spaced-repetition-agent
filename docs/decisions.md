# Implementation decisions

- Python 3.12 retained in a separate Conda environment named `recall`.
- This machine's Python HTTPS connections time out, while curl succeeds. For initial setup only, downloaded Conda artifacts and PyPI wheels with curl; PyPI wheel SHA-256 values verified against PyPI metadata. Installed wheels locally. Normal documented installation uses pip and pinned locks.
- Alembic migrations ship inside the package and run through SQLAlchemy connections, so an installed wheel can initialize a database without a source checkout.
- Live credentials do not implicitly enable paid calls or real SMS. Local fixtures and simulator are the defaults.
- Dependencies were also installed successfully in a clean Linux arm64 Docker image.
  `greenlet` is explicit in the lock to cover SQLAlchemy's platform-dependent dependency.
  Build backend, Python base image, and Caddy image are pinned; container images include digests.
- Offline grading is explicit fixture replay. Unknown free-form answers stay pending;
  no approximate string-matching grader is presented as semantic AI.
- Live grading and the collection assistant share an opt-in provider and durable token
  allowance; automatic live grading additionally requires a matching, passed, human-reviewed
  evaluation report. No live model was selected or evaluated during this build.
- Collection management uses bounded application operations. Model-proposed definitions
  and edits require explicit review; archive/restore require owner intent and exact IDs.
- The service owns writes. `recall init` is an offline maintenance operation protected by
  the same database lock; backup/restore in the CLI use authenticated service endpoints.
- JSON learning imports require an empty destination and omit messaging queues and pending
  assistant edit proposals. Full SQLite restore retains those audit rows, while cancelling
  unfinished work and requiring new consent/reactivation. Neither path silently merges histories.
- Layout uses a scrollable reserved card region and a visually hidden rating row until
  reveal, so animation and appearance of ratings do not move the controls.
- Original project licensing/public package naming remains an owner release decision;
  no public package was published. Third-party notices include installed license texts.
