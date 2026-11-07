"""The input contracts and ML package entry point need only the Python stdlib."""

import os
import subprocess
import sys
from pathlib import Path


def test_financial_contracts_import_without_django_or_site_packages():
    project_root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment.pop("DJANGO_SETTINGS_MODULE", None)
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-c",
            "import sys; sys.path.insert(0, sys.argv[1]); "
            "import quant, quant.contracts, quant.conventions, quant.inputs, ml; "
            "assert not {'django', 'rest_framework', 'torch', 'QuantLib'} & sys.modules.keys()",
            str(project_root / "src"),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert result.returncode == 0, result.stderr
