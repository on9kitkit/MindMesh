# MindMesh backend (StudyRoom source identifiers)

The FastAPI source implements PostgreSQL-owned room/quiz state, authenticated HTTP and WebSocket APIs, solo attempts, private reviews, completion receipts, bounded rewards and cosmetic pet state. Supabase Auth supplies identity; the app backend verifies tokens and owns StudyRoom data. The mobile client in this package uses realtime protocol v2 and the matching `/me/solo-attempts`, `/me/rewards`, `/me/pets` and daily-invitation APIs.

`pyproject.toml` requires Python 3.11+; `requirements.lock` pins the runtime image dependencies. The project has no bundled database, user account, provider key or hosted deployment. Runtime startup requires an authorized PostgreSQL database already at Alembic revision `0012_learning_companions` and **never upgrades it automatically**.

Start in the package root (the directory containing the top-level README). In a POSIX shell, install the backend dependencies:

```sh
STUDYROOM_PACKAGE_ROOT="$(pwd -P)"
cd "$STUDYROOM_PACKAGE_ROOT/backend"
python3.11 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
```

`backend/.env.example` is a placeholder reference, **not an automatically loaded configuration**. Both Alembic and the server read process environment variables (`os.environ`). Prepare your own private, owner-reviewed, POSIX-shell-compatible file outside this package with only the approved variables. It must include `DATABASE_URL` for a **new database you control** and `SUPABASE_URL` for JWT verification. Quote values safely for your shell and restrict access to the file. Sourcing a shell file executes its contents: never source an untrusted file or the unchanged example. Keep provider/admin keys absent unless separately authorized, and do not type credential values into shell commands or history.

After independently confirming that the `DATABASE_URL` in your reviewed file targets a newly created, controlled database—not an existing or shared database—set `STUDYROOM_BACKEND_ENV_FILE` in this shell to that file's absolute path. The commands below do **not** verify the database target for you. They load the private file only inside each command's subshell; do not run them before that target check:

```sh
: "${STUDYROOM_BACKEND_ENV_FILE:?Set this to your reviewed private env-file path first}"
studyroom_with_backend_env() (
  set -a
  . "$STUDYROOM_BACKEND_ENV_FILE"
  set +a
  "$@"
)
studyroom_with_backend_env alembic upgrade head
studyroom_with_backend_env python -m app.serve
```

These are documented operator steps, **not operations performed for this package**. `DATABASE_URL` must use `postgresql+psycopg`; the server defaults to loopback port 8000 and explicit local HTTP/WebSocket origins in development. Production requires separately reviewed HTTPS origins and verifying database TLS. Provider secrets stay backend-only. Without `OPENAI_API_KEY`, adaptive generation/eligible written grading are unavailable; without RevenueCat credentials, paid entitlement actions remain unavailable. Do not place secrets in the mobile environment.

Selected offline contract/fake tests passed; the PostgreSQL-dependent cases were not run here. See [../VALIDATION.md](../VALIDATION.md). Full runtime, migration, provider, concurrency and destructive account-deletion testing require an explicitly isolated environment and separate authority.
