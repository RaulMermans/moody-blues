"""Reads an agent's manifest and packs what goes into its sandbox.

No host path may be mounted into a sandbox, so the code travels the only way in there is: over
stdin, as one zip that holds the agent's package and the SDK. The zip is deterministic, so its hash
identifies what ran.
"""

from __future__ import annotations

import hashlib
import io
import struct
import tomllib
import zipfile
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from moody_blues.contracts.adapter import (
    ADAPTER_PROTOCOL,
    MAX_BUNDLE_BYTES,
    AgentManifest,
)

SDK_PACKAGE = "moody_blues_sdk"
SDK_ROOT = Path(__file__).resolve().parents[3] / "sdk" / "python" / SDK_PACKAGE
_ZIP_EPOCH = (2026, 1, 1, 0, 0, 0)
_SHIPPED_SUFFIXES = frozenset({".py", ".json", ".toml", ".txt"})

# Reads the bundle from stdin, then hands the same stream to the SDK. It runs in the sandbox, so it
# is a convenience and not a control: everything the agent does afterwards is checked by the host.
_BOOTSTRAP = """\
import os, struct, sys
stream = sys.stdin.buffer
size = struct.unpack(">I", stream.read(4))[0]
path = os.path.abspath("agent-bundle.zip")
with open(path, "wb") as f:
    f.write(stream.read(size))
sys.path.insert(0, path)
from moody_blues_sdk.runtime import main
main({entrypoint!r}, stream)
"""


class ManifestError(ValueError):
    """The manifest or the package it names cannot be used. Says which, and never guesses."""


@dataclass(frozen=True, slots=True)
class AgentBundle:
    manifest: AgentManifest
    manifest_sha256: str
    archive: bytes
    sha256: str

    @property
    def bootstrap(self) -> str:
        return _BOOTSTRAP.format(entrypoint=self.manifest.entrypoint)

    @property
    def frame(self) -> bytes:
        """Length-prefixed archive, as the bootstrap reads it."""
        return struct.pack(">I", len(self.archive)) + self.archive


def _files(root: Path, arc_prefix: str) -> list[tuple[str, bytes]]:
    found: list[tuple[str, bytes]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ManifestError(f"{path.name}: symbolic links are not bundled")
        if path.is_file() and path.suffix in _SHIPPED_SUFFIXES and "__pycache__" not in path.parts:
            name = f"{arc_prefix}/{path.relative_to(root).as_posix()}"
            found.append((name, path.read_bytes()))
    return found


def _archive(files: list[tuple[str, bytes]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files):
            info = zipfile.ZipInfo(name, date_time=_ZIP_EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    return buffer.getvalue()


def load_manifest(path: Path) -> tuple[AgentManifest, str]:
    try:
        raw = path.read_bytes()
        manifest = AgentManifest.model_validate(tomllib.loads(raw.decode("utf-8")))
    except OSError as exc:
        raise ManifestError(f"cannot read {path.name}") from exc
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ManifestError(f"{path.name} is not valid TOML") from exc
    except ValidationError as exc:
        bad = sorted({".".join(str(p) for p in e["loc"]) for e in exc.errors()})
        raise ManifestError(f"{path.name}: invalid fields: {', '.join(bad)}") from exc
    if manifest.protocol != ADAPTER_PROTOCOL:
        raise ManifestError(f"{path.name}: protocol must be {ADAPTER_PROTOCOL}")
    return manifest, hashlib.sha256(raw).hexdigest()


def build_bundle(manifest_path: Path) -> AgentBundle:
    manifest, manifest_sha256 = load_manifest(manifest_path)
    if manifest.package == SDK_PACKAGE:
        raise ManifestError(f"{SDK_PACKAGE} is supplied by MOODY BLUES")
    if manifest.entrypoint.partition(".")[0].partition(":")[0] != manifest.package:
        raise ManifestError("entrypoint must be inside the declared package")
    if not SDK_ROOT.is_dir():
        raise ManifestError("the SDK is not beside this installation; run from a checkout")
    package = manifest_path.parent / manifest.package
    if not package.is_dir():
        raise ManifestError(f"package directory {manifest.package} not found beside the manifest")
    archive = _archive(_files(package, manifest.package) + _files(SDK_ROOT, SDK_PACKAGE))
    if len(archive) > MAX_BUNDLE_BYTES:
        raise ManifestError(f"bundle is {len(archive)} bytes; the limit is {MAX_BUNDLE_BYTES}")
    return AgentBundle(manifest, manifest_sha256, archive, hashlib.sha256(archive).hexdigest())
