"""The vendored-runtime guard: a stale `build/py` can never be bundled again.

`scripts/vendor-python.sh` installs `backend/requirements.txt` into `build/py`,
and Tauri bundles that tree verbatim. The shipped app was built against a
`build/py` vendored *before* `phonenumberslite` entered requirements.txt, so
every contacts sync in the .app raised ImportError — the old hard-coded smoke
tuple never learned about the new dependency. `scripts/check_vendored_deps.py`
derives what must be installed from requirements.txt itself, so it cannot go
stale.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "check_vendored_deps.py"
REQUIREMENTS = REPO_ROOT / "backend" / "requirements.txt"

# The extras vendor-python.sh installs beyond requirements.txt (its EXTRA_DEPS).
EXTRA_DEPS = ("uvicorn[standard]", "cryptography", "keyring")


def _load_guard():
    spec = importlib.util.spec_from_file_location("check_vendored_deps", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guard = _load_guard()


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
    )


# ---- parsing requirements text ----------------------------------------------
SAMPLE = """\
# Scuffed OS backend
fastapi>=0.115.0
psycopg[binary,pool]>=3.2

Pydantic_Settings>=2.6.0   # inline comment
pyobjc-core>=10 ; sys_platform == "darwin"
phonenumberslite
"""


def test_parse_strips_extras_specifiers_markers_and_comments():
    assert guard.parse_requirement_names(SAMPLE) == [
        "fastapi",
        "psycopg",            # extras dropped: psycopg[binary,pool]
        "pydantic-settings",  # PEP 503 normalized
        "pyobjc-core",        # environment marker dropped
        "phonenumberslite",
    ]


@pytest.mark.parametrize(
    "name, expected",
    [
        ("Pydantic_Settings", "pydantic-settings"),
        ("python.dateutil", "python-dateutil"),
        ("Foo__Bar", "foo-bar"),
    ],
)
def test_parse_normalizes_names_to_pep503(name, expected):
    assert guard.parse_requirement_names(name) == [expected]


@pytest.mark.parametrize("line", ["-r other.txt", "-e .", "--no-binary :all:"])
def test_parse_rejects_option_lines(line):
    # Silently ignoring an option line would let unverified deps through.
    with pytest.raises(ValueError):
        guard.parse_requirement_names(line)


@pytest.mark.parametrize(
    "line",
    [
        "https://example.invalid/wheels/foo-1.0-py3-none-any.whl",
        "foo @ https://example.invalid/foo.tar.gz",
        "git+https://example.invalid/foo.git#egg=foo",
    ],
)
def test_parse_rejects_url_requirements(line):
    with pytest.raises(ValueError):
        guard.parse_requirement_names(line)


def test_real_requirements_parse_and_include_phonenumberslite():
    names = guard.parse_requirement_names(REQUIREMENTS.read_text())
    assert "phonenumberslite" in names
    assert "psycopg" in names
    assert "pydantic-settings" in names


# ---- distribution lookup -----------------------------------------------------
def _fake_dist(site_packages: Path, name: str, version: str = "1.0") -> None:
    info = site_packages / f"{name}-{version}.dist-info"
    info.mkdir(parents=True)
    (info / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"
    )


def test_missing_distributions_reports_only_the_absent_ones(tmp_path):
    site_packages = tmp_path / "site-packages"
    site_packages.mkdir()
    _fake_dist(site_packages, "Foo_Bar")

    missing = guard.missing_distributions(
        ["foo-bar", "missing"], str(site_packages)
    )

    assert missing == ["missing"]


def test_missing_distributions_matches_on_distribution_not_module(tmp_path):
    # phonenumberslite (the distribution) provides phonenumbers (the module).
    # The guard must look up the distribution, or it reports a false miss.
    site_packages = tmp_path / "site-packages"
    site_packages.mkdir()
    _fake_dist(site_packages, "phonenumberslite", "9.0.0")

    assert guard.missing_distributions(["phonenumberslite"], str(site_packages)) == []
    assert guard.missing_distributions(["phonenumbers"], str(site_packages)) == [
        "phonenumbers"
    ]


# ---- CLI ---------------------------------------------------------------------
def test_cli_fails_and_names_every_missing_distribution(tmp_path):
    site_packages = tmp_path / "site-packages"
    site_packages.mkdir()
    _fake_dist(site_packages, "fastapi")
    req = tmp_path / "requirements.txt"
    req.write_text("fastapi>=0.115.0\nphonenumberslite\n")

    result = _run_cli(
        "--requirements", str(req), "--site-packages", str(site_packages)
    )

    assert result.returncode == 1
    assert "phonenumberslite" in result.stderr
    assert "fastapi" not in result.stderr


def test_cli_is_silent_and_succeeds_when_every_requirement_is_installed(tmp_path):
    site_packages = tmp_path / "site-packages"
    site_packages.mkdir()
    _fake_dist(site_packages, "fastapi")
    _fake_dist(site_packages, "phonenumberslite")
    req = tmp_path / "requirements.txt"
    req.write_text("fastapi>=0.115.0\nphonenumberslite\n")

    result = _run_cli(
        "--requirements", str(req), "--site-packages", str(site_packages)
    )

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""


def test_cli_counts_extra_specs_that_are_not_in_the_requirements_file(tmp_path):
    site_packages = tmp_path / "site-packages"
    site_packages.mkdir()
    _fake_dist(site_packages, "fastapi")
    req = tmp_path / "requirements.txt"
    req.write_text("fastapi>=0.115.0\n")

    result = _run_cli(
        "--requirements", str(req),
        "--site-packages", str(site_packages),
        "--extra", "uvicorn[standard]",
    )

    assert result.returncode == 1
    assert "uvicorn" in result.stderr


def test_cli_rejects_a_requirements_file_it_cannot_verify(tmp_path):
    req = tmp_path / "requirements.txt"
    req.write_text("-r other.txt\n")

    result = _run_cli("--requirements", str(req), "--site-packages", str(tmp_path))

    assert result.returncode == 1
    assert "other.txt" in result.stderr


# ---- --python mode (what the build actually runs) ----------------------------
def test_cli_python_mode_passes_against_an_interpreter_with_every_dependency():
    # Any environment that can run this suite installed requirements-dev.txt,
    # which pulls in all of requirements.txt — so the real check must pass here.
    result = _run_cli(
        "--requirements", str(REQUIREMENTS),
        "--python", sys.executable,
        *[arg for spec in EXTRA_DEPS for arg in ("--extra", spec)],
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert result.stderr == ""


def test_cli_python_mode_reports_a_dependency_the_interpreter_lacks(tmp_path):
    req = tmp_path / "requirements.txt"
    req.write_text("fastapi>=0.115.0\nnot-a-real-distribution\n")

    result = _run_cli(
        "--requirements", str(req), "--python", sys.executable
    )

    assert result.returncode == 1
    assert "not-a-real-distribution" in result.stderr


def test_cli_fails_cleanly_when_the_interpreter_is_missing(tmp_path):
    result = _run_cli(
        "--requirements", str(REQUIREMENTS),
        "--python", str(tmp_path / "py" / "bin" / "python3"),
    )

    assert result.returncode == 1
    assert "python3" in result.stderr
    assert "Traceback" not in result.stderr


def test_smoke_modules_are_module_names_and_cover_phonenumbers():
    # The tuple holds MODULE names, not distribution names — the regression this
    # guard exists for is that `phonenumberslite` provides `phonenumbers`.
    assert "phonenumbers" in guard.MODULES
    for module in guard.MODULES:
        assert importlib.util.find_spec(module) is not None, module
