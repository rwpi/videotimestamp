from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path


FINDER_EXTENSION_BUNDLE_ID = "net.rwebber.vts.finder.extension"
FINDER_EXTENSION_BUNDLE_NAME = "VTSFinderExtension.appex"
QUICK_ACTION_SLUGS = (
    "timestamp", "remove-audio", "merge", "transcode", "video-minutes", "clip-order",
)
QUICK_ACTION_BUNDLE_IDS = tuple(
    f"net.rwebber.vts.quick-action.{slug}" for slug in QUICK_ACTION_SLUGS
)
PLUGINKIT_PATH = Path("/usr/bin/pluginkit")
LSREGISTER_PATH = Path(
    "/System/Library/Frameworks/CoreServices.framework/Frameworks/"
    "LaunchServices.framework/Support/lsregister"
)


def _extension_candidates() -> tuple[Path, ...]:
    candidates: list[Path] = []
    override = os.environ.get("VTS_FINDER_EXTENSION_PATH")
    if override:
        candidates.append(Path(override).expanduser())
    if getattr(sys, "frozen", False):
        executable = Path(sys.executable).resolve()
        candidates.append(
            executable.parent.parent
            / "PlugIns"
            / FINDER_EXTENSION_BUNDLE_NAME
        )
    candidates.append(
        Path("/Applications/VTS.app/Contents/PlugIns")
        / FINDER_EXTENSION_BUNDLE_NAME
    )
    return tuple(candidates)


def find_finder_extension() -> Path | None:
    return next(
        (
            candidate.resolve()
            for candidate in _extension_candidates()
            if candidate.is_dir()
        ),
        None,
    )


def find_quick_actions(finder_extension_path: Path | None = None) -> dict[str, Path]:
    finder_extension = finder_extension_path or find_finder_extension()
    if finder_extension is None:
        return {}
    plugins = finder_extension.parent
    return {
        bundle_id: candidate.resolve()
        for slug, bundle_id in zip(QUICK_ACTION_SLUGS, QUICK_ACTION_BUNDLE_IDS)
        if (candidate := plugins / f"VTSQuickAction-{slug}.appex").is_dir()
    }


def _run_pluginkit(arguments: list[str]) -> subprocess.CompletedProcess[str]:
    if sys.platform != "darwin" or not PLUGINKIT_PATH.is_file():
        raise OSError("The VTS Finder extension is available only on macOS.")
    try:
        return subprocess.run(
            [str(PLUGINKIT_PATH), *arguments],
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
    except subprocess.SubprocessError as exc:
        raise OSError(f"Finder extension setup did not finish: {exc}") from exc


def _containing_application(extension: Path) -> Path:
    try:
        application = extension.parents[2]
    except IndexError as exc:
        raise OSError("The Finder extension is not inside a macOS app bundle.") from exc
    if application.suffix.lower() != ".app" or not application.is_dir():
        raise OSError("The Finder extension is not inside a macOS app bundle.")
    return application


def _register_containing_application(extension: Path) -> None:
    if sys.platform != "darwin" or not LSREGISTER_PATH.is_file():
        raise OSError("The VTS Finder extension is available only on macOS.")
    application = _containing_application(extension)
    try:
        result = subprocess.run(
            [str(LSREGISTER_PATH), "-f", str(application)],
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
    except subprocess.SubprocessError as exc:
        raise OSError(f"Finder extension setup did not finish: {exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise OSError(detail or "macOS could not register the VTS application.")


def plugin_election(bundle_id: str) -> str:
    """Return the current user's PlugInKit election for an exact bundle ID.

    A default election can be repaired after an update. An explicit ignore
    election is the user's choice and must not be undone automatically.
    """
    if sys.platform != "darwin" or not PLUGINKIT_PATH.is_file():
        return "unknown"
    result = _run_pluginkit(
        ["-m", "-v", "-i", bundle_id]
    )
    if result.returncode != 0:
        return "unknown"
    entry = re.compile(
        rf"^\s*([+!?=\-]?)\s*{re.escape(bundle_id)}\("
    )
    for line in result.stdout.splitlines():
        match = entry.match(line)
        if match:
            return {"+": "use", "-": "ignore", "": "default"}.get(
                match.group(1), "unknown"
            )
    return "unknown"


def finder_extension_election() -> str:
    return plugin_election(FINDER_EXTENSION_BUNDLE_ID)


def _elect_extension(extension: Path, bundle_id: str) -> None:
    registration = _run_pluginkit(["-a", str(extension)])
    if registration.returncode != 0:
        detail = registration.stderr.strip() or registration.stdout.strip()
        raise OSError(detail or f"macOS could not register {bundle_id}.")
    election = _run_pluginkit(["-e", "use", "-i", bundle_id])
    if election.returncode != 0:
        detail = election.stderr.strip() or election.stdout.strip()
        raise OSError(detail or f"macOS could not enable {bundle_id}.")
    if plugin_election(bundle_id) != "use":
        raise OSError(f"macOS registered {bundle_id} but has not enabled it.")


def enable_quick_actions(
    *, only_default: bool = False, finder_extension_path: Path | None = None,
    register_application: bool = True,
) -> dict[str, Path]:
    """Elect all packaged Quick Actions, or repair only default elections."""
    actions = find_quick_actions(finder_extension_path)
    if actions and len(actions) != len(QUICK_ACTION_BUNDLE_IDS):
        raise OSError("The VTS Quick Actions installation is incomplete.")
    selected = [
        (bundle_id, extension)
        for bundle_id, extension in actions.items()
        if not only_default or plugin_election(bundle_id) == "default"
    ]
    if selected and register_application:
        _register_containing_application(selected[0][1])
    for bundle_id, extension in selected:
        _elect_extension(extension, bundle_id)
    return actions


def enable_finder_extension(extension_path: Path | None = None) -> Path:
    """Register and enable Finder Sync and packaged Quick Actions for this user."""
    extension = (
        Path(extension_path).expanduser().resolve()
        if extension_path is not None
        else find_finder_extension()
    )
    if extension is None or not extension.is_dir():
        raise OSError(
            "The Finder extension is not present in this VTS installation. "
            "Install or run the current VTS build, then try again."
        )
    _register_containing_application(extension)
    _elect_extension(extension, FINDER_EXTENSION_BUNDLE_ID)
    enable_quick_actions(finder_extension_path=extension, register_application=False)
    return extension


def repair_finder_actions() -> None:
    """Repair unset elections without overriding an explicit user disable."""
    extension = find_finder_extension()
    if extension is not None and finder_extension_election() == "default":
        _elect_extension(extension, FINDER_EXTENSION_BUNDLE_ID)
    enable_quick_actions(only_default=True, register_application=False)
