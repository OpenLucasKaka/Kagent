from pathlib import Path


def test_github_actions_ci_runs_standard_check_script():
    workflow_path = Path(".github/workflows/ci.yml")
    workflow = workflow_path.read_text()

    assert workflow_path.exists()
    assert "scripts/run_checks.sh" in workflow
    assert "pip install -e '.[dev]'" in workflow


def test_github_actions_ci_installs_node_dependencies():
    workflow = Path(".github/workflows/ci.yml").read_text()

    assert "actions/setup-node@v4" in workflow
    assert "node-version: ${{ matrix.node-version }}" in workflow
    assert "cache: npm" in workflow
    assert "npm ci" in workflow


def test_github_actions_ci_uses_minimal_permissions():
    workflow = Path(".github/workflows/ci.yml").read_text()

    assert "permissions:" in workflow
    assert "contents: read" in workflow


def test_github_actions_ci_runs_python_version_matrix():
    workflow = Path(".github/workflows/ci.yml").read_text()

    assert "matrix:" in workflow
    assert "include:" in workflow
    assert 'python-version: "3.9"' in workflow
    assert "node-version: 18" in workflow
    assert 'python-version: "3.12"' in workflow
    assert "node-version: 22" in workflow
    assert "python-version: ${{ matrix.python-version }}" in workflow


def test_npm_release_runs_only_for_successful_main_push_from_this_repository():
    workflow = Path(".github/workflows/release.yml").read_text()

    assert "workflow_run:" in workflow
    assert 'workflows: ["CI"]' in workflow
    assert "types: [completed]" in workflow
    assert "github.event.workflow_run.conclusion == 'success'" in workflow
    assert "github.event.workflow_run.event == 'push'" in workflow
    assert "github.event.workflow_run.head_branch == 'main'" in workflow
    assert "github.event.workflow_run.head_repository.full_name == github.repository" in workflow


def test_npm_release_checks_out_the_exact_ci_commit_with_minimal_permissions():
    workflow = Path(".github/workflows/release.yml").read_text()

    assert "permissions:\n  contents: read" in workflow
    assert "uses: actions/checkout@v4" in workflow
    assert "ref: ${{ github.event.workflow_run.head_sha }}" in workflow
    assert "contents: write" not in workflow


def test_npm_release_verifies_build_and_package_versions_before_publish():
    workflow = Path(".github/workflows/release.yml").read_text()

    assert "npm ci" in workflow
    assert "npm run build" in workflow
    assert "npm run check" in workflow
    assert "npm pack --dry-run --json" in workflow
    assert "package_version != python_version" in workflow
    assert 'npm view "${PACKAGE_NAME}@${VERSION}" version' in workflow


def test_npm_release_is_idempotent_and_uses_semver_distribution_tags():
    workflow = Path(".github/workflows/release.yml").read_text()

    assert "already-published=true" in workflow
    assert "steps.registry.outputs.already-published != 'true'" in workflow
    assert "*-*) TAG=next" in workflow
    assert "TAG=latest" in workflow
    assert "NODE_AUTH_TOKEN: ${{ secrets.NPM_TOKEN }}" in workflow
    assert 'npm publish --access public --tag "$TAG"' in workflow
    assert "npm version" not in workflow
    assert "git commit" not in workflow
    assert "git push" not in workflow


def test_github_actions_ci_has_job_timeout():
    workflow = Path(".github/workflows/ci.yml").read_text()

    assert "timeout-minutes:" in workflow


def test_github_actions_ci_uploads_wheel_artifact():
    workflow = Path(".github/workflows/ci.yml").read_text()

    assert "actions/upload-artifact" in workflow
    assert "kagent-wheel-${{ matrix.python-version }}" in workflow
    assert "/tmp/kagent-wheelhouse" in workflow
    assert "retention-days: 14" in workflow


def test_github_actions_ci_uploads_release_manifest_artifact():
    workflow = Path(".github/workflows/ci.yml").read_text()

    assert "kagent-release-manifest-${{ matrix.python-version }}" in workflow
    assert "/tmp/kagent-release-manifest.json" in workflow
    assert "if-no-files-found: error" in workflow
    assert workflow.count("retention-days: 14") == 2


def test_dependabot_tracks_python_and_github_actions_dependencies():
    dependabot_path = Path(".github/dependabot.yml")
    dependabot = dependabot_path.read_text()

    assert dependabot_path.exists()
    assert 'package-ecosystem: "pip"' in dependabot
    assert 'package-ecosystem: "github-actions"' in dependabot
    assert "interval: weekly" in dependabot
