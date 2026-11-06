"""The native release must run on a Mac that has never seen this repository.

A signed, notarized release shipped with ``VTSDevelopmentRoot`` pointing at the
publishing Mac's checkout, ``VTSDevelopmentPython`` pointing at Homebrew, and no
engine inside the bundle at all.  On the reviewer's Mac the app therefore opened,
reported ``The file "VTS-release-swift-20260827" doesn't exist.`` and sat on
"Loading workflows..." forever, because every engine request tried to run
``<publishing checkout>/vts_engine.py`` through an interpreter that was not
installed.

Source-text assertions cannot catch that class of failure: the source was
self-consistent and the build was green.  The bundle tests below build a
release-shaped app, copy it to an unrelated directory, and require the engine
*inside* the copy to answer real requests with a scrubbed environment - no
checkout, no Homebrew on ``PATH``, no VTS environment variables.

They are slow (they run PyInstaller and swiftc), so they only run when
``VTS_RELEASE_PACKAGING_TESTS=1`` is set.  The everyday suite stays fast.
"""

from __future__ import annotations

import json
import os
import plistlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = REPO_ROOT / "build_swift_prototype.sh"
ENGINE_BUILD_SCRIPT = REPO_ROOT / "build_engine_runtime.sh"
ENGINE_SPEC = REPO_ROOT / "VTS_Engine.spec"
MACOS_COMPATIBILITY_CHECK = REPO_ROOT / "validate_macos_runtime.py"
SWIFT_SOURCE = REPO_ROOT / "macos" / "VTSNativePrototype" / "VTSNativePrototype.swift"
QUICK_ACTIONS = {
    "timestamp": "Timestamp Videos",
    "remove-audio": "Remove Audio",
    "merge": "Merge Clips",
    "transcode": "Transcode Videos",
    "video-minutes": "Calculate Runtime",
    "clip-order": "Order Clips",
}

# Where a packaged app keeps its standalone engine, relative to Contents.
BUNDLED_ENGINE_RELATIVE_PATH = "Resources/engine/vts-engine"
BUNDLED_TOOLS_RELATIVE_PATH = "Resources/engine-tools"

# A release must not preserve any publishing user's home-directory path.
LEAKED_PATHS = ("/Users/",)

PACKAGING_TESTS_ENABLED = os.environ.get("VTS_RELEASE_PACKAGING_TESTS") == "1"
SKIP_REASON = "set VTS_RELEASE_PACKAGING_TESTS=1 to build and probe a release-shaped app"


def _build_app(*, embed_engine: bool, destination: Path) -> Path:
    """Build the native app and return the path to the built bundle."""

    environment = os.environ.copy()
    environment["VTS_PROTOTYPE_EMBED_ENGINE"] = "1" if embed_engine else "0"
    environment.setdefault("VTS_PROTOTYPE_OPTIMIZATION", "-Onone")
    # Build somewhere private. The default output directory is the same
    # build/swift-prototype/ tree an ordinary development build writes to, and
    # this run takes about ten minutes; a build started in that window replaces
    # the Info.plist underneath the bundle about to be copied out, and the
    # release assertions then fail against something this test never built.
    environment["VTS_PROTOTYPE_OUTPUT_DIR"] = str(
        destination.parent / f"build-{'embedded' if embed_engine else 'development'}"
    )
    completed = subprocess.run(
        [str(BUILD_SCRIPT)],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=3600,
    )
    if completed.returncode != 0:
        raise AssertionError(
            "build_swift_prototype.sh failed "
            f"(embed_engine={embed_engine}):\n{completed.stdout[-4000:]}\n{completed.stderr[-4000:]}"
        )
    built = Path(completed.stdout.strip().splitlines()[-1])
    if not built.is_dir():
        raise AssertionError(f"The build script did not print an app bundle: {built}")

    # ditto keeps permissions, symlinks and the signature, which is how the
    # release actually travels to another Mac.
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["/usr/bin/ditto", str(built), str(destination)], check=True)
    return destination


