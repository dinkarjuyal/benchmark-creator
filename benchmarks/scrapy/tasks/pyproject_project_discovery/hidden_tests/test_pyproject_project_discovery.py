import os
import sys
from pathlib import Path

from scrapy.utils.conf import closest_scrapy_cfg, get_config, init_env


def write_scrapy_cfg(path: Path, settings_module: str):
    path.write_text(f"[settings]\ndefault = {settings_module}\n", encoding="utf-8")


def write_pyproject(path: Path, default: str, custom: str | None = None):
    lines = ["[tool.scrapy.settings]", f'default = "{default}"']
    if custom is not None:
        lines.append(f'custom = "{custom}"')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_closest_config_finds_pyproject(tmp_path, monkeypatch):
    project = tmp_path / "project"
    nested = project / "src" / "demo"
    nested.mkdir(parents=True)
    pyproject = project / "pyproject.toml"
    write_pyproject(pyproject, "demo.settings", "demo.custom_settings")
    monkeypatch.chdir(nested)

    assert closest_scrapy_cfg() == str(pyproject.resolve())


def test_get_config_reads_pyproject_settings_section(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    write_pyproject(project / "pyproject.toml", "demo.settings", "demo.custom_settings")
    monkeypatch.chdir(project)

    cfg = get_config()

    assert cfg.has_option("settings", "default")
    assert cfg.get("settings", "default") == "demo.settings"
    assert cfg.get("settings", "custom") == "demo.custom_settings"


def test_init_env_prefers_pyproject_over_scrapy_cfg(tmp_path, monkeypatch):
    project = tmp_path / "project"
    nested = project / "pkg" / "demo"
    nested.mkdir(parents=True)
    write_scrapy_cfg(project / "scrapy.cfg", "legacy.settings")
    write_pyproject(project / "pyproject.toml", "pyproject.settings")
    monkeypatch.chdir(nested)
    monkeypatch.delenv("SCRAPY_SETTINGS_MODULE", raising=False)

    original_sys_path = list(sys.path)
    try:
        init_env()
        assert os.environ["SCRAPY_SETTINGS_MODULE"] == "pyproject.settings"
        assert str(project.resolve()) in sys.path
    finally:
        sys.path[:] = original_sys_path


def test_legacy_scrapy_cfg_still_works(tmp_path, monkeypatch):
    project = tmp_path / "legacy"
    nested = project / "pkg"
    nested.mkdir(parents=True)
    scrapy_cfg = project / "scrapy.cfg"
    write_scrapy_cfg(scrapy_cfg, "legacy.settings")
    monkeypatch.chdir(nested)
    monkeypatch.delenv("SCRAPY_SETTINGS_MODULE", raising=False)

    original_sys_path = list(sys.path)
    try:
        cfg = get_config()
        init_env()
        assert closest_scrapy_cfg() == str(scrapy_cfg.resolve())
        assert cfg.get("settings", "default") == "legacy.settings"
        assert os.environ["SCRAPY_SETTINGS_MODULE"] == "legacy.settings"
    finally:
        sys.path[:] = original_sys_path
