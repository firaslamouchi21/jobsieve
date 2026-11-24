import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_readme_links_work_on_pypi_and_point_at_real_files():
    with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as f:
        targets = re.findall(r"\]\(([^)\s]+)\)", f.read())
    assert targets
    for target in targets:
        assert target.startswith(("https://", "http://", "#")), target
        local = re.match(r"https://(?:github\.com/firaslamouchi21/jobsieve/blob|raw\.githubusercontent\.com/firaslamouchi21/jobsieve)/main/(.+)", target)
        assert not local or os.path.exists(os.path.join(ROOT, local[1])), target
