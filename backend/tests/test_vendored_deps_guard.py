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
import warnings
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "check_vendored_deps.py"
REQUIREMENTS = REPO_ROOT / "backend" / "requirements.txt"

# Verbatim from the installed psycopg 3.3.4 METADATA: the `binary` extra is
# a separate distribution behind a compound marker, `test` must stay ignored,
# and the last entry is an unconditional dependency with no marker at all.
PSYCOPG_REQUIRES = (
    'psycopg-binary==3.3.4; implementation_name != "pypy" and extra == "binary"',
    'psycopg-pool; extra == "pool"',
    'pytest>=6.2.5; extra == "test"',
    "typing-extensions>=4.6",
)


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
def _fake_dist(
    site_packages: Path,
    name: str,
    version: str = "1.0",
    requires: tuple[str, ...] = (),
) -> None:
    info = site_packages / f"{name}-{version}.dist-info"
    info.mkdir(parents=True)
    lines = ["Metadata-Version: 2.1", f"Name: {name}", f"Version: {version}"]
    lines += [f"Requires-Dist: {spec}" for spec in requires]
    (info / "METADATA").write_text("\n".join(lines) + "\n")


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


def test_missing_distributions_ignores_a_dist_info_without_a_name(tmp_path):
    # A .dist-info with no Name: (or no METADATA at all) must be skipped
    # quietly: `metadata["Name"]` warns on 3.14 and will raise KeyError later,
    # and a build-gating script cannot print on its success path.
    site_packages = tmp_path / "site-packages"
    site_packages.mkdir()
    _fake_dist(site_packages, "fastapi")
    nameless = site_packages / "broken-1.0.dist-info"
    nameless.mkdir()
    (nameless / "METADATA").write_text("Metadata-Version: 2.1\nVersion: 1.0\n")
    (site_packages / "nometa-1.0.dist-info").mkdir()

    with warnings.catch_warnings():
        warnings.simplefilter("error")  # the deprecation becomes a KeyError later
        assert guard.missing_distributions(["fastapi"], str(site_packages)) == []


# ---- extras are separate distributions ---------------------------------------
def test_parse_requirements_keeps_the_extras_alongside_the_base_name():
    assert guard.parse_requirements("psycopg[Binary, pool]>=3.2\nfastapi\n") == [
        ("psycopg", ("binary", "pool")),
        ("fastapi", ()),
    ]


def test_missing_extra_distributions_demands_what_an_extra_installs(tmp_path):
    # psycopg[binary] installs psycopg AND psycopg-binary. Without the latter
    # `import psycopg` still succeeds — the app only dies at the first connect,
    # which is precisely the class of miss this guard exists to catch.
    site_packages = tmp_path / "site-packages"
    site_packages.mkdir()
    _fake_dist(site_packages, "psycopg", "3.3.4", requires=PSYCOPG_REQUIRES)
    _fake_dist(site_packages, "psycopg-pool", "3.3.1")

    missing = guard.missing_extra_distributions(
        [("psycopg", ("binary", "pool"))], str(site_packages)
    )

    assert missing == ["psycopg-binary"]


def test_missing_extra_distributions_ignores_extras_nobody_asked_for(tmp_path):
    # psycopg declares pytest under its `test` extra and typing-extensions with
    # no marker; neither may be demanded of the vendored tree.
    site_packages = tmp_path / "site-packages"
    site_packages.mkdir()
    _fake_dist(site_packages, "psycopg", "3.3.4", requires=PSYCOPG_REQUIRES)
    _fake_dist(site_packages, "psycopg-pool", "3.3.1")

    assert guard.missing_extra_distributions(
        [("psycopg", ("pool",))], str(site_packages)
    ) == []


def test_missing_extra_distributions_respects_platform_gating(tmp_path):
    # Verbatim shapes from uvicorn's `standard` extra. colorama is Windows-only
    # and legitimately absent from a macOS-arm64 tree; uvloop is gated the other
    # way and is a compiled dependency we must keep demanding.
    site_packages = tmp_path / "site-packages"
    site_packages.mkdir()
    _fake_dist(
        site_packages,
        "uvicorn",
        "0.51.0",
        requires=(
            "colorama>=0.4; sys_platform == 'win32' and extra == 'standard'",
            "uvloop>=0.15.1; sys_platform != 'win32' and extra == 'standard'",
        ),
    )

    missing = guard.missing_extra_distributions(
        [("uvicorn", ("standard",))], str(site_packages)
    )

    assert missing == ["uvloop"]


