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
    # docker buildx imagetools only reads the registry, a build is refused.
    assert not re.search(r"docker\s+(buildx\s+)?build\s", publish) and "build.py" not in publish


def test_an_action_from_outside_github_is_named_by_its_commit():
    """Whoever holds an action can move its tag to other code, and the
    image job runs with the tested image in reach. A commit cannot move."""
    refs = re.findall(r"uses:\s*(\S+)", workflow())
    outside = [r for r in refs if not r.startswith("actions/")]
    assert outside, refs
    for ref in outside + [r for r in refs if r.startswith("actions/attest@")]:
        assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", ref), ref


def test_the_tested_image_is_listed_and_scanned_before_it_is_kept():
    image = jobs()["image"]
    assert (image.index("server/smoke.py") < image.index("anchore/sbom-action@")
            < image.index("anchore/scan-action@") < image.index("docker save"))
    assert "image: paperpull-server:dev" in image
    assert "output-file: paperpull-server.spdx.json" in image
    assert "sbom: paperpull-server.spdx.json" in image
    assert "fail-build: true" in image and "severity-cutoff: critical" in image
    # The image job may not write, and Syft's action adds to a release
    # unless told not to.
    assert "upload-release-assets: false" in image
    assert "name: paperpull-server-sbom" in image


def test_a_release_signs_the_list_for_the_digest_it_pushed():
    publish = jobs()["publish"]
    assert "name: paperpull-server-sbom" in publish
    assert publish.count("uses: actions/attest@") == 2
    assert publish.count("sbom-path: paperpull-server.spdx.json") == 1
    assert publish.count("subject-digest: ${{ steps.push.outputs.digest }}") == 2
    assert publish.count("push-to-registry: true") == 2
    # latest moves only to an image already signed, so a failed signing
    # leaves it where it was.
    assert (publish.index('docker push "$image:$version"') < publish.index("--format '{{.Manifest.Digest}}'")
            < publish.index("actions/attest@") < publish.rindex("actions/attest@")
            < publish.index('docker push "$image:latest"') < publish.index("docker logout"))


def test_the_list_s_size_is_checked_before_a_release_needs_it():
    """actions/attest refuses a list over 16 MB, by then after the push."""
    image = jobs()["image"]
    assert (image.index("anchore/sbom-action@") < image.index("stat -c %s paperpull-server.spdx.json")
            < image.index("docker save"))
    assert re.search(r'test "\$size" -lt 1[0-6]\d{6}\b', image)


def test_the_weekly_run_scans_again_and_names_a_moved_base():
    on = workflow().split("\non:\n", 1)[1].split("\n\n", 1)[0]
    assert re.search(r'schedule:\s+- cron: "[^"]+"', on)
    steps = re.split(r"\n      - ", jobs()["image"])
    check = [s for s in steps if "python server/lock.py --base --check" in s]
    assert len(check) == 1 and "if: github.event_name == 'schedule'" in check[0]
    assert '["--base", "--check"]' in (SERVER / "lock.py").read_text(encoding="utf-8")
    assert "if: github.event_name == 'release'" in jobs()["publish"]


def test_only_the_publish_job_can_sign():
    assert {name: "id-token: write" in block for name, block in jobs().items()} \
        == {"image": False, "publish": True}
    assert "id-token" not in workflow().split("\njobs:\n", 1)[0]


