from __future__ import annotations

import plistlib
import re
import unittest
from pathlib import Path


SOURCE_PATH = (
    Path(__file__).resolve().parents[1]
    / "macos"
    / "VTSNativePrototype"
    / "VTSNativePrototype.swift"
)
BUILD_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "build_swift_prototype.sh"
DEPLOY_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "deploy_app_release.sh"
INFO_PLIST_PATH = (
    Path(__file__).resolve().parents[1]
    / "macos"
    / "VTSNativePrototype"
    / "Info.plist"
)


def source_block(source: str, start: str, end: str) -> str:
    return source.split(start, 1)[1].split(end, 1)[0]


def braced_source_range(source: str, pattern: str) -> tuple[int, int, str]:
    """Return one Swift braced expression without depending on indentation."""
    match = re.search(pattern, source)
    if match is None:
        raise AssertionError(f"Swift source pattern was not found: {pattern}")
    opening = source.find("{", match.start())
    if opening < 0:
        raise AssertionError(f"Swift source pattern has no opening brace: {pattern}")

    depth = 0
    for index in range(opening, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return match.start(), index + 1, source[match.start() : index + 1]
    raise AssertionError(f"Swift source pattern has no matching brace: {pattern}")


class SwiftNativeLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = SOURCE_PATH.read_text(encoding="utf-8")
        cls.build_script = BUILD_SCRIPT_PATH.read_text(encoding="utf-8")

    def test_file_workflows_keep_setup_and_preview_side_by_side(self) -> None:
        workflow = source_block(
            self.source,
            "private struct WorkflowModuleView: View",
            "private struct GlobalStatusBar: View",
        )

        self.assertIn("HStack(spacing: 0)", workflow)
        self.assertNotIn("HSplitView", workflow)
        self.assertIn("GeometryReader", workflow)
        self.assertIn("geometry.size.width * 0.4", workflow)
        self.assertIn("Divider()", workflow)
        self.assertIn("controlsColumn", workflow)
        self.assertIn("inspectorColumn", workflow)
        self.assertIn("Label(resolvedInspectorPage.title(for: workflow)", workflow)
        self.assertIn('Picker("Workspace", selection: inspectorSelection)', workflow)
        self.assertIn("max(340", workflow)
        self.assertNotIn("minWidth: 500", workflow)
        self.assertIn("alignment: .top", workflow)
        self.assertIn(".pickerStyle(.segmented)", workflow)
        self.assertIn("page.tabTitle(for: workflow)", workflow)
        self.assertIn('workflow.selectionMode == "none"', workflow)
        self.assertIn("standaloneWorkflow", workflow)

    def test_workflow_setup_scrolls_but_primary_action_stays_pinned(self) -> None:
        workflow = source_block(
            self.source,
            "private struct WorkflowModuleView: View",
            "private struct GlobalStatusBar: View",
        )

        controls = source_block(
            workflow,
            "private var controlsColumn: some View",
            "private var standaloneWorkflow: some View",
        )

        self.assertIn("ScrollView", controls)
        self.assertIn("WorkflowOptionsPanel", workflow)
        self.assertIn("InputQueueView", workflow)
        self.assertIn("Divider()", controls)
        self.assertLess(controls.index("ScrollView"), controls.index("WorkflowRunPanel"))


    def test_long_queues_scroll_and_advanced_options_are_collapsed(self) -> None:
        queue = source_block(
            self.source,
            "private struct InputQueueView: View",
            "private struct NativeVideoPreview: View",
        )
        options = source_block(
            self.source,
            "private struct WorkflowOptionsPanel: View",
            "private struct WorkflowRunPanel: View",
        )

        self.assertIn("ScrollView", queue)
        self.assertIn("LazyVStack", queue)
        self.assertIn('DisclosureGroup("Advanced Options', options)
        self.assertNotIn("ScrollView", options)


    def test_input_queue_exposes_selected_and_accessible_rows(self) -> None:
        queue = source_block(
            self.source,
            "private struct InputQueueRow: View",
            "private struct NativeVideoPreview: View",
        )

        self.assertIn("let selected = model.previewURL(for: workflow)?.path == url.path", queue)
        self.assertIn("selected ? Color.accentColor.opacity", queue)
        self.assertIn(".accessibilityValue(selected ?", queue)
        self.assertIn(".accessibilityAddTraits(selected ? .isSelected : [])", queue)
        self.assertIn('.accessibilityIdentifier("workflow.input.', queue)
        self.assertIn('Button("Remove \\(url.lastPathComponent)"', queue)
        self.assertIn('.accessibilityIdentifier("workflow.input-queue")', queue)


    def test_shared_input_queue_accepts_finder_drag_and_drop(self) -> None:
        queue = source_block(
            self.source,
            "private struct InputQueueView: View",
            "private struct NativeVideoPreview: View",
        )
        view_model = source_block(
            self.source,
            "private final class PrototypeViewModel: ObservableObject",
            "private struct ToolCard: View",
        )

        self.assertIn("@State private var isDropTargeted", queue)
        self.assertIn(".dropDestination(for: URL.self)", queue)
        self.assertIn("model.addWorkflowInputs(urls, to: workflow)", queue)
        self.assertIn("func addWorkflowInputs(_ urls: [URL], to workflow:", view_model)
        self.assertIn("Drop videos or folders here", queue)
        self.assertIn('case "merge": return "1. Clips to Merge"', queue)
        self.assertIn("ForEach(Array(selectedURLs.enumerated())", queue)
        # The queue counter already says "oldest first"; the duplicate
        # caption was removed in the declutter pass.
        self.assertNotIn("Merge order is automatic", queue)
        # The always-on drop hint was removed; the drop target itself remains.

        self.assertIn("private func orderedWorkflowInputs(", view_model)
        self.assertIn('guard workflow.id == "merge"', view_model)
        self.assertIn("private func recordingTimestamp(in url: URL)", view_model)
        self.assertIn("leftDate < rightDate", view_model)
        self.assertNotIn('"(addedCount) item', view_model)


    def test_finder_quick_action_reports_in_a_panel_instead_of_a_window(self) -> None:
        panel = source_block(
            self.source,
            "private final class FinderJobProgressPanelController",
            "private struct FinderJobProgressView: View",
        )

        # A quick action must not steal the screen from the Finder window the
        # operator started in.
        self.assertIn(".nonactivatingPanel", panel)
        self.assertIn("created.level = .floating", panel)
        # Hiding the app would take the panel with it without this.
        self.assertIn("created.canHide = false", panel)
        # A notification covered the panel outright in the top right corner.
        self.assertIn("bottomTrailingOrigin", panel)
        self.assertNotIn("topTrailingOrigin", panel)
        # The agent opens no window, so there is nothing to hide or unhide.
        self.assertNotIn("NSApp.hide(nil)", panel)
        # A job started from the Finder is finished in the Finder: the panel
        # reveals what it produced rather than opening the app.
        self.assertIn("NSWorkspace.shared.activateFileViewerSelecting(urls)", panel)
        self.assertNotIn("openMainWindow", panel)

    def test_finder_panel_shows_the_vts_icon_and_the_job_result(self) -> None:
        view = source_block(
            self.source,
            "private struct FinderJobProgressView: View",
            "\n}\n",
        )

        self.assertIn("Image(nsImage: NSApp.applicationIconImage)", view)
        self.assertIn("model.finderJobTitle", view)
        # Calculating a runtime answers with a number, which belongs on the
        # panel rather than behind a window.
        self.assertIn("model.jobResult", view)
        self.assertIn('model.cancelActiveJob(source: "finder-progress-panel")', view)
        # Only `outputs` is trusted: timestamp's processed_files are source
        # paths that may already have moved into originals/.
        self.assertIn('object["outputs"] as? [String]', view)
        self.assertNotIn('object["processed_files"]', view)
        # A read-only task made nothing, so it offers no reveal.
        self.assertIn("if !targets.isEmpty {", view)
        # Wrapping the panel as one accessibility container hid Reveal and
        # Close from VoiceOver entirely: only the window's own buttons were
        # reachable. The controls carry their own labels instead.
        self.assertNotIn("accessibilityElement(children: .contain)", view)
        # The status line carried each worker's own log, and every line of a
        # different length resized the window mid-job.
        self.assertNotIn("Text(model.jobStatus)", view)
        self.assertIn('guard isFinished else { return "Working…" }', view)
        # A HUD that resizes under a changing status line is worse than one
        # that says less, so its size is pinned.
        self.assertIn("height: 84", view)
        # A result worth reading, and any failure, must not close itself.
        # Dismissing a panel whose Reveal button was never clicked throws the
        # button away, so an output to open keeps the panel up too -- and the
        # check happens after the wait, because the result is a separate event
        # that can be applied after the outcome.
        dismissal = view.split(".onChange(of: model.jobOutcome)", 1)[1]
        wait_at = dismissal.index("Task.sleep")
        check_at = dismissal.index("guard readableResult == nil, revealTargets.isEmpty")
        self.assertLess(wait_at, check_at)
        # A workflow's machine-readable record filled the panel with braces and
        # absolute paths, so only a sentence reaches it. A record may carry a
        # `summary` for an outcome its counts would misreport -- a timestamp
        # run that skipped every clip -- and that sentence is shown.
        self.assertIn('!trimmed.hasPrefix("{")', view)
        self.assertIn('object["summary"] as? String', view)
        self.assertIn("outcome == .succeeded || outcome == .cancelled", view)

    def test_menu_bar_agent_opens_no_window_until_one_is_asked_for(self) -> None:
        delegate = source_block(
            self.source,
            "private final class VTSAppDelegate",
            "private final class VTSWindowOpener",
        )
        opener = source_block(
            self.source,
            "private final class VTSWindowOpener",
            "private enum VTSLoginItem",
        )

        # Right-clicking is the ordinary way in, so a launch shows nothing.
        scene = source_block(
            self.source, "struct VTSApp: App", "\n}\n"
        )
        # A Window scene here is a second window owner: suppressed at launch it
        # still built one of its own once the app activated, and two appeared.
        self.assertNotIn("Window(", scene)
        self.assertIn("Settings {", scene)
        self.assertIn("VTSMenuBarController.shared.install()", delegate)
        # So the opener builds and keeps the only window there is.
        self.assertIn("NSHostingController(", opener)
        self.assertIn("if let window { return window }", opener)
        # With no window on screen there is no view to carry onOpenURL, so the
        # Finder's jobs must arrive through the delegate instead.
        self.assertNotIn(".onOpenURL", self.source)
        self.assertIn("func application(_ application: NSApplication, open urls: [URL])", delegate)
        self.assertIn("PrototypeViewModel.shared", delegate)
        # Closing a settings window must not quit an agent.
        self.assertIn("applicationShouldTerminateAfterLastWindowClosed", delegate)
        # A real window needs a real menu bar; the agent gets one back after.
        self.assertIn("NSApp.setActivationPolicy(.regular)", opener)
        self.assertIn("NSApp.setActivationPolicy(.accessory)", opener)

    def test_the_menu_bar_item_cannot_hide_behind_the_notch(self) -> None:
        controller = source_block(
            self.source,
            "private final class VTSMenuBarController",
            "private enum VTSMenuBarIcon",
        )

        # SwiftUI's MenuBarExtra chose the position, and on a full menu bar it
        # chose one behind the notch, where the item drew nothing at all. The
        # scene must not go back to it; the comment saying why may stay.
        scene = source_block(
            self.source, "struct VTSApp: App", "\n}\n"
        )
        self.assertNotIn("MenuBarExtra", scene)
        self.assertIn("NSStatusBar.system.statusItem", controller)
        # Measured: without a seeded position the item lands at x=755 on a
        # 1512-point screen and is invisible; with one it lands at x=1295.
        self.assertIn('"NSStatusItem Preferred Position VTS"', controller)
        self.assertIn("guard defaults.object(forKey: preferredPositionKey) == nil else { return }", controller)
        # macOS only remembers an item that has a name.
        self.assertIn('item.autosaveName = "VTS"', controller)
        self.assertIn("item.isVisible = true", controller)
        # An item that draws nothing looks exactly like a broken install.
        self.assertIn('button.title = "VTS"', controller)

    def test_menu_bar_icon_is_a_template_symbol_not_the_filled_app_tile(self) -> None:
        icon = source_block(
            self.source,
            "private enum VTSMenuBarIcon",
            "private struct FinderJobProgressView",
        )

        # The app icon is a filled black tile, which a menu bar would render as
        # a solid blob. The panel still fronts the real logo.
        self.assertIn("systemSymbolName:", icon)
        self.assertIn("symbol.isTemplate = true", icon)
        self.assertNotIn("applicationIconImage", icon)

    def test_the_app_ships_as_a_menu_bar_agent(self) -> None:
        info = plistlib.loads(INFO_PLIST_PATH.read_bytes())

        # Work starts from the Finder, so the app carries no Dock icon.
        self.assertIs(info.get("LSUIElement"), True)
        # The Finder extension reaches the app by URL, which still has to be
        # declared for a job to arrive at all.
        schemes = [
            scheme
            for entry in info.get("CFBundleURLTypes", [])
            for scheme in entry.get("CFBundleURLSchemes", [])
        ]
        self.assertIn("vts", schemes)


    def test_one_model_serves_the_window_and_the_finder(self) -> None:
        self.assertIn("static let shared = PrototypeViewModel()", self.source)
        self.assertIn(
            "@StateObject private var model = PrototypeViewModel.shared", self.source
        )
        self.assertNotIn("@StateObject private var model = PrototypeViewModel()", self.source)

    def test_auto_started_job_shows_only_its_panel(self) -> None:
        model = braced_source_range(
            self.source, r"func openFinderJob\(_ url: URL\) async -> String\?"
        )[2]

        self.assertIn(
            "FinderJobProgressPanelController.shared.present(model: self)", model
        )
        self.assertIn("finderJobTitle = workflow.title", model)


    def test_media_inspection_queue_also_accepts_video_drops(self) -> None:
        status = source_block(
            self.source,
            "private struct SystemStatusView: View",
            "private struct InputQueueView: View",
        )

        self.assertIn("@State private var isInspectionDropTargeted", status)
        self.assertIn(".dropDestination(for: URL.self)", status)
        self.assertIn("model.addInspectionInputs(urls)", status)
        self.assertIn("Drop videos here", status)

    def test_recovered_job_options_are_pruned_to_the_current_schema(self) -> None:
        view_model = source_block(
            self.source,
            "private final class PrototypeViewModel: ObservableObject",
            "private struct ToolCard: View",
        )
        defaults = source_block(
            view_model,
            "private func installMissingDefaults(from workflows:",
            "private func applyPreferences",
        )

        self.assertIn("let allowedKeys = Set(workflow.options.map(\\.key))", defaults)
        self.assertIn("allowedKeys.contains($0.key)", defaults)

    def test_direct_trim_files_do_not_show_a_second_queue(self) -> None:
        workflow = source_block(
            self.source,
            "private struct WorkflowModuleView: View",
            "private struct GlobalStatusBar: View",
        )
        trim_details = source_block(
            self.source,
            "private struct NativeTrimQueueView: View",
            "private struct AIDetectionSetupView: View",
        )

        self.assertIn('workflow.id == "trim", !model.trimCandidates.isEmpty', workflow)
        self.assertIn('Label("1. Clips to Trim"', trim_details)
        self.assertIn('.accessibilityIdentifier("workflow.trim-queue")', trim_details)
        self.assertIn("model.addWorkflowInputs(urls, to: workflow)", trim_details)
        self.assertNotIn('Label("Videos Found in Folder"', trim_details)

    def test_non_trim_previews_do_not_write_trim_recovery_state(self) -> None:
        preview = source_block(
            self.source,
            "private struct NativeVideoPreview: View",
            "private struct NativeTrimQueueView: View",
        )

        self.assertIn('private var isTrim: Bool { workflow.id == "trim" }', preview)
        self.assertEqual(preview.count("model.installTrimDuration"), 1)
        self.assertRegex(
            preview,
            r"if\s+isTrim\s*\{\s*model\.installTrimDuration\(seconds,\s*for:\s*url\)\s*\}",
        )

    def test_process_start_failure_cleans_up_every_busy_resource(self) -> None:
        view_model = source_block(
            self.source,
            "private final class PrototypeViewModel: ObservableObject",
            "private struct ToolCard: View",
        )
        start_job = source_block(
            view_model,
            "private func startJobProcess(",
            "func cancelActiveJob(source: String)",
        )
        after_run = start_job.split("try process.run()", 1)[1]
        cleanup = after_run.split("throw error", 1)[0]

        for statement in (
            "output.fileHandleForReading.readabilityHandler = nil",
            "errors.fileHandleForReading.readabilityHandler = nil",
            "process.terminationHandler = nil",
            "jobProcess = nil",
            "jobOutputPipe = nil",
            "jobErrorPipe = nil",
            "launchingWorkflowID = nil",
            "activeWorkflowID = nil",
            "isWorking = false",
        ):
            self.assertIn(statement, cleanup)


    def test_recovered_trim_options_win_over_initial_saved_preferences(self) -> None:
        view_model = source_block(
            self.source,
            "private final class PrototypeViewModel: ObservableObject",
            "private struct ToolCard: View",
        )
        preferences = source_block(
            view_model,
            "private func applyPreferences(",
            "var settingsEntries:",
        )
        restore = source_block(
            view_model,
            "private func restoreTrimSession()",
            "private func scheduleTrimSessionSave()",
        )
        clear = source_block(
            view_model,
            "private func clearPersistedTrimSession()",
            "private func trimSignature(",
        )

        self.assertIn("recoveredTrimOptionKeys = Set(snapshot.options.keys)", restore)
        self.assertIn('workflow.id == "trim"', preferences)
        self.assertIn("recoveredTrimOptionKeys.contains(option.key)", preferences)
        self.assertIn("continue", preferences)
        self.assertIn("recoveredTrimOptionKeys.removeAll()", clear)

    def test_errors_surface_in_workflow_activity_and_global_status(self) -> None:
        run_panel = source_block(
            self.source,
            "private struct WorkflowRunPanel: View",
            "private struct WorkflowInspectorPlaceholder: View",
        )
        activity = source_block(
            self.source,
            "private struct JobActivityView: View",
            "private struct WorkflowOptionEditor: View",
        )
        global_status = source_block(
            self.source,
            "private struct GlobalStatusBar: View",
            "private struct ContentView: View",
        )

        self.assertIn("InlineMessageBanner(message: error, tone: .failure)", run_panel)
        self.assertIn("model.dismissWorkflowError(for: workflow)", run_panel)
        self.assertIn("model.jobOutcome.tone", activity)
        self.assertIn("title: model.jobOutcome.title", activity)
        self.assertIn("model.errorMessage != nil { return .failure }", global_status)
        self.assertIn("if let error = model.errorMessage { return error }", global_status)
        self.assertIn('.accessibilityIdentifier("global.status")', global_status)

    def test_errors_are_scoped_to_their_product_area(self) -> None:
        view_model = source_block(
            self.source,
            "private final class PrototypeViewModel: ObservableObject",
            "private struct ToolCard: View",
        )
        bridge = source_block(
            self.source,
            "private struct SystemStatusView: View",
            "private struct InputQueueView: View",
        )
        settings = source_block(
            self.source,
            "private struct SettingsPanelView: View",
            "private enum WorkflowInspectorPage",
        )

        for state in (
            "engineErrorMessage",
            "inspectionErrorMessage",
            "settingsErrorMessage",
            "workflowErrors",
            "jobErrorMessage",
        ):
            self.assertIn(state, view_model)
        self.assertIn("model.engineErrorMessage", bridge)
        self.assertIn("model.inspectionErrorMessage", bridge)
        self.assertIn("model.settingsErrorMessage", settings)


    def test_settings_dirty_state_controls_save_and_sidebar_indicator(self) -> None:
        view_model = source_block(
            self.source,
            "private final class PrototypeViewModel: ObservableObject",
            "private struct ToolCard: View",
        )
        settings = source_block(
            self.source,
            "private struct SettingsPanelView: View",
            "private enum WorkflowInspectorPage",
        )
        save_settings = source_block(
            view_model,
            "func saveSettings() async",
            "func validationMessage(for workflow: WorkflowStatus)",
        )
        content = source_block(
            self.source,
            "private struct ContentView: View",
            "@main",
        )

        self.assertIn("private var savedSettingsValues", view_model)
        self.assertIn("var hasUnsavedSettings: Bool", view_model)
        self.assertIn("currentSettingsValues != savedSettingsValues", view_model)
        self.assertIn("savedSettingsValues = currentSettingsValues", save_settings)
        self.assertIn("model.hasUnsavedSettings ?", settings)
        self.assertIn("!model.hasUnsavedSettings", settings)
        self.assertIn('.accessibilityIdentifier("settings.save")', settings)
        self.assertIn("showResetConfirmation", settings)
        self.assertIn("if model.hasUnsavedSettings", content)
        self.assertIn('.accessibilityLabel("Unsaved settings")', content)


    def test_build_script_pins_sdk_and_uses_a_writable_module_cache(self) -> None:
        script = self.build_script

        self.assertIn('MODULE_CACHE_PATH="${VTS_PROTOTYPE_MODULE_CACHE:', script)
        self.assertIn('VTS_PROTOTYPE_SDK', script)
        self.assertIn('xcrun --sdk macosx --show-sdk-path', script)
        self.assertIn('"$ENGINE_TOOLS_PATH" "$MODULE_CACHE_PATH"', script)
        self.assertIn('CLANG_MODULE_CACHE_PATH="$MODULE_CACHE_PATH"', script)
        self.assertIn('-sdk "$SDK_PATH"', script)


if __name__ == "__main__":
    unittest.main()


class JobOutputOrderingTests(unittest.TestCase):
    """stdout, stderr and termination must reach the UI in the order they happened.

    Three independent `Task { @MainActor }` hops had no ordering between them.
    With a small payload it never showed; with a large one the termination hop
    routinely overtook the output it followed and tore down the buffer.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = SOURCE_PATH.read_text(encoding="utf-8")

    def test_job_output_is_funnelled_through_one_ordered_stream(self) -> None:
        self.assertIn("private enum JobStreamEvent", self.source)
        self.assertIn("case output(Data)", self.source)
        self.assertIn("case terminated(Process)", self.source)
        self.assertIn("AsyncStream<JobStreamEvent>(bufferingPolicy: .unbounded)", self.source)

    def test_no_handler_hops_to_the_main_actor_on_its_own(self) -> None:
        for stray in (
            "Task { @MainActor in self?.consumeJobOutput(",
            "Task { @MainActor in self?.jobDidTerminate(",
            "Task { @MainActor in self?.appendJobLog(",
        ):
            with self.subTest(stray=stray):
                self.assertNotIn(stray, self.source)

    def test_termination_is_yielded_into_the_same_stream(self) -> None:
        self.assertIn("continuation.yield(.terminated(finished))", self.source)
        self.assertIn("continuation.yield(.output(data))", self.source)