def test_missing_extra_distributions_skips_a_requirement_whose_base_is_absent(tmp_path):
    # The absent base is already reported by missing_distributions; resolving
    # its extras is impossible and would only add noise.
    site_packages = tmp_path / "site-packages"
    site_packages.mkdir()

    assert guard.missing_extra_distributions(
        [("psycopg", ("binary",))], str(site_packages)
    ) == []


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


def test_cli_reports_an_extras_distribution_the_tree_lacks(tmp_path):
    site_packages = tmp_path / "site-packages"
    site_packages.mkdir()
    _fake_dist(site_packages, "psycopg", "3.3.4", requires=PSYCOPG_REQUIRES)
    req = tmp_path / "requirements.txt"
    req.write_text("psycopg[binary,pool]>=3.2\n")

    result = _run_cli(
        "--requirements", str(req), "--site-packages", str(site_packages)
    )

    assert result.returncode == 1
    # The base distribution is present, so only the two extras are reported.
    assert result.stderr.splitlines() == [
        "missing extra distribution: psycopg-binary",
        "missing extra distribution: psycopg-pool",
    ]


def test_cli_stays_silent_when_a_dist_info_has_no_name(tmp_path):
    site_packages = tmp_path / "site-packages"
    site_packages.mkdir()
    _fake_dist(site_packages, "fastapi")
    nameless = site_packages / "broken-1.0.dist-info"
    nameless.mkdir()
    (nameless / "METADATA").write_text("Metadata-Version: 2.1\nVersion: 1.0\n")
    req = tmp_path / "requirements.txt"
    req.write_text("fastapi\n")

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
    # which is `-r requirements.txt` — so the real check must pass here, extras
    # included: requirements.txt asks for psycopg[binary,pool], so this also
    # proves the extras resolution works against a real installed tree.
    # No --extra here: vendor-python.sh's uvicorn[standard] is a packaging-only
    # dependency that dev/CI environments do not install.
    result = _run_cli(
        "--requirements", str(REQUIREMENTS),
        "--python", sys.executable,
        "--extra", "cryptography",
        "--extra", "keyring",
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


# ---- the interpreter subprocesses are isolated and write no bytecode ---------
def test_import_smoke_ignores_a_module_supplied_only_by_pythonpath(tmp_path, monkeypatch):
    """The smoke must audit the TREE, not the shell that runs the build.

    A PYTHONPATH (or a user site-packages) carrying a stub of a missing
    dependency made the smoke pass against a tree that does not have it — the
    guard would then bless an .app that raises ImportError on the user's Mac. The
    probe therefore runs isolated (`-I`), so an injected path is invisible.
    """
    stub_dir = tmp_path / "injected"
    stub_dir.mkdir()
    (stub_dir / "stub_only_via_pythonpath.py").write_text("VALUE = 1\n")
    monkeypatch.setenv("PYTHONPATH", str(stub_dir))
    monkeypatch.setattr(guard, "MODULES", ("stub_only_via_pythonpath",))

    # sanity: the stub really is importable for a NON-isolated interpreter
    reachable = subprocess.run(
        [sys.executable, "-c", "import stub_only_via_pythonpath"],
        capture_output=True, text=True,
    )
    assert reachable.returncode == 0, reachable.stderr

    assert guard._failed_imports(sys.executable) == ["stub_only_via_pythonpath"]


def test_interpreter_probes_run_isolated_and_write_no_bytecode(monkeypatch):
    """Both interpreter subprocesses pass `-I` (ignore PYTHONPATH/PYTHONHOME/user
    site) and `-B` (write no .pyc). Without `-B` every run re-creates the
    `__pycache__` directories vendor-python.sh prunes — inside the .app, in the
    [6b/7] check that runs immediately before signing."""
    import types

    calls: list[list[str]] = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(guard, "subprocess", types.SimpleNamespace(
        run=fake_run, CalledProcessError=subprocess.CalledProcessError))

    guard._purelib("/fake/py/bin/python3")
    guard._failed_imports("/fake/py/bin/python3")

    assert len(calls) == 2
    for argv in calls:
        assert argv[0] == "/fake/py/bin/python3"
        assert argv[1:3] == ["-I", "-B"]
        assert argv[3] == "-c"


def test_smoke_modules_are_module_names_and_cover_phonenumbers():
    # The tuple holds MODULE names, not distribution names — the regression this
    # guard exists for is that `phonenumberslite` provides `phonenumbers`.
    assert "phonenumbers" in guard.MODULES
    for module in guard.MODULES:
        assert importlib.util.find_spec(module) is not None, module
