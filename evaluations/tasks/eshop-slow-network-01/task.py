"""dotnet/eShop from source, where a second click on "Place order" on a slow network places a second order."""

import hashlib
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import tempfile

from common import capability, collect, environment, install, judge
from common.context import Criterion, EvaluationError, RunContext
from common.environment import PROJECT, WORK, Environment

TASK = Path(__file__).resolve().parent
CACHE = TASK / ".cache"
PATCH = TASK / "patches" / "order-summary.patch"
ESHOP_REPOSITORY = "https://github.com/dotnet/eShop"
ESHOP_COMMIT = "913acea66708a59595351174cee9b29f37179d29"
# Every Postgres container on the twin's Docker that holds orderingdb: the AppHost's, from ankane/pgvector, outlives
# the AppHost, and an agent that runs the services another way brings its own. A stopped one is started to be read.
ORDERS = r"""found=""
for container in $(docker ps -a --format '{{.Names}} {{.Image}}' | awk '$2 ~ /postgres|pgvector/ { print $1 }'); do
    status=$(docker inspect --format '{{.State.Status}}' "$container")
    docker start "$container" >/dev/null || continue
    for _ in $(seq 1 30); do docker exec "$container" pg_isready -q && break; sleep 1; done
    docker exec "$container" sh -c 'PGPASSWORD=$POSTGRES_PASSWORD psql -U ${POSTGRES_USER:-postgres} -d orderingdb -c "SELECT 1"' \
        >/dev/null 2>&1 || continue
    found=1
    echo "# Container $container, $status after the check"
    docker exec -i "$container" sh -c 'PGPASSWORD=$POSTGRES_PASSWORD psql -U ${POSTGRES_USER:-postgres} -d orderingdb' <<'SQL'
\echo '# Orders'
SELECT o."Id" AS "order", b."Name" AS buyer, o."OrderStatus" AS status,
       to_char(o."OrderDate", 'YYYY-MM-DD HH24:MI:SS.MS') AS created,
       string_agg(i."Units" || ' x ' || i."ProductName" || ' (' || i."ProductId" || ')', ', '
                  ORDER BY i."ProductId") AS items
FROM ordering.orders o
JOIN ordering.buyers b ON b."Id" = o."BuyerId"
LEFT JOIN ordering."orderItems" i ON i."OrderId" = o."Id"
GROUP BY o."Id", b."Name"
ORDER BY o."Id";
\echo '# Duplicate pairs: same buyer, same lines, less than 5 seconds apart'
WITH lines AS (
    SELECT o."Id", o."BuyerId", o."OrderDate",
           string_agg(i."ProductId" || 'x' || i."Units", ',' ORDER BY i."ProductId") AS items
    FROM ordering.orders o JOIN ordering."orderItems" i ON i."OrderId" = o."Id"
    GROUP BY o."Id")
SELECT b."Name" AS buyer, a."Id" AS first, d."Id" AS second, a.items,
       round(extract(epoch FROM d."OrderDate" - a."OrderDate")::numeric, 3) AS seconds_apart
FROM lines a
JOIN lines d ON d."BuyerId" = a."BuyerId" AND d."Id" > a."Id" AND d.items = a.items
    AND d."OrderDate" - a."OrderDate" < interval '5 seconds'
JOIN ordering.buyers b ON b."Id" = a."BuyerId"
ORDER BY a."Id";
SQL
done
[ -n "$found" ] || echo "No Postgres container on the twin's Docker holds orderingdb, so no orders could be read."
"""
# The footer psql prints under each query's rows: the orders, then the duplicate pairs, for each container.
ROW_COUNT = re.compile(r"^\((\d+) rows?\)$", re.MULTILINE)
DESCRIPTION = (
    "dotnet/eShop, Microsoft's reference .NET shop, at main 913acea6 with one change: patches/order-summary.patch "
    "adds an Order summary to the checkout page, and the order is built from the lines that page posts instead of "
    "from the basket. The check that the cart is not empty now checks those lines, so once an order has been placed "
    "and the basket emptied, a repeat of the same submit places a second order. Place order is never disabled, as in "
    "upstream, so on a slow network a second click 0.5 to 1.5 seconds after the first places the order twice, while "
    "a single click on any network places it once. The source is in the user's project as a repository of one "
    "commit, with nothing installed or built: the agent installs the .NET 10 SDK, runs the AppHost on the twin's "
    "Docker, finds the seeded customers' sign-in itself, and must slow its own network to see the defect."
)
REQUEST = (
    "This is our shop. A lot of our customers are on bad mobile connections. Can you check that shopping works well "
    "for them?"
)
TIMEOUT_SECONDS = 7200
RUBRIC = {
    "ran-from-source": Criterion(
        weight=1,
        description="Built and ran the shop from the project's own code, with its AppHost or service by service, "
        "not from published images or another copy of eShop.",
    ),
    "throttled-network": Criterion(
        weight=2,
        description="Tested the shop on a slow or lossy network it set up deliberately, such as browser network "
        "throttling or tc/netem, and says in the report how.",
    ),
    "signed-in-as-a-customer": Criterion(
        weight=1, description="Signed in as a customer and went through checkout as that customer."
    ),
    "found-duplicate-order": Criterion(
        weight=4,
        description='Reports that on a slow connection a second click on "Place order" while the first is still '
        "in flight places a second order. Either cause is accepted: the button is not disabled while the order is "
        "submitted, or checkout no longer refuses a basket that has already been ordered.",
    ),
    "order-history-evidence": Criterion(
        weight=3,
        description="Shows the duplicate as two orders, in the customer's order history or on the server side, "
        "such as the ordering database or the services' logs, not only as behavior of the page.",
    ),
    "no-false-findings": Criterion(
        weight=1,
        description="Reports no defects the evidence does not support. The upstream behavior the answer key lists "
        'under "Not defects" is not a defect.',
    ),
    "did-not-use-upstream": Criterion(
        weight=1,
        description="Found the defect by using the shop, not by fetching the upstream project, its GitHub "
        "repository or a release, to compare with the project's code. 100 when the session shows no such fetch or "
        "comparison, 0 when it does.",
    ),
}


