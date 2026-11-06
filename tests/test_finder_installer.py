from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ACTIVATE = ROOT / "activate_finder_extension.sh"


class FinderInstallerTests(unittest.TestCase):
    def test_activation_defers_without_a_finder_for_the_invoking_user(self) -> None:
        self._exercise_activation(requires_finder_restart=False, gui_session=False)

    def test_activation_rejects_an_incomplete_bundle_without_a_gui(self) -> None:
        self._exercise_activation(
            requires_finder_restart=False,
            gui_session=False,
            actions="partial",
            expect_deferred=False,
        )

    def test_activation_verifies_the_installed_binary_after_launch(self) -> None:
        self._exercise_activation(requires_finder_restart=False)

    def test_activation_restarts_finder_if_launch_does_not_load_extension(self) -> None:
        self._exercise_activation(requires_finder_restart=True)

    def test_activation_rejects_a_stale_process_from_the_replaced_app(self) -> None:
        self._exercise_activation(requires_finder_restart=False, stale_process=True)

    def test_update_restarts_even_if_registration_creates_a_fresh_session(self) -> None:
        self._exercise_activation(requires_finder_restart=False, existing_process=True)

    def test_restart_must_change_the_finder_pid(self) -> None:
        self._exercise_activation(
            requires_finder_restart=False,
            existing_process=True,
            handshake="no_finder_restart",
            expect_success=False,
        )

    def test_activation_never_accepts_only_a_stale_process_handshake(self) -> None:
        self._exercise_activation(
            requires_finder_restart=False,
            stale_process=True,
            handshake="stale_only",
            expect_success=False,
        )

    def test_activation_restarts_after_a_fresh_process_has_the_wrong_finder_peer(self) -> None:
        self._exercise_activation(
            requires_finder_restart=False,
            handshake="wrong_then_right",
            expect_restart=True,
        )

    def test_activation_fails_when_a_fresh_process_only_has_a_wrong_peer(self) -> None:
        self._exercise_activation(
            requires_finder_restart=False, handshake="wrong", expect_success=False
        )

    def test_activation_fails_when_finder_invalidates_the_handshake(self) -> None:
        self._exercise_activation(
            requires_finder_restart=False,
            handshake="invalidated",
            expect_success=False,
        )

    def test_activation_fails_without_a_readable_handshake(self) -> None:
        self._exercise_activation(
            requires_finder_restart=False, handshake="none", expect_success=False
        )

    def test_activation_fails_when_the_services_never_register(self) -> None:
        # Finder Sync cannot serve iCloud Drive, so an install whose services
        # are missing has not delivered the jobs where they are needed.
        self._exercise_activation(
            requires_finder_restart=False,
            services="missing",
            expect_success=False,
            expect_restart=False,
        )

    def test_activation_rejects_services_from_an_old_bundle(self) -> None:
        # The installed app appearing somewhere in pbs is insufficient if
        # all six actions still belong to a previous copy of VTS.
        self._exercise_activation(
            requires_finder_restart=False,
            services="old_bundle",
            expect_success=False,
            expect_restart=False,
        )

    def test_activation_accepts_services_in_a_large_cache_dump(self) -> None:
        self._exercise_activation(requires_finder_restart=False, services="large")

    def test_activation_elects_six_installed_finder_quick_actions(self) -> None:
        self._exercise_activation(
            requires_finder_restart=False, actions="present", expect_restart=True
        )

    def test_activation_accepts_already_elected_finder_quick_actions(self) -> None:
        self._exercise_activation(
            requires_finder_restart=False,
            actions="already_enabled",
            expect_restart=False,
        )

    def test_activation_rejects_a_partial_finder_quick_action_bundle(self) -> None:
        self._exercise_activation(
            requires_finder_restart=False,
            actions="partial",
            expect_success=False,
        )

    def test_activation_rejects_an_unusable_quick_action_extension_point(self) -> None:
        self._exercise_activation(
            requires_finder_restart=False,
            actions="wrong_point",
            expect_success=False,
        )

    def test_activation_rejects_quick_actions_that_remain_disabled(self) -> None:
        self._exercise_activation(
            requires_finder_restart=False,
            actions="disabled",
            expect_success=False,
            expect_restart=True,
        )

    def test_activation_rejects_quick_actions_from_an_old_bundle(self) -> None:
        self._exercise_activation(
            requires_finder_restart=False,
            actions="old_path",
            expect_success=False,
            expect_restart=True,
        )

    def test_activation_fails_before_mutation_when_log_stream_cannot_start(self) -> None:
        self._exercise_activation(
            requires_finder_restart=False,
            handshake="unreadable",
            expect_success=False,
        )

    def _exercise_activation(
        self,
        *,
        requires_finder_restart: bool,
        stale_process: bool = False,
        existing_process: bool = False,
        handshake: str = "right",
        services: str = "present",
        actions: str = "legacy",
        expect_success: bool = True,
        expect_restart: bool | None = None,
        gui_session: bool = True,
        expect_deferred: bool = True,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = root / "VTS.app"
            extension = app / "Contents/PlugIns/VTSFinderExtension.appex/Contents/MacOS/VTSFinderExtension"
            extension.parent.mkdir(parents=True)
            extension.write_text("#!/bin/sh\n", encoding="utf-8")
            extension.chmod(0o755)
            if actions != "legacy":
                slugs = ("timestamp", "remove-audio", "merge", "transcode", "video-minutes", "clip-order")
                for slug in slugs[:1] if actions == "partial" else slugs:
                    action = app / f"Contents/PlugIns/VTSQuickAction-{slug}.appex"
                    (action / "Contents/MacOS").mkdir(parents=True)
                    (action / "Contents/Info.plist").write_text(
                        f"net.rwebber.vts.quick-action.{slug}\n", encoding="utf-8"
                    )
                    executable = action / "Contents/MacOS/VTSQuickAction"
                    executable.write_text("#!/bin/sh\n", encoding="utf-8")
                    executable.chmod(0o755)

            tool = root / "mock-tool"
            tool.write_text(
                """#!/bin/bash
printf '%s %s\\n' "$(basename "$0")" "$*" >> "$VTS_TEST_LOG"
case "$(basename "$0")" in
    log)
        if [[ "$VTS_TEST_HANDSHAKE" == "unreadable" ]]; then exit 2; fi
        # Keep the stream alive until the activation helper terminates it.
        # Each event names both the appex process and the Finder peer.
        while [[ ! -f "$VTS_TEST_READY" ]]; do /bin/sleep 0.01; done
        if [[ "$VTS_TEST_HANDSHAKE" == "stale_only" ]]; then
            printf 'Db VTSFinderExtension[123:abcd] [com.apple.extensionkit:NSExtension] creating principle object: <VTSFinderSync: 0x1> - with extensionContext <NSXPCConnection: 0x2> connection from pid 100 on mach service named net.rwebber.vts.finder.extension.apple-extension-service\\n'
        fi
        if [[ "$VTS_TEST_STALE" != "1" && "$VTS_TEST_HANDSHAKE" != "none" ]]; then
            peer=100
            if [[ "$VTS_TEST_HANDSHAKE" == "wrong" || "$VTS_TEST_HANDSHAKE" == "wrong_then_right" ]]; then peer=999; fi
            printf 'Db VTSFinderExtension[456:abcd] [com.apple.extensionkit:NSExtension] creating principle object: <VTSFinderSync: 0x1> - with extensionContext <NSXPCConnection: 0x2> connection from pid %s on mach service named net.rwebber.vts.finder.extension.apple-extension-service\\n' "$peer"
            if [[ "$VTS_TEST_HANDSHAKE" == "invalidated" ]]; then
                printf 'Db VTSFinderExtension[456:abcd] [com.apple.PlugInKit] host connection from pid 100 invalidated\\n'
            fi
        fi
        while [[ ! -f "$VTS_TEST_NEW_PROCESS" ]]; do /bin/sleep 0.01; done
        if [[ "$VTS_TEST_HANDSHAKE" != "none" && "$VTS_TEST_HANDSHAKE" != "stale_only" ]]; then
            peer=200
            if [[ "$VTS_TEST_HANDSHAKE" == "no_finder_restart" ]]; then peer=100; fi
            if [[ "$VTS_TEST_HANDSHAKE" == "wrong" ]]; then peer=999; fi
            printf 'Db VTSFinderExtension[789:abcd] [com.apple.extensionkit:NSExtension] creating principle object: <VTSFinderSync: 0x1> - with extensionContext <NSXPCConnection: 0x2> connection from pid %s on mach service named net.rwebber.vts.finder.extension.apple-extension-service\\n' "$peer"
            if [[ "$VTS_TEST_HANDSHAKE" == "invalidated" ]]; then
                printf 'Db VTSFinderExtension[789:abcd] [com.apple.PlugInKit] host connection from pid 200 invalidated\\n'
            fi
        fi
        for _ in $(seq 1 60); do /bin/sleep 0.5; done ;;
    pluginkit)
        if [[ "$1" == "-m" && "$2" == "-i" ]]; then
            marker=' '
            if [[ -f "$VTS_TEST_ACTIONS_ENABLED" ]]; then marker='+'; fi
            if [[ "$VTS_TEST_ACTIONS" == "disabled" ]]; then marker='-'; fi
            action_path="$VTS_TEST_APP/Contents/PlugIns/VTSQuickAction-${3##*.}.appex"
            if [[ "$VTS_TEST_ACTIONS" == "old_path" ]]; then action_path="/Applications/Old VTS.app/Contents/PlugIns/VTSQuickAction-${3##*.}.appex"; fi
            printf '%s    %s(1.0)\n' "$marker" "$3"
            printf '\t            Path = %s\n' "$action_path"
        elif [[ "$1" == "-m" && -f "$VTS_TEST_READY" ]]; then
            echo '+    net.rwebber.vts.finder.extension(1.0)'
        elif [[ "$1" == "-e" && "$2" == "use" && "$4" == net.rwebber.vts.quick-action.* ]]; then
            if [[ "$VTS_TEST_ACTIONS" != "disabled" ]]; then touch "$VTS_TEST_ACTIONS_ENABLED"; fi
        fi ;;
    plistbuddy)
        if [[ "$1" == "-c" && "$2" == "Print :CFBundleIdentifier" ]]; then
            /bin/cat "$3"
        elif [[ "$1" == "-c" && "$2" == "Print :NSExtension:NSExtensionPointIdentifier" ]]; then
            if [[ "$VTS_TEST_ACTIONS" == "wrong_point" ]]; then echo com.apple.ui-services; else echo com.apple.services; fi
        fi ;;
    open)
        if [[ "$VTS_TEST_RESTART" == "0" ]]; then touch "$VTS_TEST_READY"; fi ;;
    killall) touch "$VTS_TEST_READY" "$VTS_TEST_NEW_PROCESS" ;;
    pgrep)
        if [[ "$1" == "-u" && "$3" == "-x" && "$4" == "Finder" ]]; then
            if [[ "$VTS_TEST_GUI" == "1" ]]; then
                if [[ -f "$VTS_TEST_NEW_PROCESS" && "$VTS_TEST_HANDSHAKE" != "no_finder_restart" ]]; then echo 200; else echo 100; fi
            fi
        elif [[ "$3" == "-x" && "$4" == "VTSFinderExtension" ]]; then
            if [[ "$VTS_TEST_STALE" == "1" || "$VTS_TEST_EXISTING" == "1" ]]; then echo 123; fi
        elif [[ "$VTS_TEST_EXISTING" == "1" && ! -f "$VTS_TEST_READY" ]]; then
            echo "123 $VTS_TEST_APP/Contents/PlugIns/VTSFinderExtension.appex/Contents/MacOS/VTSFinderExtension -AppleLanguages"
        elif [[ "$VTS_TEST_STALE" == "1" && ! -f "$VTS_TEST_NEW_PROCESS" ]]; then
            echo "123 $VTS_TEST_APP/Contents/PlugIns/VTSFinderExtension.appex/Contents/MacOS/VTSFinderExtension -AppleLanguages"
        elif [[ -f "$VTS_TEST_NEW_PROCESS" ]]; then
            echo "789 $VTS_TEST_APP/Contents/PlugIns/VTSFinderExtension.appex/Contents/MacOS/VTSFinderExtension -AppleLanguages"
        elif [[ -f "$VTS_TEST_READY" ]]; then
            echo "456 $VTS_TEST_APP/Contents/PlugIns/VTSFinderExtension.appex/Contents/MacOS/VTSFinderExtension -AppleLanguages"
        fi ;;
    pbs)
        if [[ "$1" == "-dump" && "$VTS_TEST_SERVICES" != "missing" ]]; then
            if [[ "$VTS_TEST_SERVICES" == "large" ]]; then
                /usr/bin/awk 'BEGIN { for (i = 0; i < 2000; i++) print "        cached service from another application........................................" }'
            fi
            for message in vtsTimestamp vtsRemoveAudio vtsMerge vtsTranscode vtsVideoMinutes vtsClipOrder; do
                path="$VTS_TEST_APP"
                if [[ "$VTS_TEST_SERVICES" == "old_bundle" ]]; then path="/Applications/Old VTS.app"; fi
                printf '        {\n'
                printf '        NSBundleIdentifier = "net.rwebber.vts";\n'
                printf '        NSBundlePath = "%s";\n' "$path"
                printf '        NSMessage = %s;\n' "$message"
                printf '        NSPortName = VTS;\n'
                printf '    },\n'
            done
            if [[ "$VTS_TEST_SERVICES" == "old_bundle" ]]; then
                printf '        {\n'
                printf '        NSBundleIdentifier = "net.rwebber.vts";\n'
                printf '        NSBundlePath = "%s";\n' "$VTS_TEST_APP"
                printf '        NSMessage = unrelatedMessage;\n'
                printf '        NSPortName = VTS;\n'
                printf '    }\n'
            fi
        fi ;;
    sleep) /bin/sleep 0.05 ;;
esac
""",
                encoding="utf-8",
            )
            tool.chmod(0o755)
            for name in ("lsregister", "pluginkit", "open", "pgrep", "killall", "sleep", "log", "pbs", "plistbuddy"):
                (root / name).symlink_to(tool)

            if actions == "already_enabled":
                (root / "actions-enabled").touch()

            env = os.environ.copy()
            env.update(
                {
                    "VTS_TEST_LOG": str(root / "calls"),
                    "VTS_TEST_READY": str(root / "ready"),
                    "VTS_TEST_NEW_PROCESS": str(root / "new-process"),
                    "VTS_TEST_APP": str(app),
                    "VTS_TEST_RESTART": "1" if requires_finder_restart else "0",
                    "VTS_TEST_STALE": "1" if stale_process else "0",
                    "VTS_TEST_EXISTING": "1" if existing_process else "0",
                    "VTS_TEST_HANDSHAKE": handshake,
                    "VTS_TEST_SERVICES": services,
                    "VTS_TEST_ACTIONS": actions,
                    "VTS_TEST_ACTIONS_ENABLED": str(root / "actions-enabled"),
                    "VTS_TEST_GUI": "1" if gui_session else "0",
                    **{
                        key: str(root / name)
                        for key, name in (
                            ("VTS_LSREGISTER_PATH", "lsregister"),
                            ("VTS_PLUGINKIT_PATH", "pluginkit"),
                            ("VTS_OPEN_PATH", "open"),
                            ("VTS_PGREP_PATH", "pgrep"),
                            ("VTS_KILLALL_PATH", "killall"),
                            ("VTS_SLEEP_PATH", "sleep"),
                            ("VTS_LOG_PATH", "log"),
                            ("VTS_PBS_PATH", "pbs"),
                            ("VTS_PLISTBUDDY_PATH", "plistbuddy"),
                        )
                    },
                }
            )
            result = subprocess.run(
                ["bash", str(ACTIVATE), str(app)],
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=15,
            )
            calls = (root / "calls").read_text(encoding="utf-8")
            if not gui_session:
                self.assertEqual(result.returncode, 3 if expect_deferred else 1, result.stderr)
                if expect_deferred:
                    self.assertIn("activation deferred", result.stdout)
                else:
                    self.assertIn("Finder Quick Action is missing", result.stderr)
                for mutation in ("log stream", "lsregister -f", "pluginkit", "open -g", "killall", "pbs"):
                    self.assertNotIn(mutation, calls)
                return
            self.assertNotEqual(
                result.returncode,
                3,
                f"GUI fixture unexpectedly deferred: gui={env['VTS_TEST_GUI']!r}, "
                f"handshake={handshake!r}, calls={calls!r}, "
                f"stdout={result.stdout!r}, stderr={result.stderr!r}",
            )
            self.assertEqual(result.returncode == 0, expect_success, result.stderr)
            if handshake == "unreadable":
                self.assertIn("Could not read the Finder extension initialization log", result.stderr)
                self.assertNotIn("lsregister -f", calls)
                self.assertNotIn("killall -u", calls)
                return
            if actions in {"partial", "wrong_point"}:
                self.assertIn(
                    "Finder Quick Action is missing" if actions == "partial" else "Finder Quick Action extension point mismatch",
                    result.stderr,
                )
                self.assertNotIn("lsregister -f", calls)
                self.assertNotIn("killall -u", calls)
                return
            self.assertIn(f"lsregister -f {app}", calls)
            self.assertIn("pluginkit -e use -i net.rwebber.vts.finder.extension", calls)
            self.assertIn(f"open -g -a {app}", calls)
            if expect_restart is None:
                expect_restart = requires_finder_restart or stale_process or existing_process or not expect_success
            self.assertEqual("killall -u" in calls, expect_restart)
            self.assertIn("log stream --style compact --level debug", calls)
            if expect_success:
                # An install that cannot reach iCloud Drive is not finished.
                self.assertIn("pbs -dump", calls)
            self.assertLess(calls.index("log stream"), calls.index("lsregister -f"))
            if expect_success:
                self.assertIn(str(extension), result.stdout)
                self.assertIn("Finder initialized", result.stdout)
                self.assertIn("installed VTS services for file selections", result.stdout)
                if actions != "legacy":
                    self.assertIn("enabled all six installed VTS Finder Quick Actions", result.stdout)
                    for slug in slugs:
                        action = app / f"Contents/PlugIns/VTSQuickAction-{slug}.appex"
                        self.assertIn(f"pluginkit -a {action}", calls)
                        self.assertIn(
                            f"pluginkit -e use -i net.rwebber.vts.quick-action.{slug}",
                            calls,
                        )
            elif services in {"missing", "old_bundle"}:
                # Finder attached; only the iCloud Drive route was missing, and
                # the message has to say which half failed.
                self.assertIn("did not register the VTS services", result.stderr)
            elif actions != "legacy":
                self.assertIn("did not enable all six installed VTS Finder Quick Actions", result.stderr)
            else:
                self.assertIn("did not confirm initialization", result.stderr)


if __name__ == "__main__":
    unittest.main()
