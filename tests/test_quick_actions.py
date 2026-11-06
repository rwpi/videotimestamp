"""Contracts for the macOS Services entry point.

Finder Sync menus only appear inside directories the extension monitors, and a
File Provider location such as iCloud Drive may not expose those actions. The
Services surface reads the Finder selection instead of the enclosing folder.
These tests keep that surface honest: every advertised action must be a real
workflow, and every advertised selector must exist in the app.
"""

from __future__ import annotations

import json
import plistlib
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
INFO_PLIST = ROOT / "macos" / "VTSNativePrototype" / "Info.plist"
SWIFT_SOURCE = ROOT / "macos" / "VTSNativePrototype" / "VTSNativePrototype.swift"
ACTION_INFO_PLIST = ROOT / "macos" / "VTSQuickActions" / "Info.plist"
ACTION_SOURCE = ROOT / "macos" / "VTSQuickActions" / "QuickAction.m"

# The action each advertised service starts, keyed by its Objective-C message.
EXPECTED_SERVICES = {
    "vtsTimestamp": "timestamp",
    "vtsRemoveAudio": "remove-audio",
    "vtsMerge": "merge",
    "vtsTranscode": "transcode",
    "vtsVideoMinutes": "video-minutes",
    "vtsClipOrder": "clip-order",
}


class QuickActionServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.info = plistlib.loads(INFO_PLIST.read_bytes())
        cls.swift = SWIFT_SOURCE.read_text(encoding="utf-8")

    def test_every_advertised_service_is_declared(self) -> None:
        services = self.info.get("NSServices", [])
        messages = [service["NSMessage"] for service in services]
        self.assertEqual(sorted(messages), sorted(EXPECTED_SERVICES))

    def test_services_reach_video_files_and_folders(self) -> None:
        # A service that does not accept the selection never reaches the menu,
        # which is the whole failure this surface exists to fix.
        for service in self.info.get("NSServices", []):
            with self.subTest(service=service["NSMessage"]):
                sent = service["NSSendFileTypes"]
                self.assertIn("public.movie", sent)
                self.assertIn("public.folder", sent)
                self.assertEqual(service["NSPortName"], "VTS")
                self.assertTrue(
                    service["NSMenuItem"]["default"].startswith("VTS: "),
                    "a service is named so an operator can find it among other apps'",
                )

    def test_services_are_eligible_for_automatic_menu_presentation(self) -> None:
        # Apple's Services Properties guide says an absent NSRequiredContext
        # registers the service but does not automatically show it in menus.
        for service in self.info.get("NSServices", []):
            with self.subTest(service=service["NSMessage"]):
                self.assertEqual(service.get("NSRequiredContext"), {})


    def test_every_service_has_a_handler_in_the_app(self) -> None:
        for message, action in EXPECTED_SERVICES.items():
            with self.subTest(message=message):
                handler = re.search(
                    rf"@objc func {re.escape(message)}\(\s*"
                    r"_ pasteboard: NSPasteboard,\s*"
                    r"userData: String\?,\s*"
                    r"error: AutoreleasingUnsafeMutablePointer<NSString>\?\s*"
                    r"\) \{\s*"
                    rf'start\("{re.escape(action)}", from: pasteboard, reporting: error\)',
                    self.swift,
                )
                self.assertIsNotNone(
                    handler,
                    f"{message} has no handler starting {action}",
                )

    def test_the_provider_is_registered_at_launch(self) -> None:
        # macOS discovers the static entries in Info.plist. The provider must
        # register when the app is launched to answer a selected service.
        self.assertIn(
            "NSApplication.shared.servicesProvider = VTSServiceProvider.shared",
            self.swift,
        )

    def test_finder_extension_repairs_default_election_but_respects_ignore(self) -> None:
        launch = self.swift.split(
            "func applicationDidFinishLaunching(_ notification: Notification) {", 1
        )[1].split("\n    }", 1)[0]
        self.assertIn(
            "await PrototypeViewModel.shared.repairFinderExtensionElectionIfNeeded()",
            launch,
        )
        self.assertIn("Task { @MainActor in", launch)
        repair = self.swift.split(
            "func repairFinderExtensionElectionIfNeeded() async {", 1
        )[1].split("\n    }", 1)[0]
        self.assertIn('response.election == "default"', repair)
        self.assertIn('$0.installed && $0.election == "default"', repair)
        self.assertIn("response.installed == true", repair)
        self.assertIn('"action": "repair_finder_actions"', repair)
        self.assertNotIn("UserDefaults.standard", launch)

    def test_a_service_starts_work_through_the_finder_job_manifest(self) -> None:
        # One validated door in. A second job format would be a second set of
        # bugs, and the manifest is what the app already checks.
        self.assertIn('"version": 3,', self.swift)
        self.assertIn('"auto_start": true,', self.swift)
        self.assertIn('URL(string: "vts://finder-job/\\(jobID)")', self.swift)

    def test_an_empty_selection_is_reported_not_ignored(self) -> None:
        self.assertIn(
            '"VTS received no files from the Finder selection." as NSString',
            self.swift,
        )


