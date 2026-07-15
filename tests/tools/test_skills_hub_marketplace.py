# [yep-fork] Тесты для GitMarketplaceSource и whitelist источников в
# create_source_router (кастомизация форка: свой git-маркетплейс + скрытие
# публичных хабов из интерфейса с включением через config).
import json
import subprocess

import pytest

from tools.skills_hub import GitMarketplaceSource, create_source_router


def _git(cwd, *args):
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=cwd, check=True, capture_output=True, text=True,
    )


def _make_marketplace(root):
    """Собрать структуру claude-plugin marketplace и закоммитить."""
    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".claude-plugin" / "marketplace.json").write_text(
        json.dumps({
            "name": "test-mp",
            "plugins": [
                {"name": "demo", "source": "./demo", "description": "demo plugin"},
            ],
        }),
        encoding="utf-8",
    )
    skill = root / "demo" / "skills" / "hello"
    (skill / "references").mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: hello\ndescription: says hi to the world\n---\n\n"
        "See references/note.md for details.\n",
        encoding="utf-8",
    )
    (skill / "references" / "note.md").write_text("a note", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")


@pytest.fixture
def marketplace_url(tmp_path, monkeypatch):
    repo = tmp_path / "mp"
    repo.mkdir()
    _make_marketplace(repo)
    # клон-кэш источника уводим во временный HUB_DIR
    monkeypatch.setattr("tools.skills_hub.HUB_DIR", str(tmp_path / "hub"), raising=False)
    return f"file://{repo}"


class TestGitMarketplaceSource:
    def test_search_enumerates_plugin_skills(self, marketplace_url):
        src = GitMarketplaceSource([marketplace_url])
        metas = src.search("")
        names = {m.name for m in metas}
        assert "hello" in names
        m = next(m for m in metas if m.name == "hello")
        assert m.source == "marketplace"
        assert m.description == "says hi to the world"
        assert m.trust_level == "trusted"

    def test_query_filters(self, marketplace_url):
        src = GitMarketplaceSource([marketplace_url])
        assert src.search("world")          # совпадение по описанию
        assert src.search("hello")          # совпадение по имени
        assert src.search("zzz-nomatch") == []

    def test_fetch_bundles_skill_and_references(self, marketplace_url):
        src = GitMarketplaceSource([marketplace_url])
        m = next(m for m in src.search("") if m.name == "hello")
        bundle = src.fetch(m.identifier)
        assert bundle is not None
        assert "SKILL.md" in bundle.files
        assert "references/note.md" in bundle.files
        assert bundle.source == "marketplace"
        assert bundle.trust_level == "trusted"
        assert bundle.metadata.get("path") == "demo/skills/hello"

    def test_fetch_bad_identifier(self, marketplace_url):
        src = GitMarketplaceSource([marketplace_url])
        assert src.fetch("no-separator-here") is None

    def test_missing_repo_is_graceful(self, tmp_path, monkeypatch):
        monkeypatch.setattr("tools.skills_hub.HUB_DIR", str(tmp_path / "hub"), raising=False)
        src = GitMarketplaceSource([f"file://{tmp_path}/does-not-exist"])
        assert src.search("") == []


class TestSourceWhitelist:
    def test_default_shows_only_marketplace(self, monkeypatch):
        # конфиг пуст → hard-дефолт в коде: только "marketplace"
        monkeypatch.setattr("hermes_cli.config.load_config", lambda: {}, raising=False)
        ids = [s.source_id() for s in create_source_router()]
        assert ids == ["marketplace"]

    def test_config_can_reenable_public_hubs(self, monkeypatch):
        monkeypatch.setattr(
            "hermes_cli.config.load_config",
            lambda: {"skills": {"hub": {"enabled_sources": ["marketplace", "github", "official"]}}},
            raising=False,
        )
        ids = {s.source_id() for s in create_source_router()}
        assert ids == {"marketplace", "github", "official"}

    def test_empty_whitelist_hides_everything(self, monkeypatch):
        monkeypatch.setattr(
            "hermes_cli.config.load_config",
            lambda: {"skills": {"hub": {"enabled_sources": []}}},
            raising=False,
        )
        assert create_source_router() == []