def test_dependabot_proposes_the_base_s_new_digest_and_never_another_python():
    """server/lock.py resolves the lock in one Python, so a weekly proposal
    may bring the tag's newer digest and nothing more."""
    text = (REPO / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    docker = text.split("package-ecosystem: docker", 1)[1].split("package-ecosystem:", 1)[0]
    assert "directory: /server" in docker
    assert "dependency-name: python" in docker
    assert 'update-types: ["version-update:semver-major", "version-update:semver-minor"]' in docker
    assert "package-ecosystem: pip" not in text
    actions = text.split("package-ecosystem: github-actions", 1)[1]
    assert 'update-types: ["version-update:semver-major"]' in actions


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
    """By this release's version, never latest, so a person's server moves
    to another version only when they write it. The release's zip carries
    compose.yaml from its tag, so the version commit raises both."""
    version = (REPO / "VERSION").read_text(encoding="utf-8").strip()
    for name in ("compose.yaml", "compose.https.yaml"):
        compose_file = (SERVER / name).read_text(encoding="utf-8")
        images = [image for image in re.findall(r"^    image: (\S+)$", compose_file, re.M)
                  if not image.startswith("caddy:")]
        assert images == ["ghcr.io/rheeloaded/paperpull-server:%s" % version], \
            "server/%s names %s, write the image of version %s there" % (name, images, version)
    assert 'image="ghcr.io/${OWNER,,}/paperpull-server"' in jobs()["publish"]
    assert 'docker push "$image:$version"' in jobs()["publish"]


def test_the_smoke_run_starts_a_persons_compose_file_as_it_is(tmp_path):
    smoke.write_project(tmp_path, "some/image:tag")
    for name in ("compose.yaml", "compose.https.yaml", "Caddyfile", "seccomp-chrome.json"):
        assert (tmp_path / name).read_bytes() == (SERVER / name).read_bytes(), name
    override = (tmp_path / "compose.smoke.yaml").read_text(encoding="utf-8")
    keys = set(re.findall(r"^\s*([\w-]+):", override, re.M))
    assert keys <= {"services", "paperpull", "image", "container_name", "environment",
                    "PUID", "PGID"}, keys
    assert "image: some/image:tag" in override
    assert "container_name: %s" % smoke.CONTAINER in override
    # The HTTPS file as a person fills it in, with this computer's name and
    # address, and nothing else changed.
    override = (tmp_path / "compose.https.smoke.yaml").read_text(encoding="utf-8")
    keys = set(re.findall(r"^\s*([\w-]+):", override, re.M))
    assert keys <= {"services", "paperpull", "proxy", "image", "container_name", "environment",
                    "PUID", "PGID", "PAPERPULL_HOSTS", "PAPERPULL_ADDRESS", "PAPERPULL_NAMES"}, keys
    assert "image: some/image:tag" in override
    assert "container_name: %s" % smoke.CONTAINER in override
    assert "container_name: %s" % smoke.PROXY in override


def test_taking_the_smoke_run_down_can_only_reach_its_own_project(tmp_path, monkeypatch):
    """`down -v` deletes the project's volumes, and a real installation's
    hold its live sign-ins. So the smoke run's project and container have
    names of their own, and every compose command names the project."""
    assert smoke.PROJECT != "paperpull" and smoke.CONTAINER != "paperpull"
    assert smoke.PROXY not in (smoke.CONTAINER, "paperpull-proxy")
    for name in ("compose.yaml", "compose.https.yaml"):
        assert re.search(r"^name: paperpull$", (SERVER / name).read_text(encoding="utf-8"), re.M)
    seen = []

    def run(cmd, **kwargs):
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(smoke.subprocess, "run", run)
    smoke.compose(tmp_path, "down", "-v", "--remove-orphans")
    smoke.compose(tmp_path, "down", "-v", "--remove-orphans", https=True)
    assert len(seen) == 2 and all(cmd[:4] == ["docker", "compose", "-p", smoke.PROJECT]
                                  for cmd in seen)
    assert str(tmp_path / "compose.https.yaml") in seen[1]
    source = (SERVER / "smoke.py").read_text(encoding="utf-8")
    assert source.count('"compose"') == 1, "compose is run somewhere other than compose()"


def test_the_smoke_run_turns_on_the_setuid_sandbox_as_a_person_does():
    """Only the # comes off the SYS_ADMIN line SERVER.md names and goes in
    front of the panel's no-new-privileges line, never Caddy's, nothing else
    in the file changes, and a file without them is not run at all. Left
    with no-new-privileges, as a person might, only the SYS_ADMIN line
    changes."""
    for name in ("compose.yaml", "compose.https.yaml"):
        text = (SERVER / name).read_text(encoding="utf-8")
        before, after = text.splitlines(), smoke.with_setuid_sandbox(text).splitlines()
        assert len(before) == len(after), name
        assert [(a, b) for a, b in zip(before, after) if a != b] == [
            ("      - no-new-privileges:true", "      #- no-new-privileges:true"),
            ("      #- SYS_ADMIN", "      - SYS_ADMIN")], name
        missed = smoke.with_setuid_sandbox(text, keep_no_new_privileges=True).splitlines()
        assert [(a, b) for a, b in zip(before, missed) if a != b] == [
            ("      #- SYS_ADMIN", "      - SYS_ADMIN")], name
        # A Windows checkout's line endings come through as they were.
        crlf = text.replace("\n", "\r\n")
        assert smoke.with_setuid_sandbox(crlf).count("\r\n") == crlf.count("\r\n"), name
    # Caddy keeps its own no-new-privileges.
    https = smoke.with_setuid_sandbox((SERVER / "compose.https.yaml").read_text(encoding="utf-8"))
    proxy = https[https.index("\n  proxy:"):]
    assert "      - no-new-privileges:true" in proxy.splitlines()
    assert smoke.with_setuid_sandbox("services:\n  paperpull:\n") == ""