class FinderActionExtensionTests(unittest.TestCase):
    def test_action_extension_is_a_real_finder_quick_action(self) -> None:
        info = plistlib.loads(ACTION_INFO_PLIST.read_bytes())
        extension = info["NSExtension"]
        attributes = extension["NSExtensionAttributes"]
        self.assertEqual(extension["NSExtensionPointIdentifier"], "com.apple.services")
        self.assertEqual(extension["NSExtensionPrincipalClass"], "VTSQuickAction")
        self.assertTrue(attributes["NSExtensionServiceAllowsFinderPreviewItem"])
        self.assertEqual(info["CFBundleVersion"], "3")
        rule = attributes["NSExtensionActivationRule"]
        self.assertIsInstance(rule, str)
        self.assertIn('UTI-CONFORMS-TO "public.file-url"', rule)
        self.assertIn('UTI-CONFORMS-TO "public.movie"', rule)
        self.assertIn('UTI-CONFORMS-TO "public.folder"', rule)
        self.assertNotIn("TRUEPREDICATE", rule)
        self.assertEqual(info["VTSFinderAction"], "__ACTION__")
        self.assertIn("__TITLE__", attributes["NSExtensionServiceFinderPreviewLabel"])

    @unittest.skipUnless(sys.platform == "darwin", "requires macOS NSPredicate")
    def test_activation_predicate_accepts_bounded_original_url_or_semantic_selections(self) -> None:
        info = plistlib.loads(ACTION_INFO_PLIST.read_bytes())
        rule = info["NSExtension"]["NSExtensionAttributes"]["NSExtensionActivationRule"]

        def attachment(*types: str) -> dict:
            return {"registeredTypeIdentifiers": list(types)}

        def selection(*items: list[dict]) -> dict:
            return {"extensionItems": [{"attachments": item} for item in items]}

        original = attachment("public.file-url")
        movie = attachment("public.mpeg-4", "public.movie", "public.file-url")
        folder = attachment("public.folder", "public.file-url")
        cases = {
            "movie": (selection([movie]), True),
            "folder": (selection([folder]), True),
            "text_file": (selection([attachment("public.plain-text", "public.file-url")]), True),
            "original_url_only": (selection([original]), True),
            "mixed_items": (selection([movie, folder], [original]), True),
            "empty_selection": (selection(), False),
            "empty_item": (selection([original], []), False),
            "finder_semantic_movie": (selection([attachment("public.mpeg-4")]), True),
            "finder_semantic_folder": (selection([attachment("public.folder")]), True),
            "mixed_unsupported_type": (selection([movie, attachment("public.image")]), False),
            "text_without_original_url": (selection([attachment("public.plain-text")]), False),
            "remote_url": (selection([attachment("public.url")]), False),
            "maximum_count": (selection([original] * 1000), True),
            "over_limit_across_items": (selection([original] * 501, [original] * 500), False),
        }
        payload = {"rule": rule, "cases": {name: case for name, (case, _) in cases.items()}}
        # Evaluate the shipped predicate with Foundation itself, including
        # Apple's UTI-CONFORMS-TO operator and aggregate key-path semantics.
        script = """
ObjC.import('Foundation');
function run(argv) {
    var payload = JSON.parse(argv[0]);
    var predicate = $.NSPredicate.predicateWithFormat(payload.rule);
    var results = {};
    Object.keys(payload.cases).forEach(function(name) {
        var data = $(JSON.stringify(payload.cases[name])).dataUsingEncoding($.NSUTF8StringEncoding);
        var object = $.NSJSONSerialization.JSONObjectWithDataOptionsError(data, 0, null);
        results[name] = predicate.evaluateWithObject(object);
    });
    return JSON.stringify(results);
}
"""
        completed = subprocess.run(
            ["/usr/bin/osascript", "-l", "JavaScript", "-", json.dumps(payload)],
            input=script, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        results = json.loads(completed.stdout)
        for name, (_, expected) in cases.items():
            with self.subTest(selection=name):
                self.assertIs(results[name], expected)

    @unittest.skipUnless(sys.platform == "darwin", "requires macOS item providers")
    def test_provider_handoff_preserves_original_urls_and_rejects_temporary_copies(self) -> None:
        # Compile the production resolver with fake providers. No request is
        # sent to the app, no manifest is written, and no media file is opened.
        harness = r'''
#import "QuickAction.m"

@interface VTSFakeProvider : NSItemProvider
@property BOOL offersDirectURL;
@property BOOL movie;
@property BOOL folder;
@property BOOL inPlace;
@property (strong) id directValue;
@property (strong) NSError *directError;
@property (strong) NSURL *inPlaceURL;
@property (strong) NSError *inPlaceError;
@property (copy) NSString *requestedType;
@property NSInteger directLoads;
@property NSInteger inPlaceLoads;
@end

@implementation VTSFakeProvider
- (NSArray<NSString *> *)registeredTypeIdentifiers {
    if (self.offersDirectURL) { return @[@"public.file-url"]; }
    if (self.movie) { return @[@"public.mpeg-4"]; }
    if (self.folder) { return @[@"public.folder"]; }
    return @[@"public.image"];
}
- (NSArray<NSString *> *)registeredTypeIdentifiersWithFileOptions:(NSItemProviderFileOptions)options {
    return @[];
}
- (BOOL)hasRepresentationConformingToTypeIdentifier:(NSString *)type fileOptions:(NSItemProviderFileOptions)options {
    return NO;
}
- (BOOL)hasItemConformingToTypeIdentifier:(NSString *)type {
    if ([type isEqualToString:@"public.file-url"]) { return self.offersDirectURL; }
    if ([type isEqualToString:@"public.movie"]) { return self.movie; }
    if ([type isEqualToString:@"public.folder"]) { return self.folder; }
    return NO;
}
- (void)loadItemForTypeIdentifier:(NSString *)type options:(NSDictionary *)options completionHandler:(NSItemProviderCompletionHandler)completion {
    self.directLoads++;
    completion(self.directValue, self.directError);
}
- (NSProgress *)loadInPlaceFileRepresentationForTypeIdentifier:(NSString *)type completionHandler:(void (^)(NSURL *, BOOL, NSError *))completion {
    self.inPlaceLoads++;
    self.requestedType = type;
    completion(self.inPlaceURL, self.inPlace, self.inPlaceError);
    return [NSProgress progressWithTotalUnitCount:1];
}
@end

int main(void) {
    @autoreleasepool {
        NSURL *original = [NSURL fileURLWithPath:@"/tmp/VTS Original Fixture.mp4"];
        NSURL *folder = [NSURL fileURLWithPath:@"/tmp/VTS Original Folder" isDirectory:YES];
        NSURL *temporary = [NSURL fileURLWithPath:@"/tmp/VTS Temporary Copy.mp4"];
        NSURL *remote = [NSURL URLWithString:@"https://example.invalid/fixture.mp4"];
        NSError *error = [NSError errorWithDomain:NSItemProviderErrorDomain code:-1000 userInfo:nil];
        NSArray<NSDictionary *> *cases = @[
            @{ @"name": @"direct_url", @"direct": @YES, @"value": original },
            @{ @"name": @"direct_data", @"direct": @YES, @"value": [original.absoluteString dataUsingEncoding:NSUTF8StringEncoding] },
            @{ @"name": @"direct_string", @"direct": @YES, @"value": original.absoluteString },
            @{ @"name": @"direct_invalid", @"direct": @YES, @"value": remote },
            @{ @"name": @"direct_error_preserved", @"direct": @YES, @"movie": @YES, @"direct_error": error, @"url": original, @"in_place": @YES },
            @{ @"name": @"semantic_movie_unadvertised", @"movie": @YES, @"url": original, @"in_place": @YES },
            @{ @"name": @"semantic_folder_unadvertised", @"folder": @YES, @"url": folder, @"in_place": @YES },
            @{ @"name": @"temporary_copy", @"movie": @YES, @"url": temporary, @"in_place": @NO },
            @{ @"name": @"in_place_error", @"movie": @YES, @"url": original, @"in_place": @YES, @"error": error },
            @{ @"name": @"non_file_url", @"movie": @YES, @"url": remote, @"in_place": @YES },
            @{ @"name": @"missing_url", @"movie": @YES, @"in_place": @YES },
            @{ @"name": @"unsupported_provider", @"url": original, @"in_place": @YES },
        ];
        NSMutableArray *results = [NSMutableArray array];
        for (NSDictionary *test in cases) {
            VTSFakeProvider *provider = [[VTSFakeProvider alloc] init];
            provider.offersDirectURL = [test[@"direct"] boolValue];
            provider.movie = [test[@"movie"] boolValue];
            provider.folder = [test[@"folder"] boolValue];
            provider.inPlace = [test[@"in_place"] boolValue];
            provider.directValue = test[@"value"];
            provider.directError = test[@"direct_error"];
            provider.inPlaceURL = test[@"url"];
            provider.inPlaceError = test[@"error"];
            __block NSURL *resolved = nil;
            __block NSInteger completions = 0;
            VTSLoadOriginalFileURL(provider, ^(NSURL *url) {
                resolved = url;
                completions++;
            });
            [results addObject:@{
                @"name": test[@"name"], @"path": resolved.path ?: (id)NSNull.null,
                @"completions": @(completions), @"direct_loads": @(provider.directLoads),
                @"in_place_loads": @(provider.inPlaceLoads), @"requested_type": provider.requestedType ?: @"",
            }];
        }
        NSData *data = [NSJSONSerialization dataWithJSONObject:results options:0 error:nil];
        puts([[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding].UTF8String);
    }
    return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix="vts-provider-regression-") as directory:
            source = Path(directory) / "provider-regression.m"
            executable = Path(directory) / "provider-regression"
            source.write_text(harness, encoding="utf-8")
            compiled = subprocess.run(
                ["/usr/bin/xcrun", "clang", "-fobjc-arc", "-fblocks", "-framework", "AppKit",
                 "-I", str(ACTION_SOURCE.parent), str(source), "-o", str(executable)],
                capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            completed = subprocess.run([str(executable)], capture_output=True, text=True, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        results = {result["name"]: result for result in json.loads(completed.stdout)}
        original = "/tmp/VTS Original Fixture.mp4"
        expected_paths = {
            "direct_url": original, "direct_data": original, "direct_string": original,
            "semantic_movie_unadvertised": original,
            "semantic_folder_unadvertised": "/tmp/VTS Original Folder",
        }
        for name, result in results.items():
            with self.subTest(provider=name):
                self.assertEqual(result["path"], expected_paths.get(name))
                self.assertEqual(result["completions"], 1)
                if name.startswith("direct_"):
                    self.assertEqual(result["direct_loads"], 1)
                    self.assertEqual(result["in_place_loads"], 0)
                elif name == "unsupported_provider":
                    self.assertEqual(result["in_place_loads"], 0)
                else:
                    self.assertEqual(result["direct_loads"], 0)
                    self.assertEqual(result["in_place_loads"], 1)
                    self.assertEqual(
                        result["requested_type"],
                        "public.folder" if name == "semantic_folder_unadvertised" else "public.movie",
                    )

    def test_action_keeps_original_files_and_uses_existing_job_contract(self) -> None:
        source = ACTION_SOURCE.read_text(encoding="utf-8")
        self.assertIn('hasItemConformingToTypeIdentifier:@"public.file-url"', source)
        self.assertIn('loadItemForTypeIdentifier:@"public.file-url"', source)
        self.assertNotIn("loadFileRepresentationForTypeIdentifier", source)
        self.assertIn("completeRequestReturningItems:context.inputItems", source)
        self.assertIn("VTSIsInsideCameraCard(path)", source)
        self.assertIn('![action isEqualToString:@"video-minutes"]', source)
        for action in EXPECTED_SERVICES.values():
            self.assertIn(f'@"{action}"', source)
        for fragment in (
            '@"version": @3', '@"auto_start": @YES',
            '@"Library/Application Support/VTS/Finder Jobs"',
            '@"vts://finder-job/%@"',
            "withApplicationAtURL:applicationURL",
            "configuration.activates = NO",
        ):
            self.assertIn(fragment, source)


if __name__ == "__main__":
    unittest.main()
