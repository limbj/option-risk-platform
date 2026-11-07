"""Build and start the local MVP with generated, untracked development secrets."""

import argparse
import os
import secrets
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*command):
    subprocess.run(command, cwd=ROOT, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-build", action="store_true")
    args = parser.parse_args()
    os.chdir(ROOT)
    uv = shutil.which("uv")
    if uv is None:
        local = ROOT / "work" / "bootstrap" / ("Scripts/uv.exe" if os.name == "nt" else "bin/uv")
        if not local.is_file():
            parser.error("Install uv 0.13.7 first; see README.md")
        uv = str(local)
    env_file = ROOT / ".env"
    if not env_file.exists():
        env_file.write_text(
            f"DJANGO_SECRET_KEY={secrets.token_urlsafe(64)}\n"
            "DJANGO_DEBUG=false\nLOCAL_DEMO_MODE=true\nDJANGO_ALLOWED_HOSTS=localhost,127.0.0.1\n"
            "POSTGRES_DB=option_risk\nPOSTGRES_USER=option_risk\n"
            f"POSTGRES_PASSWORD={secrets.token_urlsafe(32)}\n"
            "POSTGRES_HOST=127.0.0.1\nPOSTGRES_PORT=5432\n"
            f"DEMO_PASSWORD={secrets.token_urlsafe(20)}\n",
            encoding="utf-8",
        )
        print("Created local .env. Secrets are never printed or committed.")
    run(uv, "sync", "--locked", "--extra", "ml")
    invoke = [uv, "run", "--locked", "--extra", "ml", "--env-file", ".env", "python"]
    run("docker", "compose", "up", "-d", "--wait", "db", "redis")
    run(*invoke, "manage.py", "migrate")
    run(*invoke, "manage.py", "seed_demo")
    if not (ROOT / "artifacts/demo/manifest.json").exists():
        if not (ROOT / "artifacts/baseline/manifest.json").exists():
            run(
                *invoke,
                "-m",
                "ml.train",
                "--output",
                "artifacts/baseline",
                "--dataset",
                "data/demo.npz",
                "--samples",
                "16000",
                "--epochs",
                "350",
            )
        run(
            *invoke,
            "-m",
            "ml.evaluate",
            "--artifact",
            "artifacts/baseline",
            "--dataset",
            "data/demo.npz",
            "--gates",
            "docs/ml-demo-gates.json",
            "--output",
            "artifacts/demo",
        )
    run(
        *invoke,
        "manage.py",
        "register_artifact",
        "--directory",
        "artifacts/demo",
        "--name",
        "Heston MLP demo",
    )
    if not args.skip_build:
        run("docker", "compose", "build", "api", "web")
    run("docker", "compose", "up", "-d", "api", "worker", "dispatcher", "web")
    print("Local demo: http://127.0.0.1:5173 | opens directly in local demo mode")


if __name__ == "__main__":
    main()
