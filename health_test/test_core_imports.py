import subprocess
import sys

HEAVY = ("fastapi", "uvicorn", "streamlit", "playwright", "anthropic")


def modules_loaded_by(statement: str) -> set[str]:
    code = (
        "import sys\n"
        f"{statement}\n"
        "print(' '.join(sorted({m.split('.')[0] for m in sys.modules})))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    return set(out.stdout.split())


class TestLightCore:

    def test_pipeline_and_cli_do_not_import_heavy_packages(self):
        loaded = modules_loaded_by("import jobsieve.cli, jobsieve.scraper, jobsieve.db")
        assert not loaded & set(HEAVY)

    def test_scoring_does_not_import_anthropic_until_used(self):
        loaded = modules_loaded_by("import jobsieve.ai_service")
        assert "anthropic" not in loaded


class TestBackwardCompatibleAppPath:

    def test_old_scraper_api_path_still_resolves(self):
        from jobsieve import scraper
        from jobsieve.api import api

        assert scraper.api is api
