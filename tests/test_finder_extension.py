from __future__ import annotations

import os
import plistlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from finder_extension import FINDER_EXTENSION_BUNDLE_ID, QUICK_ACTION_BUNDLE_IDS, enable_finder_extension, enable_quick_actions, find_finder_extension, finder_extension_election, repair_finder_actions


class FinderExtensionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()


    def test_find_extension_honors_explicit_development_bundle(self) -> None:
        extension = self.root / "VTSFinderExtension.appex"
        extension.mkdir()
        with mock.patch.dict(
            os.environ,
            {"VTS_FINDER_EXTENSION_PATH": str(extension)},
        ):
            self.assertEqual(find_finder_extension(), extension.resolve())


    @mock.patch("finder_extension.sys.platform", "darwin")
    @mock.patch("finder_extension.PLUGINKIT_PATH")
    @mock.patch("finder_extension._run_pluginkit")
    def test_election_distinguishes_default_from_explicit_ignore(
        self,
        run_pluginkit: mock.Mock,
        pluginkit_path: mock.Mock,
    ) -> None:
        pluginkit_path.is_file.return_value = True
        cases = (
            (f"     {FINDER_EXTENSION_BUNDLE_ID}(1.0)\n", "default"),
            (f"-    {FINDER_EXTENSION_BUNDLE_ID}(1.0)\n", "ignore"),
            (f"+    {FINDER_EXTENSION_BUNDLE_ID}(1.0)\n", "use"),
            (f"?    {FINDER_EXTENSION_BUNDLE_ID}(1.0)\n", "unknown"),
            (f"+    {FINDER_EXTENSION_BUNDLE_ID}.other(1.0)\n", "unknown"),
        )
        for listing, election in cases:
            with self.subTest(listing=listing):
                run_pluginkit.return_value = subprocess.CompletedProcess(
                    args=[], returncode=0, stdout=listing, stderr=""
                )
                self.assertEqual(finder_extension_election(), election)
        run_pluginkit.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="unavailable"
        )
        self.assertEqual(finder_extension_election(), "unknown")

    @mock.patch("finder_extension.enable_quick_actions", return_value={})
    @mock.patch("finder_extension._register_containing_application")
    @mock.patch("finder_extension.plugin_election", return_value="use")
    @mock.patch("finder_extension._run_pluginkit")
    def test_enable_registers_and_elects_extension_for_current_user(
        self,
        run_pluginkit: mock.Mock,
        _election: mock.Mock,
        register_application: mock.Mock,
        quick_actions: mock.Mock,
    ) -> None:
        extension = self.root / "VTSFinderExtension.appex"
        extension.mkdir()
        run_pluginkit.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )

        enabled = enable_finder_extension(extension)

        self.assertEqual(enabled, extension.resolve())
        register_application.assert_called_once_with(extension.resolve())
        quick_actions.assert_called_once_with(
            finder_extension_path=extension.resolve(), register_application=False
        )
        self.assertEqual(
            run_pluginkit.call_args_list,
            [
                mock.call(["-a", str(extension.resolve())]),
                mock.call(["-e", "use", "-i", FINDER_EXTENSION_BUNDLE_ID]),
            ],
        )

    @mock.patch("finder_extension._elect_extension")
    @mock.patch("finder_extension._register_containing_application")
    @mock.patch("finder_extension.plugin_election")
    @mock.patch("finder_extension.find_quick_actions")
    def test_quick_action_repair_respects_explicit_ignore(
        self,
        find_actions: mock.Mock,
        election: mock.Mock,
        register_application: mock.Mock,
        elect_extension: mock.Mock,
    ) -> None:
        find_actions.return_value = {
            bundle_id: self.root / f"{bundle_id}.appex"
            for bundle_id in QUICK_ACTION_BUNDLE_IDS
        }
        election.side_effect = lambda bundle_id: (
            "default" if bundle_id == QUICK_ACTION_BUNDLE_IDS[0]
            else "ignore" if bundle_id == QUICK_ACTION_BUNDLE_IDS[1]
            else "use"
        )

        enable_quick_actions(only_default=True)

        elect_extension.assert_called_once_with(
            find_actions.return_value[QUICK_ACTION_BUNDLE_IDS[0]],
            QUICK_ACTION_BUNDLE_IDS[0],
        )
        register_application.assert_called_once_with(
            find_actions.return_value[QUICK_ACTION_BUNDLE_IDS[0]]
        )

    @mock.patch("finder_extension._elect_extension")
    @mock.patch("finder_extension.find_quick_actions")
    def test_partial_quick_action_installation_fails_closed(
        self,
        find_actions: mock.Mock,
        elect_extension: mock.Mock,
    ) -> None:
        find_actions.return_value = {QUICK_ACTION_BUNDLE_IDS[0]: self.root / "one.appex"}
        with self.assertRaisesRegex(OSError, "incomplete"):
            enable_quick_actions()
        elect_extension.assert_not_called()

    @mock.patch("finder_extension.enable_quick_actions")
    @mock.patch("finder_extension._elect_extension")
    @mock.patch("finder_extension.finder_extension_election", return_value="ignore")
    @mock.patch("finder_extension.find_finder_extension")
    def test_auto_repair_does_not_reenable_ignored_finder_sync(
        self,
        find_extension: mock.Mock,
        _election: mock.Mock,
        elect_extension: mock.Mock,
        quick_actions: mock.Mock,
    ) -> None:
        find_extension.return_value = self.root / "VTSFinderExtension.appex"
        repair_finder_actions()
        elect_extension.assert_not_called()
        quick_actions.assert_called_once_with(
            only_default=True, register_application=False
        )

    def test_extension_bundle_metadata_and_icon_are_configured(self) -> None:
        source_root = Path(__file__).resolve().parents[1]
        info_path = source_root / "macos" / "VTSFinderExtension" / "Info.plist"
        entitlements_path = (
            source_root / "macos" / "VTSFinderExtension" / "entitlements.plist"
        )
        native_path = source_root / "macos" / "VTSFinderExtension" / "FinderSync.m"
        with info_path.open("rb") as handle:
            info = plistlib.load(handle)
        with entitlements_path.open("rb") as handle:
            entitlements = plistlib.load(handle)
        source = native_path.read_text(encoding="utf-8")

        self.assertEqual(info["CFBundleIdentifier"], FINDER_EXTENSION_BUNDLE_ID)
        self.assertEqual(info["CFBundleIconFile"], "VTS.icns")
        self.assertEqual(
            info["NSExtension"]["NSExtensionPointIdentifier"],
            "com.apple.FinderSync",
        )
        self.assertTrue(entitlements["com.apple.security.files.user-selected.read-only"])
        self.assertTrue(entitlements["com.apple.security.files.removable-volumes.read-only"])
        self.assertNotIn(
            "com.apple.security.temporary-exception.files.absolute-path.read-write",
            entitlements,
        )
        self.assertIn("FIMenuKind", source)
        self.assertIn("selectedItemURLs", source)
        self.assertIn("targetedURL", source)
        self.assertIn("getpwuid(getuid())", source)
        self.assertNotIn("moveItemAtURL", source)
        self.assertIn("mountedVolumeURLsIncludingResourceValuesForKeys", source)
        self.assertIn("NSWorkspaceDidMountNotification", source)
        self.assertIn("NSWorkspaceDidUnmountNotification", source)
        self.assertIn("@selector(startClipOrder:)", source)
        self.assertIn("@selector(startTimestamp:)", source)
        self.assertIn("@selector(startMerge:)", source)
        self.assertIn("@selector(startTranscode:)", source)
        self.assertNotIn('initWithTitle:@"VTS Tag or Retag"', source)
        self.assertNotIn('initWithTitle:@"Start Job in VTS"', source)
        self.assertNotIn("vts-dev", source)


    def test_standalone_menu_offers_only_background_file_workflows(self) -> None:
        source_root = Path(__file__).resolve().parents[1]
        source = (source_root / "macos/VTSFinderExtension/FinderSync.m").read_text()
        menu = source.split("- (NSMenu *)standaloneMenuWithIcon:", 1)[1].split(
            "- (void)startImportToday:", 1
        )[0]
        for title in (
            "Timestamp Videos", "Remove Audio", "Merge Clips", "Transcode Videos",
            "Calculate Runtime", "Order Clips",
        ):
            self.assertIn(f'@"title": @"{title}"', menu)
        for interactive_or_server_action in ("startTrim:", "applySubject:"):
            self.assertNotIn(f"@selector({interactive_or_server_action})", menu)
        self.assertNotIn("@selector(startTrim:)", source)
        self.assertIn("return [self standaloneMenuWithIcon:icon]", source)

    def test_standalone_actions_sit_directly_in_the_finder_menu(self) -> None:
        source_root = Path(__file__).resolve().parents[1]
        source = (source_root / "macos/VTSFinderExtension/FinderSync.m").read_text()
        menu = source.split("- (NSMenu *)standaloneMenuWithIcon:", 1)[1].split(
            "- (void)startImportToday:", 1
        )[0]
        # Every action is one click away, so nothing may nest them.
        self.assertIn("[menu addItem:item]", menu)
        self.assertNotIn("submenu", menu)
        # Without a parent item naming the app, each item carries the icon.
        self.assertIn("item.image = icon", menu)

    def test_import_today_is_offered_only_on_a_camera_card(self) -> None:
        source_root = Path(__file__).resolve().parents[1]
        source = (source_root / "macos/VTSFinderExtension/FinderSync.m").read_text()

        # Right-clicking the card itself only reaches the extension when the
        # folder holding every mounted volume is registered as well.
        self.assertIn('[NSURL fileURLWithPath:@"/Volumes" isDirectory:YES]', source)
        self.assertIn("FIMenuKindContextualMenuForSidebar", source)
        self.assertIn("BOOL isCameraCard = [self cameraCardVolumeURL] != nil", source)

        gate = source.split("- (BOOL)isCameraCardVolumeURL:", 1)[1]
        # A volume, not a folder inside one.
        self.assertIn('components.count != 3', gate)
        self.assertIn('![components[1] isEqualToString:@"Volumes"]', gate)
        # Removable media only, so the archive drive never offers to import.
        self.assertIn("NSURLVolumeIsRemovableKey", gate)
        self.assertIn("NSURLVolumeIsEjectableKey", gate)
        # And only when it carries the media roots importtoday.py scans.
        self.assertIn('@[@"DCIM", @"PRIVATE", @"private"]', gate)
        self.assertIn("return isCard && holdsCameraMedia", gate)

        # One right-clicked card, never a multiple selection.
        selection = source.split("- (NSURL *)cameraCardVolumeURL {", 1)[1].split(
            "- (BOOL)isCameraCardVolumeURL:", 1
        )[0]
        self.assertIn("selection.count != 1", selection)

    def test_a_card_menu_offers_nothing_that_writes_to_the_card(self) -> None:
        # The card holds the only copy of the footage until it is imported.
        # Timestamping, merging, transcoding and ordering all create or rename
        # files beside the originals, which on a card means editing evidence.
        source_root = Path(__file__).resolve().parents[1]
        source = (source_root / "macos/VTSFinderExtension/FinderSync.m").read_text()
        menu = source.split("- (NSMenu *)cameraCardMenuWithIcon:", 1)[1].split(
            "- (NSURL *)cameraCardVolumeURL", 1
        )[0]

        self.assertIn("[menu addItem:[self importTodayItemWithIcon:icon]]", menu)
        # Calculate Runtime only reads, so it is the one job that may stay.
        self.assertIn("@selector(startVideoMinutes:)", menu)
        for writing_action in (
            "startTimestamp:", "startRemoveAudio:", "startMerge:", "startTranscode:",
            "startClipOrder:", "startTrim:", "applySubject:", "resetTagsRecursively:",
        ):
            self.assertNotIn(f"@selector({writing_action})", menu)

    def test_card_descendants_never_get_write_actions(self) -> None:
        source_root = Path(__file__).resolve().parents[1]
        source = (source_root / "macos/VTSFinderExtension/FinderSync.m").read_text()
        self.assertIn("if ([self isInsideCameraCardURL:url])", source)
        self.assertIn("return [self cameraCardReadOnlyMenuWithIcon:icon];", source)
        descendant = source.split("- (NSMenu *)cameraCardReadOnlyMenuWithIcon:", 1)[1].split(
            "- (BOOL)isInsideCameraCardURL:", 1
        )[0]
        self.assertIn("@selector(startVideoMinutes:)", descendant)
        self.assertNotIn("@selector(startImportToday:)", descendant)
        for writing_action in (
            "startTimestamp:", "startRemoveAudio:", "startMerge:",
            "startTranscode:", "startClipOrder:",
        ):
            self.assertNotIn(f"@selector({writing_action})", descendant)

    def test_every_card_menu_kind_routes_to_the_card_menu(self) -> None:
        source_root = Path(__file__).resolve().parents[1]
        source = (source_root / "macos/VTSFinderExtension/FinderSync.m").read_text()
        routing = source.split("BOOL isCameraCard =", 1)[1].split(
            "- (NSMenuItem *)importTodayItemWithIcon:", 1
        )[0]

        # Sidebar answers for a card and nothing else.
        self.assertIn(
            "return isCameraCard ? [self cameraCardMenuWithIcon:icon] : nil;", routing
        )
        # Item and container right-clicks on a card get the card menu too, so
        # the write operations are unreachable from every direction.
        self.assertIn("return [self cameraCardMenuWithIcon:icon];", routing)
        self.assertIn("return [self standaloneMenuWithIcon:icon];", routing)

        item = source.split("- (NSMenuItem *)importTodayItemWithIcon:", 1)[1].split(
            "- (NSMenu *)cameraCardMenuWithIcon:", 1
        )[0]
        self.assertIn('initWithTitle:@"Import Today\'s Videos"', item)
        self.assertIn("@selector(startImportToday:)", item)

    def test_import_today_starts_a_background_job_for_the_local_day(self) -> None:
        source_root = Path(__file__).resolve().parents[1]
        source = (source_root / "macos/VTSFinderExtension/FinderSync.m").read_text()
        action = source.split("- (void)startImportToday:(id)sender {", 1)[1].split(
            "- (void)startClipOrder:", 1
        )[0]

        # The engine parses import_date with datetime.date.fromisoformat.
        self.assertIn('formatter.dateFormat = @"yyyy-MM-dd"', action)
        self.assertIn('localeWithLocaleIdentifier:@"en_US_POSIX"', action)
        self.assertIn("[NSTimeZone localTimeZone]", action)
        self.assertIn('startFinderJobWithAction:@"import-files"', action)
        self.assertIn('options:@{@"import_date":', action)
        # Every Finder action uses the immediate background-job manifest.
        self.assertIn('@"auto_start": @YES', source)

    def test_a_quick_job_that_cannot_run_says_why_instead_of_stalling(self) -> None:
        source_root = Path(__file__).resolve().parents[1]
        swift_source = (
            source_root / "macos/VTSNativePrototype/VTSNativePrototype.swift"
        ).read_text()
        block = swift_source.split("if manifest.autoStart == true {", 1)[1].split(
            "FinderJobProgressPanelController.shared.present", 1
        )[0]

        # An import with no saved destination fails validation. Without this the
        # floating panel appears and the job never starts.
        self.assertIn("if let blocker = runDisabledReason(for: workflow) {", block)
        self.assertIn("setWorkflowError(blocker, for: workflow.id)", block)
        self.assertIn("workflowMessages.removeValue(forKey: workflow.id)", block)
        self.assertIn("NSApp.activate(ignoringOtherApps: true)", block)
        self.assertIn("return workflow.id", block)

    def test_quick_jobs_target_the_owning_app_without_activating_it(self) -> None:
        source_root = Path(__file__).resolve().parents[1]
        source = (source_root / "macos/VTSFinderExtension/FinderSync.m").read_text()
        self.assertIn('@"version": @3', source)
        self.assertIn('@"auto_start": @YES', source)
        self.assertIn("configuration.activates = NO", source)
        self.assertIn("withApplicationAtURL:[self containingApplicationURL]", source)
        self.assertNotIn("openURL:jobURL]", source)
        self.assertNotIn("vts-dev", source)


if __name__ == "__main__":
    unittest.main()
