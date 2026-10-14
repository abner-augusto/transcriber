"""Every Job runs in a child process that imports `models` first; that import must stay light."""

import subprocess
import sys


def test_importing_models_does_not_load_torch_or_the_services_package():
    code = (
        "import sys, models\n"
        "heavy = [m for m in ('torch', 'services', 'engines') if m in sys.modules]\n"
        "assert not heavy, heavy\n"
    )

    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
