"""The Server image workflow publishes only an image that passed, and only
when a person published a release. The smoke run it relies on starts a
person's compose.yaml as it is, and can never reach a real installation.

The workflow is read as text, since the Python that runs this suite may
have no YAML parser. Each job is the block of lines under its name.
"""
import re
import subprocess
import sys
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1]
REPO = SERVER.parent
WORKFLOW = REPO / ".github" / "workflows" / "server-image.yml"

sys.path.insert(0, str(SERVER))
import smoke  # noqa: E402


def workflow() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def jobs() -> dict:
    out, name = {}, None
    for line in workflow().split("\njobs:\n", 1)[1].splitlines():
        m = re.match(r"^  ([\w-]+):\s*$", line)
        if m:
            name = m.group(1)
            out[name] = []
        elif line.strip() and not line.startswith(" "):
            break
        elif name:
            out[name].append(line)
    return {k: "\n".join(v) for k, v in out.items()}


def test_it_runs_on_every_change_and_on_a_published_release():
    on = workflow().split("\non:\n", 1)[1].split("\n\n", 1)[0]
    for event in ("push:", "pull_request:", "release:"):
        assert event in on
    assert "types: [published]" in on


def test_only_the_publish_job_can_write_a_package():
    assert {name: "packages: write" in block for name, block in jobs().items()} \
        == {"image": False, "publish": True}
    assert "packages: write" not in workflow().split("\njobs:\n", 1)[0]


def test_the_publish_job_runs_only_for_a_release_and_after_the_image_passed():
    block = jobs()["publish"]
    assert "if: github.event_name == 'release'" in block
    assert "needs: image" in block


def test_nothing_signs_in_to_the_registry_or_pushes_but_the_publish_job():
    for name, block in jobs().items():
        if name != "publish":
            assert "docker push" not in block and "docker login" not in block, name


def test_what_is_published_is_what_was_tested():
    image, publish = jobs()["image"], jobs()["publish"]
    assert image.index("server/build.py") < image.index("server/smoke.py") < image.index("docker save")
    assert "download-artifact" in publish
    assert "docker build" not in publish and "build.py" not in publish


def test_a_prerelease_leaves_latest_where_it_was():
    assert re.search(r'if \[ "\$PRERELEASE" != "true" \]; then\s+docker tag [^\n]*:latest',
                     jobs()["publish"])


def test_the_image_names_this_repository_as_its_source():
    """The source label is what links a published image to the repository
    on GitHub's registry, and the license is the repository's own."""
    dockerfile = (SERVER / "Dockerfile").read_text(encoding="utf-8")
    assert 'org.opencontainers.image.source="https://github.com/rheeloaded/paperpull"' in dockerfile
    assert 'org.opencontainers.image.licenses="AGPL-3.0-only"' in dockerfile
    assert 'license = { text = "AGPL-3.0-only" }' in (REPO / "core" / "pyproject.toml").read_text(encoding="utf-8")


def test_compose_names_the_image_the_workflow_publishes():
    compose_file = (SERVER / "compose.yaml").read_text(encoding="utf-8")
    assert re.search(r"^    image: ghcr\.io/rheeloaded/paperpull-server:latest$", compose_file, re.M)
    assert 'image="ghcr.io/${OWNER,,}/paperpull-server"' in jobs()["publish"]


def test_the_smoke_run_starts_a_persons_compose_file_as_it_is(tmp_path):
    smoke.write_project(tmp_path, "some/image:tag")
    for name in ("compose.yaml", "seccomp-chrome.json"):
        assert (tmp_path / name).read_bytes() == (SERVER / name).read_bytes(), name
    override = (tmp_path / "compose.smoke.yaml").read_text(encoding="utf-8")
    keys = set(re.findall(r"^\s*([\w-]+):", override, re.M))
    assert keys <= {"services", "paperpull", "image", "container_name", "environment",
                    "PUID", "PGID"}, keys
    assert "image: some/image:tag" in override
    assert "container_name: %s" % smoke.CONTAINER in override


def test_taking_the_smoke_run_down_can_only_reach_its_own_project(tmp_path, monkeypatch):
    """`down -v` deletes the project's volumes, and a real installation's
    hold its live sign-ins. So the smoke run's project and container have
    names of their own, and every compose command names the project."""
    assert smoke.PROJECT != "paperpull" and smoke.CONTAINER != "paperpull"
    assert re.search(r"^name: paperpull$", (SERVER / "compose.yaml").read_text(encoding="utf-8"), re.M)
    seen = []

    def run(cmd, **kwargs):
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(smoke.subprocess, "run", run)
    smoke.compose(tmp_path, "down", "-v", "--remove-orphans")
    assert seen and seen[0][:4] == ["docker", "compose", "-p", smoke.PROJECT]
    source = (SERVER / "smoke.py").read_text(encoding="utf-8")
    assert source.count('"compose"') == 1, "compose is run somewhere other than compose()"