class PrebuiltSwiftBinariesContract(unittest.TestCase):
    """A split release must never ship binaries from other sources.

    A stale binary would carry old behaviour under the new commit's stamp, so
    these refuse before the build script touches anything.
    """

    def _build_with(self, root: Path, manifest: str | None):
        prebuilt = root / "prebuilt"
        prebuilt.mkdir()
        (prebuilt / "VTS").write_bytes(b"stale")
        if manifest is not None:
            (prebuilt / "swift-sources.sha256").write_text(manifest, encoding="utf-8")
        output = root / "build"
        sentinel = output / "VTS.app" / "kept"
        sentinel.parent.mkdir(parents=True)
        sentinel.write_bytes(b"kept")
        environment = os.environ.copy()
        environment["VTS_PREBUILT_SWIFT_DIR"] = str(prebuilt)
        environment["VTS_PROTOTYPE_OUTPUT_DIR"] = str(output)
        completed = subprocess.run(
            [str(BUILD_SCRIPT)],
            cwd=REPO_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=120,
        )
        return completed, sentinel

    def test_binaries_from_other_sources_are_refused_before_any_work(self) -> None:
        stale = "\n".join(
            f"{'0' * 64}  {path}"
            for path in (
                "macos/VTSNativePrototype/VTSNativePrototype.swift",
            )
        )
        with tempfile.TemporaryDirectory() as directory:
            completed, sentinel = self._build_with(Path(directory), stale + "\n")
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("different sources", completed.stderr)
            self.assertTrue(sentinel.exists())

    def test_binaries_without_a_source_record_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            completed, sentinel = self._build_with(Path(directory), None)
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("different sources", completed.stderr)
            self.assertTrue(sentinel.exists())


class EngineResolutionSourceContract(unittest.TestCase):
    """Cheap guards that run in the everyday suite."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.swift_source = SWIFT_SOURCE.read_text(encoding="utf-8")
        cls.build_script = BUILD_SCRIPT.read_text(encoding="utf-8")

    def test_engine_resolution_prefers_the_bundled_engine(self) -> None:
        """A packaged app must never consult the development keys first."""

        resolver_start = self.swift_source.index("static func resolvedClient()")
        resolver_end = self.swift_source.index("func send<Response: Decodable>", resolver_start)
        resolver = self.swift_source[resolver_start:resolver_end]

        bundled = resolver.index(BUNDLED_ENGINE_RELATIVE_PATH.rsplit("/", 1)[-1])
        development = resolver.index("VTSDevelopmentRoot")
        self.assertLess(
            bundled,
            development,
            "the bundled engine must be resolved before the development fallback",
        )

    def test_background_jobs_use_the_same_resolved_runtime(self) -> None:
        """A packaged app must not start workers through a checkout path."""

        job_start = self.swift_source.index("private func startJobProcess(")
        job_source = self.swift_source[job_start : job_start + 2000]

        self.assertIn("client.command(for: .jobRunner)", job_source)
        self.assertIn("client.workingDirectoryURL", job_source)
        self.assertNotIn("vts_job_runner.py", job_source)
        self.assertNotIn("client.pythonURL", job_source)

    def test_build_scripts_carry_no_hardcoded_home_directory(self) -> None:
        """The packaging inputs must not bake in the publishing Mac's paths."""

        for script in (BUILD_SCRIPT, ENGINE_BUILD_SCRIPT, ENGINE_SPEC):
            with self.subTest(script=script.name):
                self.assertNotIn("/Users/", script.read_text(encoding="utf-8"))

    def test_build_script_keeps_the_two_modes_separate(self) -> None:
        """Embedding is a build mode, and the development keys survive it."""

        self.assertIn("VTS_PROTOTYPE_EMBED_ENGINE", self.build_script)
        for key in ("VTSDevelopmentRoot", "VTSDevelopmentPython"):
            with self.subTest(key=key):
                self.assertTrue(
                    any(
                        key in line and "PlistBuddy" in line
                        for line in self.build_script.splitlines()
                    ),
                    f"the build script no longer writes {key} for development",
                )

    def test_embedded_build_checks_every_macho_deployment_target(self) -> None:
        """A macOS 13 app must not quietly carry a macOS 26 runtime."""

        self.assertIn("VTS_PROTOTYPE_MINIMUM_MACOS", self.build_script)
        self.assertIn(MACOS_COMPATIBILITY_CHECK.name, self.build_script)

    def test_action_extensions_are_built_before_the_host_is_signed(self) -> None:
        quick_actions = self.build_script.index('"$ROOT_DIR/build_quick_actions.sh"')
        host_signature = self.build_script.index('"$APP_PATH"', quick_actions)
        self.assertLess(quick_actions, host_signature)


