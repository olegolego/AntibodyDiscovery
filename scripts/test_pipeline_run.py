"""Test a pipeline by submitting a run via the API and polling until done.

Usage:
    cd backend && .venv/bin/python ../scripts/test_pipeline_run.py "RL Test"
    cd backend && .venv/bin/python ../scripts/test_pipeline_run.py rl-test-25c7a5c6
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))


async def run_and_verify(name_or_id: str, max_wait_s: int = 600):
    try:
        import httpx
    except ImportError:
        print("httpx not found — pip install httpx")
        return

    BASE = "http://localhost:8000"

    async with httpx.AsyncClient(timeout=60) as client:
        # 1. Check backend is up
        try:
            await client.get(f"{BASE}/api/tools/")
        except Exception as e:
            print(f"Backend not reachable at {BASE}: {e}")
            print("Start it with:  cd backend && .venv/bin/python -m uvicorn app.main:app --reload")
            return

        # 2. Find pipeline
        pipelines = (await client.get(f"{BASE}/api/pipelines/")).json()
        pipeline = next(
            (p for p in pipelines
             if name_or_id.lower() in p["name"].lower() or p["id"] == name_or_id),
            None,
        )
        if not pipeline:
            print(f"Pipeline not found: {name_or_id!r}")
            print("Available pipelines:")
            for p in pipelines:
                print(f"  {p['id']}  {p['name']}")
            return

        print(f"Found: {pipeline['name']!r}  ({pipeline['id']})")

        # 3. Fetch full pipeline JSON (list endpoint strips params)
        full = (await client.get(f"{BASE}/api/pipelines/{pipeline['id']}")).json()

        # Submit run — POST body is the full Pipeline object
        resp = await client.post(f"{BASE}/api/runs/", json=full)
        if resp.status_code not in (200, 201):
            print(f"Failed to start run: {resp.status_code}  {resp.text}")
            return

        run = resp.json()
        run_id = run.get("id") or run.get("run_id")
        print(f"Run started: {run_id}")
        print()

    # 4. Poll with fresh client (long timeout)
    async with httpx.AsyncClient(timeout=max_wait_s) as client:
        last_statuses: dict = {}
        for tick in range(max_wait_s // 5):
            await asyncio.sleep(5)
            try:
                run = (await client.get(f"{BASE}/api/runs/{run_id}/")).json()
            except Exception as e:
                print(f"  [{tick*5}s] poll error: {e}")
                continue

            status = run.get("status", "?")
            nodes = run.get("nodes", {})
            statuses = {nid: n["status"] for nid, n in nodes.items()}

            # Only print when something changes
            if statuses != last_statuses or tick % 6 == 0:
                changed = {k: v for k, v in statuses.items() if last_statuses.get(k) != v}
                if changed:
                    print(f"  [{tick*5:4d}s] {status:12s}  changed: {changed}")
                else:
                    print(f"  [{tick*5:4d}s] {status:12s}  {statuses}")
                last_statuses = statuses

            if status in ("succeeded", "failed", "cancelled"):
                break

    # 5. Final report
    print()
    print("=" * 60)
    print(f"Final status: {run['status'].upper()}")
    print()

    nodes = run.get("nodes", {})
    all_ok = True
    for nid, n in nodes.items():
        s = n["status"]
        icon = "✓" if s == "succeeded" else ("✗" if s == "failed" else "·")
        print(f"  {icon} {nid:25s}  {s}")
        if s == "failed":
            all_ok = False
            err = n.get("error", "")
            if err:
                print(f"      ERROR: {err[:200]}")

    print()
    if all_ok and run["status"] == "succeeded":
        print("✓ All nodes succeeded — pipeline is working correctly.")

        # Check loop_end produced sequences
        loop_end_out = None
        for nid, n in nodes.items():
            if "loop_end" in nid.lower() or "loop" == nid.lower():
                loop_end_out = n.get("outputs", {})
        if loop_end_out:
            nh = loop_end_out.get("next_heavy_chain") or (loop_end_out.get("result") or {}).get("next_heavy_chain")
            print(f"  loop_end.next_heavy_chain: {(nh or '')[:40]!r}{'...' if nh and len(nh)>40 else ''}")
            if not nh:
                print("  WARNING: loop_end produced no next_heavy_chain — check loop_end code variable names")
    else:
        print("✗ Pipeline did not complete cleanly.")

    return run


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "RL Test"
    asyncio.run(run_and_verify(name))
