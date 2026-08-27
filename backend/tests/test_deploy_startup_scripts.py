from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


def test_rag_worker_installs_docling_native_runtime_dependencies() -> None:
    dockerfile = (
        Path(__file__).parents[2] / "deploy" / "rag-worker.Dockerfile"
    ).read_text(encoding="utf-8")

    for package in ("libgl1", "libglib2.0-0", "libx11-6", "libxext6", "libsm6", "libice6", "libxcb1"):
        assert package in dockerfile
    assert "rm -rf /var/lib/apt/lists/*" in dockerfile
    assert dockerfile.index("pip install") < dockerfile.index("apt-get install")


@pytest.mark.skipif(shutil.which("sh") is None, reason="POSIX shell is required to execute up.sh")
def test_posix_startup_replaces_empty_query_proxy_token(tmp_path) -> None:
    shell = shutil.which("sh")
    assert shell is not None
    project = tmp_path / "project"
    deploy = project / "deploy"
    scripts = deploy / "scripts"
    scripts.mkdir(parents=True)
    source = Path(__file__).parents[2] / "deploy" / "scripts" / "up.sh"
    shutil.copy2(source, scripts / "up.sh")
    (deploy / ".env").write_text(
        "\n".join(
            (
                "POSTGRES_PASSWORD=test-database-password",
                "JWT_SECRET_KEY=test-jwt-secret-with-at-least-32-characters",
                "ADMIN_PASSWORD=test-admin-password",
                "RAG_QUERY_EMBEDDING_TOKEN=",
            )
        ),
        encoding="utf-8",
    )

    binaries = tmp_path / "bin"
    binaries.mkdir()
    (binaries / "openssl").write_text(
        "#!/usr/bin/env sh\nprintf '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef\\n'\n",
        encoding="utf-8",
    )
    (binaries / "docker").write_text("#!/usr/bin/env sh\nexit 0\n", encoding="utf-8")
    os.chmod(binaries / "openssl", 0o755)
    os.chmod(binaries / "docker", 0o755)
    environment = os.environ.copy()
    environment["PATH"] = f"{binaries}{os.pathsep}{environment['PATH']}"

    subprocess.run(
        [shell, str(scripts / "up.sh")],
        cwd=deploy,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    lines = (deploy / ".env").read_text(encoding="utf-8").splitlines()
    tokens = [line for line in lines if line.startswith("RAG_QUERY_EMBEDDING_TOKEN=")]
    assert tokens == [
        "RAG_QUERY_EMBEDDING_TOKEN="
        "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
    ]