class FrozenEngineResourceRoot(unittest.TestCase):
    """A frozen engine finds its media tools without help from the caller."""

    def test_frozen_engine_finds_its_sibling_engine_tools(self) -> None:
        import media_tool_paths

        with tempfile.TemporaryDirectory() as directory:
            resources = Path(directory) / "Contents" / "Resources"
            engine_directory = resources / "engine"
            engine_directory.mkdir(parents=True)
            tools = resources / "engine-tools"
            tools.mkdir()
            executable = tools / "ffprobe"
            executable.write_text("#!/bin/sh\n", encoding="utf-8")
            executable.chmod(0o755)

            original_frozen = getattr(sys, "frozen", None)
            original_meipass = getattr(sys, "_MEIPASS", None)
            original_executable = sys.executable
            original_environment = os.environ.pop("VTS_ENGINE_RESOURCE_ROOT", None)
            sys.frozen = True  # type: ignore[attr-defined]
            sys._MEIPASS = str(engine_directory / "_internal")  # type: ignore[attr-defined]
            sys.executable = str(engine_directory / "vts-engine")
            try:
                self.assertEqual(
                    Path(media_tool_paths.resolve_media_tool("ffprobe")).resolve(),
                    executable.resolve(),
                )
            finally:
                sys.executable = original_executable
                if original_frozen is None:
                    del sys.frozen  # type: ignore[attr-defined]
                else:
                    sys.frozen = original_frozen  # type: ignore[attr-defined]
                if original_meipass is None:
                    del sys._MEIPASS  # type: ignore[attr-defined]
                else:
                    sys._MEIPASS = original_meipass  # type: ignore[attr-defined]
                if original_environment is not None:
                    os.environ["VTS_ENGINE_RESOURCE_ROOT"] = original_environment


class MacOSCompatibilityContract(unittest.TestCase):
    def test_version_comparison_normalizes_trailing_zeroes(self) -> None:
        from validate_macos_runtime import version_tuple

        self.assertEqual(version_tuple("13"), version_tuple("13.0.0"))
        self.assertLess(version_tuple("13.6.9"), version_tuple("14.0"))


