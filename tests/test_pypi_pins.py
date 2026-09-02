from __future__ import annotations

import importlib.metadata
import pathlib
import sys

import pdx_artifact_core
import prodocux_kernel
import pytest

REQUIRED = {
    "prodocux": "0.3.0rc4",
    "pdx-artifact-engine": "0.3.0a4",
}

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _normalized(path: pathlib.Path) -> str:
    return str(path.resolve()).replace("\\", "/").lower()


def _is_under(path: pathlib.Path, root: pathlib.Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def test_installed_pypi_pins() -> None:
    for name, expected in REQUIRED.items():
        assert importlib.metadata.version(name) == expected


@pytest.mark.parametrize("module", [prodocux_kernel, pdx_artifact_core])
def test_modules_come_from_site_packages(module) -> None:
    path = pathlib.Path(module.__file__).resolve()
    assert "site-packages" in _normalized(path), path
    assert not _is_under(path, REPO_ROOT), path


def test_sys_path_does_not_include_local_product_checkouts() -> None:
    for item in sys.path:
        if not item:
            continue
        text = _normalized(pathlib.Path(item))
        if "site-packages" in text:
            continue
        trimmed = text.rstrip("/")
        if trimmed.endswith("/prodocux") or trimmed.endswith("/pdx-artifact-engine"):
            raise AssertionError(f"sys.path includes a local product checkout: {item}")