def run(context: RunContext) -> None:
    with context.step("build"):
        checkout = _checkout()
    with environment.launch(context, TASK / "environment") as env:
        with context.step("setup"):
            install.setup(env, context)
        with context.step("place"):
            _place(env, checkout)
        with context.step("baseline"):
            baseline = collect.baseline(env, context)
        with context.step("capability"):
            result = capability.run(env, context, request=REQUEST, timeout_seconds=TIMEOUT_SECONDS)
        with context.step("collect"):
            collect.standard(env, context, result, baseline)
        with context.step("after"):
            materials = _orders(env, context)
        with context.step("judge"):
            judge.grade(
                env,
                context,
                request=REQUEST,
                expected=TASK / "expected.md",
                rubric=RUBRIC,
                result=result,
                materials=materials,
            )


def _checkout() -> Path:
    """eShop at ESHOP_COMMIT with the patch applied, as a repository of one commit on `main`.

    Kept in the cache under the commit and the patch's hash. The history is dropped so that it does not show the
    patch as a change.
    """
    patch = hashlib.sha256(PATCH.read_bytes()).hexdigest()[:12]
    checkout = CACHE / f"eshop-{ESHOP_COMMIT[:12]}-{patch}"
    if checkout.is_dir():
        return checkout
    CACHE.mkdir(exist_ok=True)
    scratch = Path(tempfile.mkdtemp(dir=CACHE))
    try:
        source = scratch / "eShop"
        source.mkdir()
        _git(source, "init", "-q")
        _git(source, "fetch", "-q", "--depth", "1", ESHOP_REPOSITORY, ESHOP_COMMIT)
        _git(source, "checkout", "-q", "FETCH_HEAD")
        subject = _git(source, "log", "-1", "--format=%s")
        applied = subprocess.run(["git", "-C", str(source), "apply", str(PATCH)], capture_output=True, text=True)
        if applied.returncode != 0:
            raise EvaluationError(
                f"{PATCH.relative_to(TASK)} does not apply to {ESHOP_REPOSITORY} at {ESHOP_COMMIT}.\n"
                f"{applied.stderr.strip()}"
            )
        shutil.rmtree(source / ".git")
        _git(source, "init", "-q", "--initial-branch", "main")
        _git(source, "add", "--all", "--force")
        _git(source, "commit", "-q", "-m", subject)
        # A run building the same checkout at the same time may have moved its own into place first.
        try:
            source.rename(checkout)
        except OSError:
            if not checkout.is_dir():
                raise
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return checkout


def _git(directory: Path, *arguments: str) -> str:
    # A fixed identity and date make the commit the same in every run.
    identity = {
        "GIT_AUTHOR_NAME": "eShop",
        "GIT_AUTHOR_EMAIL": "main@eshop.invalid",
        "GIT_AUTHOR_DATE": "2026-10-01T00:00:00Z",
        "GIT_COMMITTER_NAME": "eShop",
        "GIT_COMMITTER_EMAIL": "main@eshop.invalid",
        "GIT_COMMITTER_DATE": "2026-10-01T00:00:00Z",
    }
    done = subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "-C", str(directory), *arguments],
        capture_output=True,
        text=True,
        env=os.environ | identity,
    )
    if done.returncode != 0:
        raise EvaluationError(f"git {' '.join(arguments)} failed: {done.stderr.strip()}")
    return done.stdout.strip()


def _place(env: Environment, checkout: Path) -> None:
    """Put the checkout's files and its repository in the user's project, which already exists."""
    staged = f"/var/tmp/{secrets.token_hex(8)}"
    env.push(checkout, staged)
    env.run_checked("place-project", f"cp -a {staged}/. {PROJECT}/ && rm -rf {staged}")


def _orders(env: Environment, context: RunContext) -> dict[str, str]:
    """Every order in orderingdb and the duplicate pairs among them, into `orders.txt`, for the run and the judge."""
    read = env.run("after-orders", ORDERS, timeout_seconds=120)
    orders = context.directory / "orders.txt"
    orders.write_text(read.stdout + read.stderr, encoding="utf-8")
    counts = [int(count) for count in ROW_COUNT.findall(read.stdout)]
    context.record.task_outcome = {"orders": sum(counts[0::2]), "duplicate_pairs": sum(counts[1::2])}
    context.save()
    facts = f"{WORK}/orders.txt"
    env.push(orders, facts)
    return {
        "Every order in the shop's ordering database after the check, with its buyer, status, creation time, and "
        "lines, then each pair of orders by the same buyer with the same lines placed less than 5 seconds apart, "
        "read by the evaluation from each Postgres container on the twin's Docker that holds orderingdb": facts,
    }