@unittest.skipUnless(PACKAGING_TESTS_ENABLED, SKIP_REASON)
class RelocatedReleaseBundle(unittest.TestCase):
    """The release-shaped bundle, moved somewhere it has no right to work."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory()
        root = Path(cls._temporary.name)
        # Deliberately unrelated to the checkout and to /Applications.
        cls.app = _build_app(
            embed_engine=True,
            destination=root / "Unrelated Place" / "VTS.app",
        )
        cls.contents = cls.app / "Contents"
        cls.engine = cls.contents / BUNDLED_ENGINE_RELATIVE_PATH
        # macOS resolves the temporary directory through /private, and the
        # engine reports the resolved form, so compare like with like.
        cls.resolved_app = cls.app.resolve()
        cls.home = root / "fresh-home"
        (cls.home / "tmp").mkdir(parents=True)
        cls.fixtures = root / "fixtures"
        cls.fixtures.mkdir()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    @property
    def _scrubbed_environment(self) -> dict[str, str]:
        """No checkout, no Homebrew, no VTS variables: a stranger's Mac."""

        return {
            "HOME": str(self.home),
            "TMPDIR": str(self.home / "tmp"),
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "LANG": "en_US.UTF-8",
        }

    def _engine_request(self, request: dict[str, object]) -> dict:
        completed = subprocess.run(
            [str(self.engine), "--request"],
            input=json.dumps(request),
            capture_output=True,
            text=True,
            # "/" proves nothing is resolved relative to a source tree.
            cwd="/",
            env=self._scrubbed_environment,
            timeout=600,
        )
        self.assertTrue(
            completed.stdout.strip(),
            f"the engine printed no JSON: {completed.stderr[-4000:]}",
        )
        return json.loads(completed.stdout)

    def _assert_inside_bundle(self, reported: str, description: str) -> None:
        self.assertTrue(
            Path(reported).resolve().is_relative_to(self.resolved_app),
            f"{description} resolved outside the bundle: {reported}",
        )

    def _fixture_video(self, name: str) -> Path:
        """Encode a tiny clip with the app's own bundled ffmpeg."""

        clip = self.fixtures / name
        if clip.exists():
            return clip
        subprocess.run(
            [
                str(self.contents / BUNDLED_TOOLS_RELATIVE_PATH / "ffmpeg"),
                "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=10:duration=1",
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                str(clip),
            ],
            check=True,
            capture_output=True,
        )
        return clip

    def test_release_info_plist_has_no_development_configuration(self) -> None:
        with (self.contents / "Info.plist").open("rb") as handle:
            info = plistlib.load(handle)

        self.assertNotIn("VTSDevelopmentRoot", info)
        self.assertNotIn("VTSDevelopmentPython", info)

    def test_bundle_carries_an_executable_engine_and_its_runtime(self) -> None:
        self.assertTrue(self.engine.is_file(), f"missing embedded engine: {self.engine}")
        self.assertTrue(os.access(self.engine, os.X_OK), "the embedded engine is not executable")

        runtime = self.engine.parent / "_internal"
        self.assertTrue(runtime.is_dir(), "the embedded engine has no Python runtime")
        interpreters = [
            entry.name
            for entry in runtime.iterdir()
            if entry.name.startswith("Python") or entry.name.startswith("libpython")
        ]
        self.assertTrue(interpreters, f"no Python runtime inside {runtime}")

    def test_bundle_carries_all_six_signed_finder_quick_actions(self) -> None:
        plugins = self.contents / "PlugIns"
        template = plistlib.loads((REPO_ROOT / "macos/VTSQuickActions/Info.plist").read_bytes())
        activation_rule = template["NSExtension"]["NSExtensionAttributes"]["NSExtensionActivationRule"]
        bundles = sorted(plugins.glob("VTSQuickAction-*.appex"))
        self.assertEqual(
            {bundle.name for bundle in bundles},
            {f"VTSQuickAction-{slug}.appex" for slug in QUICK_ACTIONS},
        )
        for slug, title in QUICK_ACTIONS.items():
            with self.subTest(action=slug):
                bundle = plugins / f"VTSQuickAction-{slug}.appex"
                info = plistlib.loads((bundle / "Contents/Info.plist").read_bytes())
                self.assertEqual(info["CFBundleIdentifier"], f"net.rwebber.vts.quick-action.{slug}")
                self.assertEqual(info["CFBundleVersion"], "3")
                self.assertEqual(info["VTSFinderAction"], slug)
                self.assertEqual(info["CFBundleDisplayName"], f"VTS: {title}")
                extension = info["NSExtension"]
                self.assertEqual(extension["NSExtensionPointIdentifier"], "com.apple.services")
                self.assertEqual(
                    extension["NSExtensionAttributes"]["NSExtensionActivationRule"],
                    activation_rule,
                )
                self.assertEqual(
                    extension["NSExtensionAttributes"]["NSExtensionServiceFinderPreviewLabel"],
                    f"VTS: {title}",
                )
                executable = bundle / "Contents/MacOS/VTSQuickAction"
                self.assertTrue(os.access(executable, os.X_OK))
                verified = subprocess.run(
                    ["/usr/bin/codesign", "--verify", "--strict", str(bundle)],
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(verified.returncode, 0, verified.stderr)

    def test_bundle_carries_the_license_notice(self) -> None:
        notice = self.engine.parent / "_internal" / "THIRD_PARTY_NOTICES.md"

        self.assertIn("FFmpeg", notice.read_text(encoding="utf-8"))

    def test_bundle_machos_do_not_exceed_the_declared_macos_minimum(self) -> None:
        with (self.contents / "Info.plist").open("rb") as handle:
            minimum_macos = plistlib.load(handle)["LSMinimumSystemVersion"]

        completed = subprocess.run(
            [
                sys.executable,
                str(MACOS_COMPATIBILITY_CHECK),
                str(self.app),
                str(minimum_macos),
            ],
            capture_output=True,
            text=True,
            timeout=600,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_relocated_engine_answers_capabilities(self) -> None:
        from workflow_schemas import WORKFLOW_SCHEMA_VERSION, public_workflow_schemas

        response = self._engine_request({"action": "capabilities"})

        self.assertTrue(response.get("ok"), response)
        self.assertEqual(response["workflow_schema_version"], WORKFLOW_SCHEMA_VERSION)
        self.assertTrue(response["workflows"], "the packaged engine published no workflows")
        self.assertEqual(
            {workflow["id"] for workflow in response["workflows"]},
            {workflow["id"] for workflow in public_workflow_schemas()},
        )
        self._assert_inside_bundle(
            response["engine"]["python_executable"],
            "the interpreter",
        )

    def test_relocated_engine_resolves_media_tools_from_the_bundle(self) -> None:
        response = self._engine_request({"action": "capabilities"})

        for tool in ("ffmpeg", "ffprobe", "exiftool"):
            with self.subTest(tool=tool):
                entry = response["tools"][tool]
                self.assertTrue(entry["available"], entry)
                self._assert_inside_bundle(entry["resolved_path"], tool)
                self.assertTrue(entry["version"], f"{tool} did not report a version")

    def test_relocated_engine_inspects_a_clip_with_its_bundled_tools(self) -> None:
        clip = self._fixture_video("packaging-fixture.mp4")

        response = self._engine_request({"action": "inspect_videos", "paths": [str(clip)]})

        self.assertTrue(response.get("ok"), response)
        inspected = response["files"][0]
        self.assertEqual(inspected["warnings"], [], inspected)
        self.assertEqual((inspected["width"], inspected["height"]), (320, 240))
        self.assertAlmostEqual(inspected["duration_seconds"], 1.0, delta=0.5)


    def test_relocated_bundle_starts_a_job_worker(self) -> None:
        """The app starts workflows through the same embedded executable."""

        completed = subprocess.run(
            [str(self.engine), "--job-runner", "--request"],
            input=json.dumps({"workflow": "not-a-workflow"}),
            capture_output=True,
            text=True,
            cwd="/",
            env=self._scrubbed_environment,
            timeout=600,
        )

        self.assertEqual(completed.returncode, 2, completed.stderr[-4000:])
        events = [
            json.loads(line)
            for line in completed.stdout.splitlines()
            if line.strip()
        ]
        self.assertTrue(events, f"the worker emitted no events: {completed.stderr[-4000:]}")
        # Reaching the job runner's own validation proves the worker entry
        # point resolved and imported inside the bundle.
        errors = [event for event in events if event["event"] == "error"]
        self.assertTrue(errors, events)
        self.assertIn("not-a-workflow", errors[0]["message"])
        self.assertEqual(events[-1]["event"], "finished")
        self.assertFalse(events[-1]["success"])


    def test_release_bundle_does_not_leak_the_publishing_worktree(self) -> None:
        """Functional metadata and configuration must name no build machine path.

        The frozen Python archive under ``engine/_internal`` is excluded: CPython
        records the build-time source path inside every code object, which is
        inert at runtime and cannot be removed by this project.
        """

        frozen_runtime = self.contents / "Resources" / "engine" / "_internal"
        suffixes = {".plist", ".json", ".cfg", ".ini", ".conf", ".sh"}
        checked = 0
        for path in self.contents.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in suffixes:
                continue
            if frozen_runtime in path.parents:
                continue
            content = path.read_bytes()
            checked += 1
            for leaked in LEAKED_PATHS:
                with self.subTest(file=path.name, leaked=leaked):
                    self.assertNotIn(
                        leaked.encode("utf-8"),
                        content,
                        f"{path} names a build machine path",
                    )
        self.assertGreater(checked, 0, "no functional metadata was scanned")


@unittest.skipUnless(PACKAGING_TESTS_ENABLED, SKIP_REASON)
class DevelopmentBundle(unittest.TestCase):
    """The development loop keeps its deliberate source-tree fallback."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory()
        cls.app = _build_app(
            embed_engine=False,
            destination=Path(cls._temporary.name) / "VTS.app",
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def test_development_build_points_at_this_checkout(self) -> None:
        with (self.app / "Contents" / "Info.plist").open("rb") as handle:
            info = plistlib.load(handle)

        self.assertEqual(info["VTSDevelopmentRoot"], str(REPO_ROOT))
        self.assertTrue(Path(info["VTSDevelopmentPython"]).is_file())
        self.assertFalse(
            (self.app / "Contents" / BUNDLED_ENGINE_RELATIVE_PATH).exists(),
            "a development build should not pay for the packaged engine",
        )


if __name__ == "__main__":
    unittest.main()
