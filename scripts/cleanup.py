"""Delete all sandboxes starting with pa- prefix."""

import asyncio
import os
import sys

from dotenv import load_dotenv

load_dotenv()

CELESTO_API_KEY = os.environ.get("CELESTO_API_KEY", "")


async def celesto(args: list[str]) -> tuple[str, str, int]:
    proc = await asyncio.create_subprocess_exec(
        "celesto", *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, "CELESTO_API_KEY": CELESTO_API_KEY}
    )
    stdout, stderr = await proc.communicate()
    return stdout.decode(), stderr.decode(), proc.returncode


async def main():
    print("Listing all computers...")
    stdout, stderr, rc = await celesto(["computer", "list", "--format", "json"])
    if rc != 0:
        print(f"Failed to list computers: {stderr}")
        sys.exit(1)

    import json
    try:
        computers = json.loads(stdout)
    except json.JSONDecodeError:
        # Try line-by-line names
        computers = [{"name": line.strip()} for line in stdout.splitlines() if line.strip()]

    pa_computers = [c for c in computers if c.get("name", "").startswith("pa-")]
    print(f"Found {len(pa_computers)} pa-* sandboxes to delete.")

    for computer in pa_computers:
        name = computer["name"]
        print(f"  Deleting {name}...", end=" ")
        _, err, rc = await celesto(["computer", "delete", name, "--yes"])
        print("OK" if rc == 0 else f"FAILED: {err.strip()}")

    print("Cleanup complete.")


if __name__ == "__main__":
    asyncio.run(main())
