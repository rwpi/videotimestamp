import AppKit
import AVFoundation
import AVKit
import Foundation
import ServiceManagement
import SwiftUI
import UniformTypeIdentifiers

private enum JSONValue: Codable, Hashable {
    case string(String)
    case bool(Bool)
    case number(Double)
    case null

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() {
            self = .null
        } else if let value = try? container.decode(Bool.self) {
            self = .bool(value)
        } else if let value = try? container.decode(Double.self) {
            self = .number(value)
        } else if let value = try? container.decode(String.self) {
            self = .string(value)
        } else {
            throw DecodingError.typeMismatch(
                JSONValue.self,
                DecodingError.Context(
                    codingPath: decoder.codingPath,
                    debugDescription: "Workflow values must be strings, numbers, booleans, or null."
                )
            )
        }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .string(let value): try container.encode(value)
        case .bool(let value): try container.encode(value)
        case .number(let value): try container.encode(value)
        case .null: try container.encodeNil()
        }
    }

    var anyValue: Any {
        switch self {
        case .string(let value): return value
        case .bool(let value): return value
        case .number(let value): return value
        case .null: return NSNull()
        }
    }

    var stringValue: String {
        switch self {
        case .string(let value): return value
        case .number(let value): return String(format: "%g", value)
        case .bool(let value): return value ? "true" : "false"
        case .null: return ""
        }
    }

    var boolValue: Bool {
        if case .bool(let value) = self { return value }
        return false
    }

    var numberValue: Double {
        if case .number(let value) = self { return value }
        return 0
    }
}

private struct EngineInfo: Decodable {
    let name: String
    let pythonVersion: String
    let pythonExecutable: String
    let platform: String
    let machine: String
    let headless: Bool

    enum CodingKeys: String, CodingKey {
        case name
        case pythonVersion = "python_version"
        case pythonExecutable = "python_executable"
        case platform
        case machine
        case headless
    }
}

private struct ToolStatus: Decodable {
    let command: String
    let resolvedPath: String?
    let available: Bool
    let version: String?

    enum CodingKeys: String, CodingKey {
        case command
        case resolvedPath = "resolved_path"
        case available
        case version
    }
}

private struct WorkflowChoice: Decodable, Hashable, Identifiable {
    let value: JSONValue
    let label: String
    var id: String { "\(label)-\(value.stringValue)" }
}

private struct WorkflowOptionDefinition: Decodable, Identifiable {
    let key: String
    var label: String
    let kind: String
    let defaultValue: JSONValue
    var helpText: String
    let choices: [WorkflowChoice]
    let minimum: Double?
    let maximum: Double?
    let step: Double?
    let required: Bool
    let pathMode: String?
    let preferenceID: String?
    let placement: String
    var settingsSection: String?

    var id: String { key }

    enum CodingKeys: String, CodingKey {
        case key
        case label
        case kind
        case defaultValue = "default"
        case helpText = "help"
        case choices
        case minimum
        case maximum
        case step
        case required
        case pathMode = "path_mode"
        case preferenceID = "preference_id"
        case placement
        case settingsSection = "settings_section"
    }
}

private struct WorkflowStatus: Decodable, Identifiable {
    let id: String
    var title: String
    var category: String
    var symbol: String
    var summary: String
    let selectionMode: String
    var launchLabel: String
    let executionMode: String
    var options: [WorkflowOptionDefinition]
    let interactiveNote: String?
    let visible: Bool?
    let bridgeStatus: String

    enum CodingKeys: String, CodingKey {
        case id
        case title
        case category
        case symbol
        case summary
        case selectionMode = "selection_mode"
        case launchLabel = "launch_label"
        case executionMode = "execution_mode"
        case options
        case interactiveNote = "interactive_note"
        case visible
        case bridgeStatus = "bridge_status"
    }
}

private struct SettingsOptionEntry: Identifiable {
    let workflow: WorkflowStatus
    let option: WorkflowOptionDefinition
    var id: String { option.preferenceID ?? "\(workflow.id).\(option.key)" }
}

private struct EngineErrorPayload: Decodable {
    let code: String
    let message: String
}

private struct CapabilitiesResponse: Decodable {
    let ok: Bool
    let protocolVersion: Int
    let workflowSchemaVersion: Int?
    let engine: EngineInfo?
    let tools: [String: ToolStatus]?
    let workflows: [WorkflowStatus]?
    let error: EngineErrorPayload?

    enum CodingKeys: String, CodingKey {
        case ok
        case protocolVersion = "protocol_version"
        case workflowSchemaVersion = "workflow_schema_version"
        case engine
        case tools
        case workflows
        case error
    }
}

private struct VideoInspection: Decodable, Identifiable {
    var id: String { path }
    let path: String
    let name: String
    let extensionName: String
    let supportedExtension: Bool
    let exists: Bool
    let isFile: Bool
    let sizeBytes: Int64?
    let durationSeconds: Double?
    let formatName: String?
    let width: Int?
    let height: Int?
    let dates: [String: String]
    let warnings: [String]

    enum CodingKeys: String, CodingKey {
        case path
        case name
        case extensionName = "extension"
        case supportedExtension = "supported_extension"
        case exists
        case isFile = "is_file"
        case sizeBytes = "size_bytes"
        case durationSeconds = "duration_seconds"
        case formatName = "format_name"
        case width
        case height
        case dates
        case warnings
    }
}

private struct InspectionResponse: Decodable {
    let ok: Bool
    let files: [VideoInspection]?
    let error: EngineErrorPayload?
}

private struct PreferencesResponse: Decodable {
    let ok: Bool
    let preferences: [String: JSONValue]?
    let error: EngineErrorPayload?
}

private struct TrimRange: Codable, Equatable, Sendable {
    var start: Double
    var end: Double
    var duration: Double
    var edited: Bool
}

private struct TrimRecoverySnapshot: Codable {
    let savedAt: String
    let ranges: [String: TrimRange]
    let selectedPaths: [String]
    let options: [String: JSONValue]
}

private struct VideoRuntimePayload: Decodable {
    let kind: String
    let totalSeconds: Double
    let subjectSeconds: Double
    let integrityClips: Int
    let unknownDurationClips: Int
    let clipCount: Int

    enum CodingKeys: String, CodingKey {
        case kind
        case totalSeconds = "total_seconds"
        case subjectSeconds = "subject_seconds"
        case integrityClips = "integrity_clips"
        case unknownDurationClips = "unknown_duration_clips"
        case clipCount = "clip_count"
    }

    /// Renders a duration the way someone reading a runtime total would say it,
    /// dropping the units that are zero rather than padding them with zeroes.
    static func readableDuration(_ seconds: Double) -> String {
        let whole = Int(seconds.rounded())
        let hours = whole / 3600
        let minutes = (whole % 3600) / 60
        let remainder = whole % 60
        var parts: [String] = []
        if hours > 0 { parts.append("\(hours) hr") }
        if minutes > 0 { parts.append("\(minutes) min") }
        if remainder > 0 || parts.isEmpty { parts.append("\(remainder) sec") }
        return parts.joined(separator: " ")
    }

    var summary: String {
        let clipLabel = clipCount == 1 ? "1 clip" : "\(clipCount) clips"
        var lines = ["Total runtime: \(Self.readableDuration(totalSeconds))  ·  \(clipLabel)"]
        if subjectSeconds > 0 {
            lines.append("SUBJECT: \(Self.readableDuration(subjectSeconds))")
        }
        if integrityClips > 0 {
            let label = integrityClips == 1 ? "clip" : "clips"
            lines.append("Integrity: \(integrityClips) \(label)")
        }
        // Silence here would be misleading: these clips contributed nothing to
        // the total, so the total is short by an unknown amount.
        if unknownDurationClips > 0 {
            let label = unknownDurationClips == 1
                ? "1 clip has no readable duration and is not counted above"
                : "\(unknownDurationClips) clips have no readable duration and are not counted above"
            lines.append(label)
        }
        return lines.joined(separator: "\n")
    }
}

private struct TrimSetupClip: Decodable, Identifiable {
    let path: String
    let duration: Double
    let suggestedStart: Double
    let suggestedEnd: Double

    var id: String { path }

    enum CodingKeys: String, CodingKey {
        case path
        case duration
        case suggestedStart = "suggested_start"
        case suggestedEnd = "suggested_end"
    }
}

private struct TrimSetupResponse: Decodable {
    let ok: Bool
    let clips: [TrimSetupClip]?
    let error: EngineErrorPayload?
}

private struct FinderQuickActionResponse: Decodable {
    let bundleID: String
    let installed: Bool
    let election: String

    enum CodingKeys: String, CodingKey {
        case bundleID = "bundle_id"
        case installed
        case election
    }
}

private struct FinderExtensionResponse: Decodable {
    let ok: Bool
    let installed: Bool?
    let enabled: Bool?
    let election: String?
    let quickActions: [FinderQuickActionResponse]?
    let extensionPath: String?
    let error: EngineErrorPayload?

    enum CodingKeys: String, CodingKey {
        case ok
        case installed
        case enabled
        case election
        case quickActions = "quick_actions"
        case extensionPath = "extension_path"
        case error
    }
}

private struct FinderJobManifest: Decodable {
    let version: Int
    let jobID: String
    let action: String
    let paths: [String]
    let options: [String: JSONValue]?
    let autoStart: Bool?

    enum CodingKeys: String, CodingKey {
        case version
        case jobID = "job_id"
        case action
        case paths
        case options
        case autoStart = "auto_start"
    }
}

private enum EngineClientError: LocalizedError {
    case missingConfiguration(String)
    case invalidResponse(String)
    case engine(String)

    var errorDescription: String? {
        switch self {
        case .missingConfiguration(let message), .invalidResponse(let message), .engine(let message):
            return message
        }
    }
}

/// The two Python programs the app starts. A packaged build reaches both
/// through the single executable it ships; a development build runs the
/// matching script out of the checkout.
private enum EngineEntryPoint {
    case engine
    case jobRunner

    var developmentScript: String {
        switch self {
        case .engine: return "vts_engine.py"
        case .jobRunner: return "vts_job_runner.py"
        }
    }

    var packagedArguments: [String] {
        switch self {
        case .engine: return ["--request"]
        case .jobRunner: return ["--job-runner", "--request"]
        }
    }
}

private struct EngineClient {
    /// Where the engine's code and interpreter come from.
    enum Runtime {
        /// A packaged release carries both inside the app bundle.
        case packaged(executable: URL)
        /// A development build runs this Mac's checkout and interpreter.
        case development(root: URL, python: URL)
    }

    let runtime: Runtime
    let resourceRootURL: URL?

    /// Python resolves relative paths and its own module search against this.
    var workingDirectoryURL: URL {
        switch runtime {
        case .packaged(let executable): return executable.deletingLastPathComponent()
        case .development(let root, _): return root
        }
    }

    func command(for entryPoint: EngineEntryPoint) -> (executable: URL, arguments: [String]) {
        switch runtime {
        case .packaged(let executable):
            return (executable, entryPoint.packagedArguments)
        case .development(let root, let python):
            return (
                python,
                [root.appendingPathComponent(entryPoint.developmentScript).path, "--request"]
            )
        }
    }

    var processEnvironment: [String: String] {
        var environment = ProcessInfo.processInfo.environment
        if let resourceRootURL {
            environment["VTS_ENGINE_RESOURCE_ROOT"] = resourceRootURL.path
        }
        if let extensionURL = Bundle.main.builtInPlugInsURL?
            .appendingPathComponent("VTSFinderExtension.appex", isDirectory: true),
           FileManager.default.fileExists(atPath: extensionURL.path) {
            environment["VTS_FINDER_EXTENSION_PATH"] = extensionURL.path
        }
        return environment
    }

    static func resolvedClient() throws -> EngineClient {
        let packagedTools = Bundle.main.resourceURL?
            .appendingPathComponent("engine-tools", isDirectory: true)
        let resourceRoot = packagedTools.flatMap {
            FileManager.default.fileExists(atPath: $0.path) ? $0 : nil
        }

        // A packaged release runs the engine it ships with. Looking at the
        // development keys first is what shipped a release that tried to run a
        // checkout and a Homebrew interpreter that exist on no other Mac.
        if let engine = Bundle.main.resourceURL?
            .appendingPathComponent("engine", isDirectory: true)
            .appendingPathComponent("vts-engine"),
           FileManager.default.isExecutableFile(atPath: engine.path) {
            return EngineClient(
                runtime: .packaged(executable: engine),
                resourceRootURL: resourceRoot
            )
        }

        // Development builds deliberately run this checkout instead, so an edit
        // to a Python module takes effect without rebuilding the app.
        guard let root = Bundle.main.object(forInfoDictionaryKey: "VTSDevelopmentRoot") as? String else {
            throw EngineClientError.missingConfiguration("The VTS application bundle is missing its engine root configuration.")
        }
        guard let python = Bundle.main.object(forInfoDictionaryKey: "VTSDevelopmentPython") as? String else {
            throw EngineClientError.missingConfiguration("The VTS application bundle is missing its Python engine configuration.")
        }
        return EngineClient(
            runtime: .development(
                root: URL(fileURLWithPath: root, isDirectory: true),
                python: URL(fileURLWithPath: python)
            ),
            resourceRootURL: resourceRoot
        )
    }

    func send<Response: Decodable>(_ request: [String: Any], as type: Response.Type) async throws -> Response {
        let launch = command(for: .engine)
        let workingDirectoryURL = self.workingDirectoryURL
        return try await Task.detached(priority: .userInitiated) {
            let requestData = try JSONSerialization.data(withJSONObject: request)
            let process = Process()
            let standardInput = Pipe()
            let standardOutput = Pipe()
            let standardError = Pipe()
            process.executableURL = launch.executable
            process.arguments = launch.arguments
            process.currentDirectoryURL = workingDirectoryURL
            process.environment = self.processEnvironment
            process.standardInput = standardInput
            process.standardOutput = standardOutput
            process.standardError = standardError

            try process.run()
            standardInput.fileHandleForWriting.write(requestData)
            try standardInput.fileHandleForWriting.close()
            let output = standardOutput.fileHandleForReading.readDataToEndOfFile()
            let errorOutput = standardError.fileHandleForReading.readDataToEndOfFile()
            process.waitUntilExit()
            guard !output.isEmpty else {
                let detail = String(data: errorOutput, encoding: .utf8) ?? "No output"
                throw EngineClientError.invalidResponse("Python engine returned no JSON: \(detail)")
            }
            do {
                return try JSONDecoder().decode(Response.self, from: output)
            } catch {
                let rawOutput = String(data: output, encoding: .utf8) ?? "Unreadable output"
                throw EngineClientError.invalidResponse("Could not decode the Python response: \(error)\n\(rawOutput)")
            }
        }.value
    }
}

private enum VTSMetrics {
    static let compactSpacing: CGFloat = 6
    static let spacing: CGFloat = 10
    static let sectionSpacing: CGFloat = 14
    static let panelPadding: CGFloat = 12
    static let pagePadding: CGFloat = 16
    static let rowRadius: CGFloat = 8
    static let panelRadius: CGFloat = 11
}

private enum VTSStatusTone {
    case neutral
    case ready
    case attention
    case running
    case success
    case failure

    var color: Color {
        switch self {
        case .neutral: return .secondary
        case .ready, .success: return .green
        case .attention: return .orange
        case .running: return Color.accentColor
        case .failure: return .red
        }
    }

    var symbol: String {
        switch self {
        case .neutral: return "circle.dotted"
        case .ready: return "checkmark.circle.fill"
        case .attention: return "exclamationmark.circle.fill"
        case .running: return "gearshape.2.fill"
        case .success: return "checkmark.seal.fill"
        case .failure: return "xmark.octagon.fill"
        }
    }
}

private enum JobOutcome: String {
    case idle
    case running
    case succeeded
    case failed
    case cancelled

    var title: String {
        switch self {
        case .idle: return "Not Run"
        case .running: return "Running"
        case .succeeded: return "Complete"
        case .failed: return "Failed"
        case .cancelled: return "Cancelled"
        }
    }

    var tone: VTSStatusTone {
        switch self {
        case .idle, .cancelled: return .neutral
        case .running: return .running
        case .succeeded: return .success
        case .failed: return .failure
        }
    }
}

private struct WorkflowDisplayStatus {
    let title: String
    let detail: String
    let tone: VTSStatusTone
}

private struct StatusPill: View {
    let title: String
    let tone: VTSStatusTone

    var body: some View {
        Label(title.uppercased(), systemImage: tone.symbol)
            .font(.caption2.bold())
            .foregroundStyle(tone.color)
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background(tone.color.opacity(0.10), in: Capsule())
            .accessibilityElement(children: .combine)
            .accessibilityLabel("Status")
            .accessibilityValue(title)
    }
}

private struct InlineMessageBanner: View {
    let message: String
    let tone: VTSStatusTone
    var dismiss: (() -> Void)?

    var body: some View {
        HStack(alignment: .top, spacing: 9) {
            Image(systemName: tone.symbol)
                .foregroundStyle(tone.color)
                .accessibilityHidden(true)
            Text(message)
                .font(.callout)
                .fixedSize(horizontal: false, vertical: true)
                // The minimum width matters: `fixedSize` makes this text report
                // its full wrapped height for whatever width it is offered, and a
                // greedy container asks for the height at a near-zero width first.
                // Without a floor the message wraps to one character per line and
                // the resulting height starves every sibling view in the window.
                .frame(minWidth: 260, maxWidth: .infinity, alignment: .leading)
            if let dismiss {
                Button("Dismiss", systemImage: "xmark") { dismiss() }
                    .labelStyle(.iconOnly)
                    .buttonStyle(.plain)
                    .help("Dismiss message")
                    .accessibilityLabel("Dismiss message")
            }
        }
        .padding(VTSMetrics.spacing)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(tone.color.opacity(0.09), in: RoundedRectangle(cornerRadius: VTSMetrics.rowRadius))
        .overlay(
            RoundedRectangle(cornerRadius: VTSMetrics.rowRadius)
                .stroke(tone.color.opacity(0.25), lineWidth: 1)
        )
        .accessibilityElement(children: .combine)
    }
}

private struct PolishedEmptyState: View {
    let title: String
    let message: String
    let symbol: String
    var actionTitle: String?
    var action: (() -> Void)?

    var body: some View {
        VStack(spacing: 9) {
            Image(systemName: symbol)
                .font(.system(size: 28, weight: .light))
                .foregroundStyle(.secondary)
                .accessibilityHidden(true)
            Text(title)
                .font(.headline)
            Text(message)
                .font(.callout)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 360)
            if let actionTitle, let action {
                Button(actionTitle, action: action)
                    .controlSize(.small)
            }
        }
        .padding(VTSMetrics.sectionSpacing)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .accessibilityElement(children: .combine)
    }
}

/// One ordered channel for everything a running job says.
///
/// stdout, stderr and process termination arrive on three different Foundation
/// queues. Hopping each to the main actor with its own unstructured `Task` puts
/// no ordering between them, and both failure modes are real: interleaved byte
/// chunks corrupt a JSON line mid-object, and a termination that overtakes the
/// output it follows tears down the buffer before the last groups are parsed --
/// the job reports success and shows no result. Funnelling all three
/// through a single stream with one consumer restores the order they happened
/// in, which is the order the parser has always assumed.
private enum JobStreamEvent {
    case output(Data)
    case log(String)
    case terminated(Process)
}

/// Every published value feeds SwiftUI. Keeping the model on the main actor is
/// not cosmetic: AVFoundation and subprocess continuations resume on arbitrary
/// queues, and publishing from those queues produces runtime warnings.
@MainActor
private final class PrototypeViewModel: ObservableObject {
    /// The app is a menu bar agent, so a Finder job can arrive before any
    /// window exists and has to reach the model through the app delegate.
    /// One instance keeps that path and the window on the same state.
    static let shared = PrototypeViewModel()

    @Published var capabilities: CapabilitiesResponse?
    @Published var selectedURLs: [URL] = []
    @Published var inspections: [VideoInspection] = []
    @Published var isInspecting = false
    @Published var inspectionErrorMessage: String?
    @Published var isWorking = false
    @Published var message = "Checking local processing components…"
    @Published var errorMessage: String?
    @Published var engineErrorMessage: String?
    @Published var workflowSelections: [String: [URL]] = [:]
    @Published var workflowOptionValues: [String: [String: JSONValue]] = [:]
    @Published var workflowMessages: [String: String] = [:]
    @Published var workflowErrors: [String: String] = [:]
    @Published var launchingWorkflowID: String?
    @Published var isSavingSettings = false
    @Published var settingsErrorMessage: String?
    @Published var settingsMessage = "Saved settings are shared across VTS workflows."
    @Published var workflowPreviewURLs: [String: URL] = [:]
    @Published var trimRanges: [String: TrimRange] = [:]
    @Published var trimCandidates: [TrimSetupClip] = []
    @Published var isPreparingTrim = false
    @Published var trimSetupMessage = "Choose a queue to load its clips."
    @Published var activeWorkflowID: String?
    @Published var lastJobWorkflowID: String?
    @Published var jobProgress = 0.0
    @Published var jobStatus = "Ready"
    @Published var jobOutcome: JobOutcome = .idle
    @Published var jobErrorMessage: String?
    @Published var jobLogs: [String] = []
    @Published var jobResult: String?
    @Published var jobOperation: String?
    @Published var jobStage: String?
    /// Names the job in the Finder progress panel, which has no sidebar to say
    /// which tool is running.
    @Published var finderJobTitle: String?

    @Published var finderExtensionEnabled = false
    @Published var finderExtensionStatus = "Checking the VTS Finder extension…"
    @Published var isUpdatingFinderExtension = false

    var jobProgressLabel: String {
        if jobProgress > 0, jobProgress < 1 { return "<1%" }
        if jobProgress > 0, jobProgress < 10 {
            return String(format: "%.1f%%", jobProgress)
        }
        return "\(Int(jobProgress.rounded()))%"
    }
    @Published var requestedSettingsSection: String?
    @Published var requestedWorkflowID: String?

    private var client: EngineClient?
    private var jobProcess: Process?
    private var jobOutputPipe: Pipe?
    private var jobErrorPipe: Pipe?
    private var jobOutputBuffer = Data()
    private var jobOutputScanOffset = 0
    private var jobEventTask: Task<Void, Never>?
    private var jobEventContinuation: AsyncStream<JobStreamEvent>.Continuation?
    private var preparedTrimSignature: String?
    private var trimRecoverySaveTask: Task<Void, Never>?
    private var activeTrimPreparationID: UUID?
    private var recoveredTrimOptionKeys = Set<String>()
    private var savedSettingsValues: [String: JSONValue]?

    init() {
        restoreTrimSession()
    }

    var workflows: [WorkflowStatus] {
        StandaloneWorkflowCatalog.workflows(from: capabilities?.workflows ?? [])
    }

    var hasUnsavedSettings: Bool {
        guard let savedSettingsValues else { return false }
        return currentSettingsValues != savedSettingsValues
    }

    private var currentSettingsValues: [String: JSONValue] {
        var values: [String: JSONValue] = [:]
        for entry in settingsEntries {
            guard let preferenceID = entry.option.preferenceID else { continue }
            values[preferenceID] = value(for: entry.option, workflow: entry.workflow)
        }
        return values
    }

    func refreshCapabilities() async {
        isWorking = true
        errorMessage = nil
        engineErrorMessage = nil
        defer { isWorking = false }
        do {
            let client = try EngineClient.resolvedClient()
            self.client = client
            let response: CapabilitiesResponse = try await client.send(
                ["action": "capabilities"],
                as: CapabilitiesResponse.self
            )
            guard response.ok else {
                throw EngineClientError.engine(response.error?.message ?? "The engine connection failed.")
            }
            capabilities = response
            installMissingDefaults(from: response.workflows ?? [])
            do {
                let preferencesResponse: PreferencesResponse = try await client.send(
                    ["action": "preferences"],
                    as: PreferencesResponse.self
                )
                if preferencesResponse.ok {
                    applyPreferences(preferencesResponse.preferences ?? [:])
                    savedSettingsValues = currentSettingsValues
                } else {
                    savedSettingsValues = currentSettingsValues
                }
            } catch {
                settingsMessage = "Using schema defaults because saved settings could not be read."
                savedSettingsValues = currentSettingsValues
            }
            await refreshFinderExtensionStatus(client: client)
            message = "Ready. Choose a task or drop videos to begin."
        } catch {
            errorMessage = error.localizedDescription
            engineErrorMessage = error.localizedDescription
            message = "Local processing is unavailable."
        }
    }

    private func installMissingDefaults(from workflows: [WorkflowStatus]) {
        var allValues = workflowOptionValues
        for workflow in workflows {
            let allowedKeys = Set(workflow.options.map(\.key))
            var values = (allValues[workflow.id] ?? [:]).filter {
                allowedKeys.contains($0.key)
            }
            for option in workflow.options where values[option.key] == nil {
                values[option.key] = option.defaultValue
            }
            allValues[workflow.id] = values
        }
        workflowOptionValues = allValues
    }

    private func applyPreferences(_ preferences: [String: JSONValue]) {
        var allValues = workflowOptionValues
        for workflow in workflows {
            var values = allValues[workflow.id] ?? [:]
            for option in workflow.options {
                if let preferenceID = option.preferenceID,
                   let preferenceValue = preferences[preferenceID] {
                    if workflow.id == "trim", recoveredTrimOptionKeys.contains(option.key) {
                        continue
                    }
                    values[option.key] = preferenceValue
                }
            }
            allValues[workflow.id] = values
        }
        workflowOptionValues = allValues
    }

    var settingsEntries: [SettingsOptionEntry] {
        var seen = Set<String>()
        var entries: [SettingsOptionEntry] = []
        for workflow in workflows {
            for option in workflow.options where option.placement == "settings" {
                let identifier = option.preferenceID ?? "\(workflow.id).\(option.key)"
                if seen.insert(identifier).inserted {
                    entries.append(SettingsOptionEntry(workflow: workflow, option: option))
                }
            }
        }
        return entries
    }

    func isWorkflowVisible(_ workflow: WorkflowStatus) -> Bool {
        workflow.visible != false
    }

    func refreshFinderExtensionStatus(client suppliedClient: EngineClient? = nil) async {
        do {
            let client = try suppliedClient ?? self.client ?? EngineClient.resolvedClient()
            self.client = client
            let response: FinderExtensionResponse = try await client.send(
                ["action": "finder_extension_status"],
                as: FinderExtensionResponse.self
            )
            guard response.ok else {
                throw EngineClientError.engine(response.error?.message ?? "Finder extension status is unavailable.")
            }
            let quickActions = response.quickActions ?? []
            let installedActions = quickActions.filter(\.installed)
            let enabledActions = installedActions.filter { $0.election == "use" }
            finderExtensionEnabled = response.enabled == true || !enabledActions.isEmpty
            let syncStatus: String
            if response.enabled == true {
                syncStatus = "Finder Sync: enabled for local folders."
            } else if response.election == "ignore" {
                syncStatus = "Finder Sync: disabled by this Mac user."
            } else if response.installed == true {
                syncStatus = "Finder Sync: installed but not enabled."
            } else {
                syncStatus = "Finder Sync: missing from this VTS installation."
            }
            let actionStatus: String
            if installedActions.count == 6 {
                actionStatus = "Finder Quick Actions: \(enabledActions.count) of 6 enabled."
            } else if installedActions.isEmpty {
                actionStatus = "Finder Quick Actions: not included in this VTS installation."
            } else {
                actionStatus = "Finder Quick Actions: installation incomplete (\(installedActions.count) of 6)."
            }
            finderExtensionStatus = "\(syncStatus)\n\(actionStatus)"
        } catch {
            finderExtensionEnabled = false
            finderExtensionStatus = error.localizedDescription
        }
    }

    func enableFinderExtension() async {
        guard !isUpdatingFinderExtension else { return }
        isUpdatingFinderExtension = true
        defer { isUpdatingFinderExtension = false }
        do {
            let client = try self.client ?? EngineClient.resolvedClient()
            self.client = client
            let response: FinderExtensionResponse = try await client.send(
                ["action": "enable_finder_extension"],
                as: FinderExtensionResponse.self
            )
            guard response.ok, response.enabled == true else {
                throw EngineClientError.engine(response.error?.message ?? "macOS did not enable the Finder extension.")
            }
            await refreshFinderExtensionStatus(client: client)
        } catch {
            finderExtensionEnabled = false
            finderExtensionStatus = error.localizedDescription
        }
    }

    func repairFinderExtensionElectionIfNeeded() async {
        // PlugInKit's default election can return after an update or a
        // transient setup failure. The backend rechecks each election and
        // repairs only defaults, preserving explicit ignore choices.
        do {
            let client = try self.client ?? EngineClient.resolvedClient()
            self.client = client
            let response: FinderExtensionResponse = try await client.send(
                ["action": "finder_extension_status"],
                as: FinderExtensionResponse.self
            )
            guard response.ok else { return }
            let finderNeedsRepair = response.installed == true && response.election == "default"
            let actionNeedsRepair = response.quickActions?.contains {
                $0.installed && $0.election == "default"
            } == true
            guard finderNeedsRepair || actionNeedsRepair else { return }
            let repaired: FinderExtensionResponse = try await client.send(
                ["action": "repair_finder_actions"],
                as: FinderExtensionResponse.self
            )
            if repaired.ok {
                await refreshFinderExtensionStatus(client: client)
            }
        } catch {
            // A failed lookup is retried on the next launch. Do not elect an
            // extension whose current user choice could not be read.
        }
    }

    func openFinderJob(_ url: URL) async -> String? {
        guard
            url.scheme?.lowercased() == "vts",
            url.host?.lowercased() == "finder-job",
            let identifier = url.pathComponents.last,
            let uuid = UUID(uuidString: identifier),
            uuid.uuidString.lowercased() == identifier.lowercased()
        else {
            errorMessage = "VTS received an invalid Finder job link."
            return nil
        }

        if capabilities == nil {
            await refreshCapabilities()
        }

        let manifestURL = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/VTS/Finder Jobs", isDirectory: true)
            .appendingPathComponent("\(identifier.lowercased()).json")
        do {
            let resourceValues = try manifestURL.resourceValues(forKeys: [.isSymbolicLinkKey])
            guard resourceValues.isSymbolicLink != true else {
                throw EngineClientError.engine("VTS Finder job manifests cannot be symbolic links.")
            }
            let manifest = try JSONDecoder().decode(
                FinderJobManifest.self,
                from: Data(contentsOf: manifestURL)
            )
            guard manifest.jobID == identifier.lowercased() else {
                throw EngineClientError.engine("The Finder job identifier does not match its manifest.")
            }
            guard [1, 2, 3].contains(manifest.version) else {
                throw EngineClientError.engine("This Finder job uses an unsupported format.")
            }
            guard
                (manifest.version == 1 && manifest.options == nil) ||
                (manifest.version == 2 && manifest.options != nil) ||
                (manifest.version == 3 && manifest.autoStart == true)
            else {
                throw EngineClientError.engine("The Finder job options do not match its format version.")
            }
            var action = manifest.action
            var migratedOptions = manifest.options ?? [:]
            switch manifest.action {
            case "split":
                action = "transcode"
                if let limit = migratedOptions.removeValue(forKey: "max_part_gb") {
                    migratedOptions["max_size_gb"] = limit
                }
                migratedOptions["max_size_enabled"] = .bool(true)
                migratedOptions["size_strategy"] = .string("preserve_quality")
            default:
                break
            }
            guard let workflow = workflows.first(where: { $0.id == action }) else {
                throw EngineClientError.engine("This VTS build does not support the requested Finder job.")
            }
            let urls = deduplicated(manifest.paths.map { URL(fileURLWithPath: $0) }).filter {
                FileManager.default.fileExists(atPath: $0.path)
            }
            guard !urls.isEmpty else {
                throw EngineClientError.engine("The Finder selection is no longer available.")
            }

            let orderedURLs = orderedWorkflowInputs(urls, for: workflow)
            workflowSelections[workflow.id] = orderedURLs
            workflowPreviewURLs[workflow.id] = firstPlayableURL(in: orderedURLs)
            if manifest.options != nil {
                let allowedKeys = Set(workflow.options.map(\.key))
                var values = workflowOptionValues[workflow.id] ?? [:]
                for (key, value) in migratedOptions where allowedKeys.contains(key) {
                    values[key] = value
                }
                workflowOptionValues[workflow.id] = values
            }
            if workflow.id == "trim" {
                invalidateTrimSetup()
                scheduleTrimSessionSave()
            }
            try FileManager.default.removeItem(at: manifestURL)
            setWorkflowMessage(
                manifest.autoStart == true
                    ? "Finder started this job in the background."
                    : "Finder added \(urls.count) item\(urls.count == 1 ? "" : "s"). Review the job options and run it here.",
                for: workflow.id
            )
            message = manifest.autoStart == true
                ? "Running \(workflow.title) from Finder."
                : "Opened \(workflow.title) from Finder."
            errorMessage = nil
            if manifest.autoStart == true {
                // A quick action has no window in which a disabled Run button
                // could explain itself. "Import Today's Videos" on a card with
                // no saved destination would otherwise present an empty panel
                // and never start, so say what is missing and open the tool.
                if let blocker = runDisabledReason(for: workflow) {
                    workflowMessages.removeValue(forKey: workflow.id)
                    setWorkflowError(blocker, for: workflow.id)
                    errorMessage = blocker
                    message = "\(workflow.title) needs one more setting."
                    NSApp.activate(ignoringOtherApps: true)
                    return workflow.id
                }
                finderJobTitle = workflow.title
                jobResult = nil
                // A quick action reports in its own floating panel and opens
                // no window at all.
                FinderJobProgressPanelController.shared.present(model: self)
                launchWorkflow(workflow)
                return nil
            }
            NSApp.activate(ignoringOtherApps: true)
            return workflow.id
        } catch {
            let detail = error.localizedDescription
            errorMessage = detail
            message = "Finder job could not be opened."
            return nil
        }
    }

    func chooseVideos() {
        let panel = NSOpenPanel()
        panel.title = "Choose videos to check"
        panel.prompt = "Choose"
        panel.canChooseDirectories = false
        panel.canChooseFiles = true
        panel.allowsMultipleSelection = true
        panel.allowedContentTypes = [.movie, .video, .audiovisualContent]
        if panel.runModal() == .OK {
            addInspectionInputs(panel.urls, replacing: true)
        }
    }

    @discardableResult
    func addInspectionInputs(_ urls: [URL], replacing: Bool = false) -> Bool {
        let supportedExtensions = Set([
            "3gp", "avi", "m2ts", "m4v", "mkv", "mov", "mp4", "mts", "ts", "webm",
        ])
        let accepted = urls.map(\.standardizedFileURL).filter {
            !$0.hasDirectoryPath && supportedExtensions.contains($0.pathExtension.lowercased())
        }
        guard !accepted.isEmpty else {
            message = "Drop one or more video files to check them."
            return false
        }
        selectedURLs = deduplicated((replacing ? [] : selectedURLs) + accepted)
        inspections = []
        inspectionErrorMessage = nil
        message = "Selected \(selectedURLs.count) file\(selectedURLs.count == 1 ? "" : "s"). Ready to inspect."
        return true
    }

    func clearInspectionInputs() {
        selectedURLs = []
        inspections = []
        inspectionErrorMessage = nil
        message = "Ready for media inspection."
    }

    func inspectSelected() async {
        guard !selectedURLs.isEmpty else { return }
        isWorking = true
        isInspecting = true
        errorMessage = nil
        inspectionErrorMessage = nil
        defer {
            isWorking = false
            isInspecting = false
        }
        do {
            let client = try self.client ?? EngineClient.resolvedClient()
            self.client = client
            let response: InspectionResponse = try await client.send(
                ["action": "inspect_videos", "paths": selectedURLs.map(\.path)],
                as: InspectionResponse.self
            )
            guard response.ok else {
                throw EngineClientError.engine(response.error?.message ?? "Inspection failed.")
            }
            inspections = response.files ?? []
            message = "Checked \(inspections.count) file\(inspections.count == 1 ? "" : "s") with the bundled media tools."
        } catch {
            errorMessage = error.localizedDescription
            inspectionErrorMessage = error.localizedDescription
            message = "Media inspection failed."
        }
    }

    func workflowSelection(for workflow: WorkflowStatus) -> [URL] {
        workflowSelections[workflow.id] ?? []
    }

    @discardableResult
    func addWorkflowInputs(_ urls: [URL], to workflow: WorkflowStatus) -> Bool {
        guard workflow.selectionMode == "files_or_folder" else { return false }
        let supportedExtensions = Set([
            "3gp", "avi", "m2ts", "m4v", "mkv", "mov", "mp4", "mts", "ts", "webm",
        ])
        let accepted = urls.compactMap { rawURL -> URL? in
            let url = rawURL.standardizedFileURL
            var isDirectory: ObjCBool = false
            guard FileManager.default.fileExists(atPath: url.path, isDirectory: &isDirectory) else {
                return nil
            }
            if isDirectory.boolValue { return url }
            return supportedExtensions.contains(url.pathExtension.lowercased()) ? url : nil
        }
        guard !accepted.isEmpty else {
            setWorkflowMessage("Drop video files or folders containing videos.", for: workflow.id)
            return false
        }

        var selections = workflowSelections
        let existing = selections[workflow.id] ?? []
        selections[workflow.id] = orderedWorkflowInputs(
            deduplicated(existing + accepted),
            for: workflow
        )
        workflowSelections = selections
        if workflowPreviewURLs[workflow.id] == nil {
            workflowPreviewURLs[workflow.id] = firstPlayableURL(
                in: selections[workflow.id] ?? accepted
            )
        }
        clearWorkflowFailure(for: workflow.id)
        let addedCount = selections[workflow.id]?.count ?? accepted.count
        let readyMessage: String
        switch workflow.id {
        case "trim":
            readyMessage = "Loading \(addedCount) source item\(addedCount == 1 ? "" : "s") into the trim queue…"
        case "merge":
            readyMessage = "\(addedCount) clip\(addedCount == 1 ? "" : "s") queued in chronological order."
        default:
            readyMessage = "\(addedCount) item\(addedCount == 1 ? "" : "s") queued. Every item listed will be processed."
        }
        setWorkflowMessage(readyMessage, for: workflow.id)
        if workflow.id == "trim" {
            invalidateTrimSetup()
            scheduleTrimSessionSave()
        }
        return true
    }

    func chooseWorkflowInput(for workflow: WorkflowStatus) {
        guard workflow.selectionMode == "files_or_folder" else { return }
        let panel = NSOpenPanel()
        panel.title = "Choose videos or a folder for \(workflow.title)"
        panel.prompt = "Add"
        panel.canChooseDirectories = true
        panel.canChooseFiles = true
        panel.allowsMultipleSelection = true
        panel.allowedContentTypes = [.movie, .video, .audiovisualContent]
        if panel.runModal() == .OK {
            addWorkflowInputs(panel.urls, to: workflow)
        }
    }

    func removeWorkflowInput(_ url: URL, from workflow: WorkflowStatus) {
        var selections = workflowSelections
        selections[workflow.id] = (selections[workflow.id] ?? []).filter { $0.path != url.path }
        workflowSelections = selections
        if workflowPreviewURLs[workflow.id]?.path == url.path {
            workflowPreviewURLs[workflow.id] = firstPlayableURL(in: selections[workflow.id] ?? [])
        }
        if workflow.id == "trim" {
            invalidateTrimSetup()
            scheduleTrimSessionSave()
        }
        clearWorkflowFailure(for: workflow.id)
    }

    func clearWorkflowInput(for workflow: WorkflowStatus) {
        var selections = workflowSelections
        selections[workflow.id] = []
        workflowSelections = selections
        workflowPreviewURLs[workflow.id] = nil
        if workflow.id == "trim" {
            invalidateTrimSetup()
            scheduleTrimSessionSave()
        }
        clearWorkflowFailure(for: workflow.id)
    }

    private func deduplicated(_ urls: [URL]) -> [URL] {
        var seen = Set<String>()
        return urls.filter { seen.insert($0.standardizedFileURL.path).inserted }
    }

    private func orderedWorkflowInputs(
        _ urls: [URL],
        for workflow: WorkflowStatus
    ) -> [URL] {
        guard workflow.id == "merge" else { return urls }
        return urls.sorted { left, right in
            let leftDate = recordingTimestamp(in: left)
            let rightDate = recordingTimestamp(in: right)
            switch (leftDate, rightDate) {
            case let (leftDate?, rightDate?) where leftDate != rightDate:
                return leftDate < rightDate
            case (_?, nil):
                return true
            case (nil, _?):
                return false
            default:
                return left.path.localizedStandardCompare(right.path) == .orderedAscending
            }
        }
    }

    private func recordingTimestamp(in url: URL) -> Date? {
        let name = url.deletingPathExtension().lastPathComponent
        let pattern = #"(?i)([0-9]{2}|[A-Z]{3})-([0-9]{2}|[A-Z]{3})-([0-9]{4})_([0-9]{2})-([0-9]{2})-([0-9]{2})"#
        guard let expression = try? NSRegularExpression(pattern: pattern),
              let match = expression.firstMatch(
                in: name,
                range: NSRange(name.startIndex..<name.endIndex, in: name)
              )
        else { return nil }

        func captured(_ index: Int) -> String? {
            guard let range = Range(match.range(at: index), in: name) else { return nil }
            return String(name[range])
        }
        guard let first = captured(1),
              let second = captured(2),
              let year = captured(3).flatMap(Int.init),
              let hour = captured(4).flatMap(Int.init),
              let minute = captured(5).flatMap(Int.init),
              let secondValue = captured(6).flatMap(Int.init)
        else { return nil }

        let monthNames = [
            "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4,
            "MAY": 5, "JUN": 6, "JUL": 7, "AUG": 8,
            "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
        ]
        let firstUpper = first.uppercased()
        let secondUpper = second.uppercased()
        let month: Int
        let day: Int
        if let namedMonth = monthNames[firstUpper], let numericDay = Int(second) {
            month = namedMonth
            day = numericDay
        } else if let namedMonth = monthNames[secondUpper], let numericDay = Int(first) {
            month = namedMonth
            day = numericDay
        } else if let firstNumber = Int(first), let secondNumber = Int(second) {
            if firstNumber > 12 {
                day = firstNumber
                month = secondNumber
            } else if secondNumber > 12 {
                month = firstNumber
                day = secondNumber
            } else if prefersDayFirstDates {
                day = firstNumber
                month = secondNumber
            } else {
                month = firstNumber
                day = secondNumber
            }
        } else {
            return nil
        }

        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = .current
        return calendar.date(from: DateComponents(
            year: year,
            month: month,
            day: day,
            hour: hour,
            minute: minute,
            second: secondValue
        ))
    }

    private var prefersDayFirstDates: Bool {
        for workflow in workflows {
            guard let option = workflow.options.first(where: { $0.preferenceID == "date_format" }) else {
                continue
            }
            return value(for: option, workflow: workflow).stringValue.hasPrefix("%d")
        }
        return false
    }

    private func firstPlayableURL(in urls: [URL]) -> URL? {
        if let file = urls.first(where: { !$0.hasDirectoryPath }) { return file }
        let supportedExtensions = Set(["3gp", "avi", "m2ts", "m4v", "mkv", "mov", "mp4", "mts", "ts", "webm"])
        for folder in urls where folder.hasDirectoryPath {
            guard let enumerator = FileManager.default.enumerator(
                at: folder,
                includingPropertiesForKeys: [.isRegularFileKey],
                options: [.skipsHiddenFiles, .skipsPackageDescendants]
            ) else { continue }
            var playable: [URL] = []
            for case let candidate as URL in enumerator {
                guard supportedExtensions.contains(candidate.pathExtension.lowercased()) else { continue }
                if (try? candidate.resourceValues(forKeys: [.isRegularFileKey]).isRegularFile) == true {
                    playable.append(candidate)
                }
            }
            if let file = playable.sorted(by: {
                $0.path.localizedStandardCompare($1.path) == .orderedAscending
            }).first {
                return file
            }
        }
        return nil
    }

    func previewURL(for workflow: WorkflowStatus) -> URL? {
        if workflow.id == "trim", !trimCandidates.isEmpty {
            let candidatePaths = Set(trimCandidates.map(\.path))
            if let selected = workflowPreviewURLs[workflow.id], candidatePaths.contains(selected.path) {
                return selected
            }
            return URL(fileURLWithPath: trimCandidates[0].path)
        }
        return workflowPreviewURLs[workflow.id] ?? firstPlayableURL(in: workflowSelection(for: workflow))
    }

    func selectPreview(_ url: URL, for workflow: WorkflowStatus) {
        workflowPreviewURLs[workflow.id] = url.hasDirectoryPath ? firstPlayableURL(in: [url]) : url
    }

    func trimRange(for url: URL, duration: Double) -> TrimRange {
        trimRanges[url.path] ?? TrimRange(start: 0, end: duration, duration: duration, edited: false)
    }

    func installTrimDuration(_ duration: Double, for url: URL) {
        guard duration.isFinite, duration > 0 else { return }
        if var existing = trimRanges[url.path] {
            existing.duration = duration
            existing.start = min(max(0, existing.start), duration)
            existing.end = min(max(existing.start, existing.end), duration)
            trimRanges[url.path] = existing
        } else {
            trimRanges[url.path] = TrimRange(start: 0, end: duration, duration: duration, edited: false)
        }
        scheduleTrimSessionSave()
    }

    func updateTrimRange(for url: URL, start: Double? = nil, end: Double? = nil) {
        guard var range = trimRanges[url.path] else { return }
        if let start { range.start = min(max(0, start), max(0, range.end - 0.05)) }
        if let end { range.end = max(range.start + 0.05, min(range.duration, end)) }
        range.edited = true
        trimRanges[url.path] = range
        scheduleTrimSessionSave()
    }

    func resetTrimRange(for url: URL) {
        guard var range = trimRanges[url.path] else { return }
        range.start = 0
        range.end = range.duration
        range.edited = false
        trimRanges[url.path] = range
        scheduleTrimSessionSave()
    }

    private var trimRecoveryURL: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/VTS/trim-recovery", isDirectory: true)
            .appendingPathComponent("live-trim-session.json")
    }

    private func restoreTrimSession() {
        let url = trimRecoveryURL
        guard let data = try? Data(contentsOf: url),
              let snapshot = try? JSONDecoder().decode(TrimRecoverySnapshot.self, from: data)
        else { return }
        trimRanges = snapshot.ranges
        let existingPaths = snapshot.selectedPaths.filter {
            FileManager.default.fileExists(atPath: $0)
        }
        if !existingPaths.isEmpty {
            workflowSelections["trim"] = existingPaths.map { URL(fileURLWithPath: $0) }
            workflowPreviewURLs["trim"] = URL(fileURLWithPath: existingPaths[0])
        }
        if !snapshot.options.isEmpty {
            workflowOptionValues["trim"] = snapshot.options
            recoveredTrimOptionKeys = Set(snapshot.options.keys)
        }
        let editedCount = snapshot.ranges.values.filter(\.edited).count
        if editedCount > 0 {
            trimSetupMessage = "Recovered \(editedCount) saved trim range(s) from \(snapshot.savedAt)."
        }
    }

    private func scheduleTrimSessionSave() {
        trimRecoverySaveTask?.cancel()
        trimRecoverySaveTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 250_000_000)
            guard !Task.isCancelled else { return }
            self?.persistTrimSessionNow()
        }
    }

    private func persistTrimSessionNow() {
        guard !trimRanges.isEmpty else { return }
        let snapshot = TrimRecoverySnapshot(
            savedAt: ISO8601DateFormatter().string(from: Date()),
            ranges: trimRanges,
            selectedPaths: (workflowSelections["trim"] ?? []).map(\.path),
            options: workflowOptionValues["trim"] ?? [:]
        )
        do {
            let url = trimRecoveryURL
            try FileManager.default.createDirectory(
                at: url.deletingLastPathComponent(),
                withIntermediateDirectories: true
            )
            let encoder = JSONEncoder()
            encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
            try encoder.encode(snapshot).write(to: url, options: .atomic)
        } catch {
            trimSetupMessage = "Could not save trim recovery data: \(error.localizedDescription)"
        }
    }

    private func clearPersistedTrimSession() {
        trimRecoverySaveTask?.cancel()
        trimRecoverySaveTask = nil
        recoveredTrimOptionKeys.removeAll()
        try? FileManager.default.removeItem(at: trimRecoveryURL)
    }

    private func trimSignature(for workflow: WorkflowStatus) -> String {
        return workflowSelection(for: workflow).map(\.path).sorted().joined(separator: "|")
    }

    func trimPreparationKey(for workflow: WorkflowStatus) -> String {
        trimSignature(for: workflow)
    }

    private func invalidateTrimSetup() {
        preparedTrimSignature = nil
        trimCandidates = []
        trimSetupMessage = "Loading the trim queue…"
    }

    private func effectiveWorkflowOptions(for workflow: WorkflowStatus) -> [String: JSONValue] {
        var options = workflowOptionValues[workflow.id] ?? [:]
        return options
    }

    func prepareNativeTrim(for workflow: WorkflowStatus, force: Bool = false) async {
        guard workflow.id == "trim", !workflowSelection(for: workflow).isEmpty else { return }
        let signature = trimSignature(for: workflow)
        guard force || preparedTrimSignature != signature else { return }
        let requestID = UUID()
        activeTrimPreparationID = requestID
        isPreparingTrim = true
        trimSetupMessage = "Reading clip durations…"
        defer {
            if activeTrimPreparationID == requestID {
                isPreparingTrim = false
                activeTrimPreparationID = nil
            }
        }
        do {
            let client = try self.client ?? EngineClient.resolvedClient()
            self.client = client
            let options = effectiveWorkflowOptions(for: workflow)
            let response: TrimSetupResponse = try await client.send(
                [
                    "action": "trim_setup",
                    "paths": workflowSelection(for: workflow).map(\.path),
                    "options": options.mapValues(\.anyValue),
                ],
                as: TrimSetupResponse.self
            )
            guard response.ok else {
                throw EngineClientError.engine(response.error?.message ?? "The trim queue could not be prepared.")
            }
            guard !Task.isCancelled,
                  activeTrimPreparationID == requestID,
                  trimSignature(for: workflow) == signature else { return }
            let clips = response.clips ?? []
            trimCandidates = clips
            for clip in clips {
                if trimRanges[clip.path]?.edited != true {
                    trimRanges[clip.path] = TrimRange(
                        start: clip.suggestedStart,
                        end: clip.suggestedEnd,
                        duration: clip.duration,
                        edited: false
                    )
                }
            }
            scheduleTrimSessionSave()
            preparedTrimSignature = signature
            if let current = workflowPreviewURLs[workflow.id], !clips.contains(where: { $0.path == current.path }) {
                workflowPreviewURLs[workflow.id] = clips.first.map { URL(fileURLWithPath: $0.path) }
            } else if workflowPreviewURLs[workflow.id] == nil {
                workflowPreviewURLs[workflow.id] = clips.first.map { URL(fileURLWithPath: $0.path) }
            }
            trimSetupMessage = "Loaded \(clips.count) clip(s)."
            clearWorkflowFailure(for: workflow.id)
        } catch {
            trimSetupMessage = error.localizedDescription
            setWorkflowError(error.localizedDescription, for: workflow.id)
        }
    }

    func value(for option: WorkflowOptionDefinition, workflow: WorkflowStatus) -> JSONValue {
        return workflowOptionValues[workflow.id]?[option.key] ?? option.defaultValue
    }

    func setValue(_ value: JSONValue, for option: WorkflowOptionDefinition, workflow: WorkflowStatus) {
        var allValues = workflowOptionValues
        if let preferenceID = option.preferenceID {
            for candidateWorkflow in workflows {
                var values = allValues[candidateWorkflow.id] ?? [:]
                for candidateOption in candidateWorkflow.options
                    where candidateOption.preferenceID == preferenceID {
                    values[candidateOption.key] = value
                }
                allValues[candidateWorkflow.id] = values
            }
        } else {
            var values = allValues[workflow.id] ?? [:]
            values[option.key] = value
            allValues[workflow.id] = values
        }
        guard allValues != workflowOptionValues else { return }
        workflowOptionValues = allValues
        if workflow.id == "trim" {
            scheduleTrimSessionSave()
        }
    }

    func stringBinding(for option: WorkflowOptionDefinition, workflow: WorkflowStatus) -> Binding<String> {
        Binding(
            get: { self.value(for: option, workflow: workflow).stringValue },
            set: { self.setValue(.string($0), for: option, workflow: workflow) }
        )
    }

    func boolBinding(for option: WorkflowOptionDefinition, workflow: WorkflowStatus) -> Binding<Bool> {
        Binding(
            get: { self.value(for: option, workflow: workflow).boolValue },
            set: { self.setValue(.bool($0), for: option, workflow: workflow) }
        )
    }

    func numberBinding(for option: WorkflowOptionDefinition, workflow: WorkflowStatus) -> Binding<Double> {
        Binding(
            get: { self.value(for: option, workflow: workflow).numberValue },
            set: { self.setValue(.number($0), for: option, workflow: workflow) }
        )
    }

    func choiceBinding(for option: WorkflowOptionDefinition, workflow: WorkflowStatus) -> Binding<JSONValue> {
        Binding(
            get: { self.value(for: option, workflow: workflow) },
            set: { self.setValue($0, for: option, workflow: workflow) }
        )
    }

    func choosePath(for option: WorkflowOptionDefinition, workflow: WorkflowStatus) {
        let panel = NSOpenPanel()
        panel.title = "Choose \(option.label)"
        panel.prompt = "Choose"
        panel.allowsMultipleSelection = false
        panel.canChooseDirectories = true
        panel.canChooseFiles = option.pathMode == "file_or_folder"
        if panel.runModal() == .OK, let url = panel.url {
            setValue(.string(url.path), for: option, workflow: workflow)
        }
    }

    func resetOptions(for workflow: WorkflowStatus) {
        var allValues = workflowOptionValues
        var values = allValues[workflow.id] ?? [:]
        for option in workflow.options where option.placement == "workflow" {
            values[option.key] = option.defaultValue
        }
        allValues[workflow.id] = values
        workflowOptionValues = allValues
        setWorkflowMessage("Job options restored to defaults.", for: workflow.id)
    }

    func resetSettingsDefaults() {
        for entry in settingsEntries {
            setValue(entry.option.defaultValue, for: entry.option, workflow: entry.workflow)
        }
        settingsMessage = "Defaults restored locally. Click Save Settings to apply them."
    }

    func saveSettings() async {
        guard !isSavingSettings else { return }
        isSavingSettings = true
        errorMessage = nil
        settingsErrorMessage = nil
        defer { isSavingSettings = false }
        do {
            let client = try self.client ?? EngineClient.resolvedClient()
            self.client = client
            var preferences: [String: Any] = [:]
            for entry in settingsEntries {
                guard let preferenceID = entry.option.preferenceID else { continue }
                preferences[preferenceID] = value(
                    for: entry.option,
                    workflow: entry.workflow
                ).anyValue
            }
            let response: PreferencesResponse = try await client.send(
                ["action": "save_preferences", "preferences": preferences],
                as: PreferencesResponse.self
            )
            guard response.ok else {
                throw EngineClientError.engine(response.error?.message ?? "Settings could not be saved.")
            }
            applyPreferences(response.preferences ?? [:])
            savedSettingsValues = currentSettingsValues
            settingsMessage = "Settings saved and shared with every workflow."
        } catch {
            errorMessage = error.localizedDescription
            settingsErrorMessage = error.localizedDescription
            settingsMessage = "Settings could not be saved: \(error.localizedDescription)"
        }
    }

    func validationMessage(for workflow: WorkflowStatus) -> String? {
        if workflow.selectionMode == "files_or_folder", workflowSelection(for: workflow).isEmpty {
            return "Add at least one video or folder."
        }
        for option in workflow.options where option.required {
            if value(for: option, workflow: workflow).stringValue.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                return "Choose \(option.label.lowercased())."
            }
        }
        if workflow.id == "import-files" {
            let destination = valueForKey("destination", workflow: workflow)?.stringValue ?? ""
            if destination.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                return "Choose the import destination."
            }
        }
        if workflow.id == "trim" {
            if isPreparingTrim { return "Wait for the selected videos to finish loading." }
            if trimCandidates.isEmpty { return "No videos are ready to trim." }
            if !hasEditedTrimRanges(for: workflow) {
                return "Adjust at least one trim range."
            }
        }
        return nil
    }

    func runDisabledReason(for workflow: WorkflowStatus) -> String? {
        if launchingWorkflowID != nil {
            return "Wait for the current job to finish preparing."
        }
        if let activeWorkflowID, activeWorkflowID != workflow.id {
            let activeName = workflows.first(where: { $0.id == activeWorkflowID })?.title ?? "another job"
            return "Wait for \(activeName) to finish."
        }
        if activeWorkflowID == workflow.id {
            return "This job is already running."
        }
        if isWorking {
            return "Wait for the current engine operation to finish."
        }
        return validationMessage(for: workflow)
    }

    func displayStatus(for workflow: WorkflowStatus) -> WorkflowDisplayStatus {
        if activeWorkflowID == workflow.id {
            return WorkflowDisplayStatus(title: "Running", detail: jobStatus, tone: .running)
        }
        if lastJobWorkflowID == workflow.id, jobOutcome == .failed {
            return WorkflowDisplayStatus(title: "Failed", detail: jobErrorMessage ?? jobStatus, tone: .failure)
        }
        if lastJobWorkflowID == workflow.id, jobOutcome == .succeeded {
            return WorkflowDisplayStatus(title: "Complete", detail: "The most recent job completed successfully.", tone: .success)
        }
        if lastJobWorkflowID == workflow.id, jobOutcome == .cancelled {
            return WorkflowDisplayStatus(title: "Cancelled", detail: "The most recent job was cancelled.", tone: .neutral)
        }
        if capabilities == nil, let engineErrorMessage {
            return WorkflowDisplayStatus(title: "Unavailable", detail: engineErrorMessage, tone: .failure)
        }
        if let validation = validationMessage(for: workflow) {
            return WorkflowDisplayStatus(title: "Setup", detail: validation, tone: .attention)
        }
        return WorkflowDisplayStatus(title: "Ready", detail: "Ready to run.", tone: .ready)
    }

    func dismissInspectionError() {
        let dismissed = inspectionErrorMessage
        inspectionErrorMessage = nil
        if dismissed == errorMessage { errorMessage = nil }
        message = "Ready for media inspection."
    }

    func dismissSettingsError() {
        let dismissed = settingsErrorMessage
        settingsErrorMessage = nil
        if dismissed == errorMessage { errorMessage = nil }
        settingsMessage = hasUnsavedSettings
            ? "Settings still have unsaved changes."
            : "Saved settings are shared across VTS workflows."
    }

    func dismissWorkflowError(for workflow: WorkflowStatus) {
        let dismissed = workflowErrors.removeValue(forKey: workflow.id)
        if dismissed == errorMessage { errorMessage = nil }
    }

    private func valueForKey(_ key: String, workflow: WorkflowStatus) -> JSONValue? {
        guard let option = workflow.options.first(where: { $0.key == key }) else { return nil }
        return value(for: option, workflow: workflow)
    }

    func hasEditedTrimRanges(for workflow: WorkflowStatus) -> Bool {
        if workflow.id == "trim", !trimCandidates.isEmpty {
            let candidates = Set(trimCandidates.map(\.path))
            return trimRanges.contains { candidates.contains($0.key) && $0.value.edited }
        }
        let selections = workflowSelection(for: workflow)
        return trimRanges.contains { path, range in
            range.edited && selections.contains { selection in
                selection.path == path || (selection.hasDirectoryPath && URL(fileURLWithPath: path).deletingLastPathComponent().path == selection.path)
            }
        }
    }

    func launchWorkflow(_ workflow: WorkflowStatus) {
        guard runDisabledReason(for: workflow) == nil else { return }
        guard jobProcess == nil else { return }
        launchPreparedWorkflow(workflow)
    }

    private func launchPreparedWorkflow(_ workflow: WorkflowStatus) {
        guard validationMessage(for: workflow) == nil else {
            launchingWorkflowID = nil
            return
        }
        guard jobProcess == nil else {
            launchingWorkflowID = nil
            return
        }
        launchingWorkflowID = workflow.id
        errorMessage = nil
        workflowErrors.removeValue(forKey: workflow.id)
        do {
            let client = try self.client ?? EngineClient.resolvedClient()
            self.client = client
            let options = effectiveWorkflowOptions(for: workflow)
            var request: [String: Any] = [
                "workflow": workflow.id,
                "paths": workflowSelection(for: workflow).map(\.path),
                "options": options.mapValues(\.anyValue),
            ]
            if workflow.id == "trim" {
                let candidates = Set(trimCandidates.map(\.path))
                request["edits"] = trimRanges.compactMap { path, range -> [String: Any]? in
                    guard candidates.contains(path), range.edited else { return nil }
                    return ["path": path, "start": range.start, "end": range.end]
                }
                persistTrimSessionNow()
            }
            try startJobProcess(client: client, request: request, workflow: workflow)
        } catch {
            setWorkflowMessage(error.localizedDescription, for: workflow.id)
            setWorkflowError(error.localizedDescription, for: workflow.id)
            lastJobWorkflowID = workflow.id
            jobOutcome = .failed
            jobErrorMessage = error.localizedDescription
            launchingWorkflowID = nil
        }
    }

    // MARK: - Confidence ladder (live filtering)

    private func startJobProcess(
        client: EngineClient,
        request: [String: Any],
        workflow: WorkflowStatus
    ) throws {
        let requestData = try JSONSerialization.data(withJSONObject: request)
        let process = Process()
        let input = Pipe()
        let output = Pipe()
        let errors = Pipe()
        let launch = client.command(for: .jobRunner)
        process.executableURL = launch.executable
        process.arguments = launch.arguments
        process.currentDirectoryURL = client.workingDirectoryURL
        process.environment = client.processEnvironment
        process.standardInput = input
        process.standardOutput = output
        process.standardError = errors

        jobOutputBuffer = Data()
        jobOutputScanOffset = 0
        jobLogs = []
        jobResult = nil
        jobProgress = 0
        jobStatus = "Starting \(workflow.title)…"
        jobOperation = request["operation"] as? String
        jobStage = nil
        jobOutcome = .running
        jobErrorMessage = nil
        activeWorkflowID = workflow.id
        lastJobWorkflowID = workflow.id
        isWorking = true
        jobProcess = process
        jobOutputPipe = output
        jobErrorPipe = errors

        jobEventTask?.cancel()
        jobEventContinuation?.finish()
        var madeContinuation: AsyncStream<JobStreamEvent>.Continuation!
        let events = AsyncStream<JobStreamEvent>(bufferingPolicy: .unbounded) { continuation in
            madeContinuation = continuation
        }
        let continuation = madeContinuation!
        jobEventContinuation = continuation
        let workflowID = workflow.id
        jobEventTask = Task { @MainActor [weak self] in
            for await event in events {
                guard let self else { break }
                switch event {
                case .output(let data):
                    self.consumeJobOutput(data, workflowID: workflowID)
                case .log(let text):
                    self.appendJobLog(text)
                case .terminated(let finished):
                    self.jobDidTerminate(finished, workflowID: workflowID)
                }
            }
        }

        output.fileHandleForReading.readabilityHandler = { handle in
            let data = handle.availableData
            if data.isEmpty { return }
            continuation.yield(.output(data))
        }
        errors.fileHandleForReading.readabilityHandler = { handle in
            let data = handle.availableData
            guard !data.isEmpty, let text = String(data: data, encoding: .utf8) else { return }
            continuation.yield(.log(text.trimmingCharacters(in: .whitespacesAndNewlines)))
        }
        process.terminationHandler = { finished in
            // Ordered behind every chunk already yielded, so the trailing read
            // in jobDidTerminate only ever picks up what genuinely arrived late.
            continuation.yield(.terminated(finished))
            continuation.finish()
        }
        do {
            try process.run()
        } catch {
            output.fileHandleForReading.readabilityHandler = nil
            errors.fileHandleForReading.readabilityHandler = nil
            process.terminationHandler = nil
            jobProcess = nil
            jobOutputPipe = nil
            jobErrorPipe = nil
            launchingWorkflowID = nil
            activeWorkflowID = nil
            isWorking = false
            jobStatus = "Could not start"
            jobOutcome = .failed
            jobErrorMessage = error.localizedDescription
            throw error
        }
        input.fileHandleForWriting.write(requestData)
        try input.fileHandleForWriting.close()
        setWorkflowMessage("Processing on this Mac. You can monitor progress here.", for: workflow.id)
    }

    func cancelActiveJob(source: String) {
        guard let process = jobProcess, process.isRunning else { return }
        // The user reported a job showing Cancelled that they never
        // cancelled. Every cancellation now names its trigger in the
        // diagnostic log, so a recurrence is attributable instead of a
        // mystery.
        appendJobLog("Cancel requested from the \(source).")
        jobStatus = "Cancelling…"
        process.terminate()
    }

    private func consumeJobOutput(_ data: Data, workflowID: String) {
        jobOutputBuffer.append(data)
        while jobOutputScanOffset <= jobOutputBuffer.count {
            let searchStart = jobOutputBuffer.index(
                jobOutputBuffer.startIndex,
                offsetBy: jobOutputScanOffset
            )
            guard let newline = jobOutputBuffer[searchStart...].firstIndex(of: 0x0A) else {
                // The next callback only needs to scan newly appended bytes.
                jobOutputScanOffset = jobOutputBuffer.count
                break
            }
            let line = Data(jobOutputBuffer.prefix(upTo: newline))
            jobOutputBuffer.removeSubrange(...newline)
            jobOutputScanOffset = 0
            guard !line.isEmpty,
                  let object = try? JSONSerialization.jsonObject(with: line) as? [String: Any],
                  let event = object["event"] as? String else { continue }
            switch event {
            case "started":
                jobStatus = "Processing"
            case "status":
                if let text = object["message"] as? String {
                    jobStatus = text
                    appendJobLog(text)
                }
            case "progress":
                if let value = object["value"] as? NSNumber {
                    jobProgress = value.doubleValue
                }
            case "stage":
                jobStage = object["value"] as? String
            case "result":
                if let result = object["data"], JSONSerialization.isValidJSONObject(result),
                   let resultData = try? JSONSerialization.data(withJSONObject: result) {
                    if let runtime = try? JSONDecoder().decode(VideoRuntimePayload.self, from: resultData),
                       runtime.kind == "video_runtime" {
                        jobResult = runtime.summary
                    } else if let pretty = try? JSONSerialization.data(withJSONObject: result, options: [.prettyPrinted, .sortedKeys]) {
                        jobResult = String(data: pretty, encoding: .utf8)
                    }
                }
            case "error":
                let text = object["message"] as? String ?? "The processing job failed."
                setWorkflowError(text, for: workflowID)
                jobStatus = text
                jobOutcome = .failed
                jobErrorMessage = text
                appendJobLog(text)
            case "finished":
                if object["success"] as? Bool == true {
                    jobProgress = 100
                    jobStatus = "Complete"
                    jobOutcome = .succeeded
                    setWorkflowMessage("Completed successfully.", for: workflowID)
                    if workflowID == "trim" { clearPersistedTrimSession() }
                } else if object["cancelled"] as? Bool == true {
                    jobStatus = "Cancelled"
                    jobOutcome = .cancelled
                    setWorkflowMessage("Job cancelled.", for: workflowID)
                } else if jobOutcome != .failed {
                    jobOutcome = .failed
                    jobErrorMessage = jobStatus
                }
            default:
                break
            }
        }
    }

    private func jobDidTerminate(_ process: Process, workflowID: String) {
        jobOutputPipe?.fileHandleForReading.readabilityHandler = nil
        jobErrorPipe?.fileHandleForReading.readabilityHandler = nil
        if let trailingOutput = jobOutputPipe?.fileHandleForReading.readDataToEndOfFile(), !trailingOutput.isEmpty {
            consumeJobOutput(trailingOutput, workflowID: workflowID)
        }
        if let trailingError = jobErrorPipe?.fileHandleForReading.readDataToEndOfFile(),
           !trailingError.isEmpty,
           let text = String(data: trailingError, encoding: .utf8) {
            appendJobLog(text.trimmingCharacters(in: .whitespacesAndNewlines))
        }
        if !jobOutputBuffer.isEmpty {
            var final = jobOutputBuffer
            final.append(0x0A)
            jobOutputBuffer = Data()
            jobOutputScanOffset = 0
            consumeJobOutput(final, workflowID: workflowID)
        }
        if process.terminationStatus != 0 && jobOutcome != .failed && jobStatus != "Cancelled" {
            let detail = "The background engine exited with status \(process.terminationStatus)."
            setWorkflowError(detail, for: workflowID)
            jobStatus = detail
            jobOutcome = .failed
            jobErrorMessage = detail
        }
        jobProcess = nil
        jobOutputPipe = nil
        jobErrorPipe = nil
        jobEventContinuation = nil
        launchingWorkflowID = nil
        activeWorkflowID = nil
        isWorking = false
    }

    private func appendJobLog(_ text: String) {
        guard !text.isEmpty else { return }
        jobLogs.append(text)
        if jobLogs.count > 500 { jobLogs.removeFirst(jobLogs.count - 500) }
    }

    private func formatTime(_ seconds: Double) -> String {
        let value = max(0, Int(seconds.rounded()))
        return String(format: "%02d:%02d:%02d", value / 3600, (value % 3600) / 60, value % 60)
    }

    private func setWorkflowMessage(_ value: String, for workflowID: String) {
        var messages = workflowMessages
        messages[workflowID] = value
        workflowMessages = messages
    }

    private func setWorkflowError(_ value: String, for workflowID: String) {
        var errors = workflowErrors
        errors[workflowID] = value
        workflowErrors = errors
        errorMessage = value
    }

    private func clearWorkflowFailure(for workflowID: String) {
        let dismissed = workflowErrors.removeValue(forKey: workflowID)
        if dismissed == errorMessage { errorMessage = nil }
        guard lastJobWorkflowID == workflowID, jobOutcome == .failed else { return }
        lastJobWorkflowID = nil
        jobOutcome = .idle
        jobErrorMessage = nil
        jobStatus = "Ready"
        jobProgress = 0
    }
}

private struct ToolCard: View {
    let name: String
    let status: ToolStatus?

    private var tone: VTSStatusTone {
        guard let status else { return .neutral }
        return status.available ? .ready : .failure
    }

    private var statusTitle: String {
        guard let status else { return "Checking" }
        return status.available ? "Ready" : "Missing"
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Image(systemName: tone.symbol)
                    .foregroundStyle(tone.color)
                Text(name).font(.headline)
                Spacer()
                Text(statusTitle.uppercased())
                    .font(.caption.bold())
                    .foregroundStyle(.secondary)
            }
            Text(status?.version ?? status?.command ?? "Not checked")
                .font(.caption)
                .foregroundStyle(.secondary)
                .lineLimit(2)
            if let path = status?.resolvedPath {
                Text(path)
                    .font(.system(.caption2, design: .monospaced))
                    .foregroundStyle(.tertiary)
                    .lineLimit(1)
                    .truncationMode(.middle)
            }
        }
        .padding(VTSMetrics.panelPadding)
        .frame(maxWidth: .infinity, minHeight: 105, alignment: .topLeading)
        .background(.quaternary.opacity(0.22), in: RoundedRectangle(cornerRadius: VTSMetrics.panelRadius))
        .overlay(
            RoundedRectangle(cornerRadius: VTSMetrics.panelRadius)
                .stroke(Color.secondary.opacity(0.09), lineWidth: 1)
        )
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(name), \(statusTitle)")
    }
}

private struct InspectionRow: View {
    let inspection: VideoInspection

    private var durationText: String {
        guard let duration = inspection.durationSeconds else { return "Duration unavailable" }
        let minutes = Int(duration) / 60
        let seconds = duration - Double(minutes * 60)
        return String(format: "%d:%05.2f", minutes, seconds)
    }

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: inspection.warnings.isEmpty ? "film.circle.fill" : "exclamationmark.circle.fill")
                .font(.title2)
                .foregroundStyle(inspection.warnings.isEmpty ? Color.accentColor : .orange)
            VStack(alignment: .leading, spacing: 4) {
                Text(inspection.name).font(.headline)
                HStack(spacing: 12) {
                    Text(durationText)
                    if let width = inspection.width, let height = inspection.height { Text("\(width) × \(height)") }
                    if let bytes = inspection.sizeBytes { Text(ByteCountFormatter.string(fromByteCount: bytes, countStyle: .file)) }
                    if let date = inspection.dates["CreateDate"] ?? inspection.dates["MediaCreateDate"] { Text(date) }
                }
                .font(.caption)
                .foregroundStyle(.secondary)
                if let warning = inspection.warnings.first {
                    Text(warning).font(.caption).foregroundStyle(.orange)
                }
            }
            Spacer()
        }
        .padding(.vertical, 5)
    }
}

private struct SystemStatusView: View {
    @ObservedObject var model: PrototypeViewModel
    @State private var isInspectionDropTargeted = false

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            VStack(alignment: .leading, spacing: 4) {
                Text("System Status")
                    .font(.title2.bold())
                    .accessibilityHeading(.h1)
            }
            .padding(.horizontal, 20)
            .padding(.vertical, 14)

            Divider()

            HSplitView {
                GroupBox("Processing Components") {
                    VStack(alignment: .leading, spacing: 10) {
                        HStack {
                            Label(
                                model.engineErrorMessage != nil ? "Unavailable" : (model.capabilities?.engine?.headless == true ? "Ready on this Mac" : "Checking…"),
                                systemImage: model.engineErrorMessage != nil ? "xmark.octagon.fill" : (model.capabilities?.engine?.headless == true ? "bolt.horizontal.circle.fill" : "clock")
                            )
                            .fontWeight(.semibold)
                            .foregroundStyle(model.engineErrorMessage != nil ? .red : (model.capabilities?.engine?.headless == true ? .green : .secondary))
                            Spacer()
                            Button("Run Check") { Task { await model.refreshCapabilities() } }
                                .controlSize(.small)
                                .disabled(model.isWorking)
                        }

                        if let engine = model.capabilities?.engine {
                            Text("Local worker: Python \(engine.pythonVersion) • \(engine.machine)")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }

                        ToolCard(name: "FFmpeg", status: model.capabilities?.tools?["ffmpeg"])
                        ToolCard(name: "FFprobe", status: model.capabilities?.tools?["ffprobe"])
                        ToolCard(name: "ExifTool", status: model.capabilities?.tools?["exiftool"])

                        HStack {
                            Label("\(model.workflows.filter { model.isWorkflowVisible($0) }.count) workflows", systemImage: "square.grid.3x3.fill")
                            Spacer()
                            Text("Processing remains local")
                                .foregroundStyle(.secondary)
                        }
                        .font(.caption)

                        if let error = model.engineErrorMessage {
                            InlineMessageBanner(message: error, tone: .failure)
                        }
                    }
                    .padding(.top, 5)
                }
                .padding(16)
                .frame(minWidth: 340, idealWidth: 400, maxWidth: 470, maxHeight: .infinity, alignment: .top)

                GroupBox("Check a Video") {
                    VStack(alignment: .leading, spacing: 12) {
                        HStack {
                            Button("Choose Videos…", systemImage: "plus") { model.chooseVideos() }
                            Button("Clear") { model.clearInspectionInputs() }
                                .disabled(model.selectedURLs.isEmpty)
                            Button("Check Selected", systemImage: "play.fill") { Task { await model.inspectSelected() } }
                                .buttonStyle(.borderedProminent)
                                .disabled(model.selectedURLs.isEmpty || model.isWorking)
                            Spacer()
                            Text("\(model.selectedURLs.count) selected").foregroundStyle(.secondary)
                        }

                        if model.isInspecting {
                            HStack(spacing: 9) {
                                ProgressView().controlSize(.small)
                                Text("Inspecting metadata and media streams…")
                                    .font(.callout)
                                    .foregroundStyle(.secondary)
                            }
                            .accessibilityElement(children: .combine)
                        }

                        if let error = model.inspectionErrorMessage {
                            InlineMessageBanner(message: error, tone: .failure) {
                                model.dismissInspectionError()
                            }
                        }

                        if model.selectedURLs.isEmpty {
                            PolishedEmptyState(
                                title: "Drop videos here",
                                message: "Drag video files from Finder to check their dates, duration, dimensions, and compatibility.",
                                symbol: "square.and.arrow.down.on.square",
                                actionTitle: "Choose Videos…",
                                action: { model.chooseVideos() }
                            )
                        } else {
                            ScrollView {
                                LazyVStack(alignment: .leading, spacing: 0) {
                                    if model.inspections.isEmpty {
                                        ForEach(model.selectedURLs, id: \.path) { url in
                                            Label(url.lastPathComponent, systemImage: "film")
                                                .padding(.vertical, 7)
                                            Divider()
                                        }
                                    } else {
                                        ForEach(model.inspections) { inspection in
                                            InspectionRow(inspection: inspection)
                                            if inspection.id != model.inspections.last?.id { Divider() }
                                        }
                                    }
                                }
                            }
                            Label("Drop more videos anywhere in this box", systemImage: "arrow.down.doc")
                                .font(.caption2)
                                .foregroundStyle(.tertiary)
                        }
                    }
                    .padding(.top, 5)
                }
                .background(
                    isInspectionDropTargeted ? Color.accentColor.opacity(0.09) : Color.clear,
                    in: RoundedRectangle(cornerRadius: VTSMetrics.panelRadius)
                )
                .overlay {
                    RoundedRectangle(cornerRadius: VTSMetrics.panelRadius)
                        .stroke(
                            isInspectionDropTargeted ? Color.accentColor : Color.clear,
                            style: StrokeStyle(lineWidth: 2, dash: [7, 5])
                        )
                }
                .dropDestination(for: URL.self) { urls, _ in
                    model.addInspectionInputs(urls)
                } isTargeted: { targeted in
                    isInspectionDropTargeted = targeted
                }
                .padding(16)
                .frame(minWidth: 460, maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .navigationTitle("System Status")
    }
}

private struct InputQueueRow: View {
    let workflow: WorkflowStatus
    let url: URL
    let index: Int
    let selected: Bool
    @ObservedObject var model: PrototypeViewModel

    var body: some View {
        HStack(spacing: 4) {
            Button {
                model.selectPreview(url, for: workflow)
            } label: {
                HStack(spacing: 9) {
                    if workflow.id == "merge" {
                        mergePosition
                    }
                    Image(systemName: url.hasDirectoryPath ? "folder.fill" : "film")
                        .foregroundStyle(selected ? Color.accentColor : .secondary)
                        .accessibilityHidden(true)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(url.lastPathComponent).fontWeight(.medium)
                        Text(url.deletingLastPathComponent().path)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                            .truncationMode(.middle)
                    }
                    Spacer()
                    if selected {
                        Label("Previewing", systemImage: "play.rectangle.fill")
                            .font(.caption2)
                            .foregroundStyle(Color.accentColor)
                    }
                }
                .padding(9)
                .frame(maxWidth: .infinity, alignment: .leading)
                .contentShape(Rectangle())
                .background(
                    selected ? Color.accentColor.opacity(0.12) : Color.secondary.opacity(0.045),
                    in: RoundedRectangle(cornerRadius: VTSMetrics.rowRadius)
                )
                .overlay(
                    RoundedRectangle(cornerRadius: VTSMetrics.rowRadius)
                        .stroke(selected ? Color.accentColor.opacity(0.75) : Color.clear, lineWidth: 1.5)
                )
            }
            .buttonStyle(.plain)
            .accessibilityLabel(url.lastPathComponent)
            .accessibilityValue(selected ? "Selected for preview" : "Not selected")
            .accessibilityAddTraits(selected ? .isSelected : [])
            .accessibilityIdentifier("workflow.input.\(url.path)")

            Button("Remove \(url.lastPathComponent)", systemImage: "minus.circle") {
                model.removeWorkflowInput(url, from: workflow)
            }
            .labelStyle(.iconOnly)
            .buttonStyle(.plain)
            .foregroundStyle(.secondary)
            .help("Remove \(url.lastPathComponent) from the queue")
            .padding(6)
        }
    }

    private var mergePosition: some View {
        let position = String(index + 1)
        return Text(position)
            .font(.system(.caption, design: .rounded).weight(.bold))
            .foregroundStyle(selected ? Color.accentColor : .secondary)
            .frame(width: 22, height: 22)
            .background(.quaternary, in: Circle())
            .accessibilityLabel("Merge position " + position)
    }
}

private struct InputQueueView: View {
    let workflow: WorkflowStatus
    @ObservedObject var model: PrototypeViewModel
    @State private var isDropTargeted = false

    private var selectedURLs: [URL] { model.workflowSelection(for: workflow) }

    private var queueTitle: String {
        switch workflow.id {
        case "timestamp": return "1. Videos to Timestamp"
        case "clip-order": return "1. Clips to Organize"
        case "video-minutes": return "1. Videos to Count"
        case "trim": return "1. Videos to Trim"
        case "transcode": return "1. Videos to Transcode"
        case "merge": return "1. Clips to Merge"
        default: return "1. Choose Videos"
        }
    }

    private var emptyMessage: String {
        switch workflow.id {
        case "trim": return "Drop one or more videos, or a folder containing the clips you want to trim."
        case "merge": return "Drop all clips for the final video. VTS will put timestamped files in chronological order."
        case "transcode": return "Drop videos to convert at the selected quality, resolution, and file-size limit."
        case "timestamp": return "Drop camcorder or covert-camera footage that needs visible date and time overlays."
        default: return "Drop videos or a folder here. Every item in this queue will be processed."
        }
    }

    var body: some View {
        GroupBox {
            VStack(alignment: .leading, spacing: VTSMetrics.spacing) {
                HStack {
                    Button("Add Videos or Folder…", systemImage: "plus") { model.chooseWorkflowInput(for: workflow) }
                        .keyboardShortcut("o", modifiers: [.command])
                        .accessibilityIdentifier("workflow.add-input")
                    Button("Clear") { model.clearWorkflowInput(for: workflow) }
                        .disabled(selectedURLs.isEmpty)
                    Spacer()
                    Text(
                        workflow.id == "merge"
                            ? "\(selectedURLs.count) clip\(selectedURLs.count == 1 ? "" : "s") • oldest first"
                            : "\(selectedURLs.count) queued"
                    )
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                if selectedURLs.isEmpty {
                    PolishedEmptyState(
                        title: "Drop videos or folders here",
                        message: emptyMessage,
                        symbol: "square.and.arrow.down.on.square",
                        actionTitle: "Add Videos…",
                        action: { model.chooseWorkflowInput(for: workflow) }
                    )
                    .frame(minHeight: 112)
                } else {
                    ScrollView {
                        LazyVStack(spacing: VTSMetrics.compactSpacing) {
                            ForEach(Array(selectedURLs.enumerated()), id: \.element.path) { index, url in
                                let selected = model.previewURL(for: workflow)?.path == url.path
                                InputQueueRow(
                                    workflow: workflow,
                                    url: url,
                                    index: index,
                                    selected: selected,
                                    model: model
                                )
                            }
                        }
                        .padding(8)
                    }
                    .frame(minHeight: 105)
                    .background(.quaternary.opacity(0.20), in: RoundedRectangle(cornerRadius: VTSMetrics.rowRadius))

                }
            }
            .padding(.top, 4)
            .frame(maxWidth: .infinity, alignment: .topLeading)
        } label: {
            Label(queueTitle, systemImage: workflow.id == "merge" ? "list.number" : "list.bullet.rectangle")
        }
        .frame(
            maxWidth: .infinity,
            maxHeight: selectedURLs.isEmpty ? nil : .infinity,
            alignment: .topLeading
        )
        .background(
            isDropTargeted ? Color.accentColor.opacity(0.09) : Color.clear,
            in: RoundedRectangle(cornerRadius: VTSMetrics.panelRadius)
        )
        .overlay {
            RoundedRectangle(cornerRadius: VTSMetrics.panelRadius)
                .stroke(
                    isDropTargeted ? Color.accentColor : Color.clear,
                    style: StrokeStyle(lineWidth: 2, dash: [7, 5])
                )
        }
        .dropDestination(for: URL.self) { urls, _ in
            model.addWorkflowInputs(urls, to: workflow)
        } isTargeted: { targeted in
            isDropTargeted = targeted
        }
        .accessibilityIdentifier("workflow.input-queue")
        .accessibilityHint("Drop video files or folders here from Finder")
    }
}

private struct NativeVideoPreview: View {
    let url: URL
    let workflow: WorkflowStatus
    @ObservedObject var model: PrototypeViewModel

    @State private var player = AVPlayer()
    @State private var duration = 0.0
    @State private var currentTime = 0.0
    @State private var timeObserver: Any?
    @State private var trimPlaybackEnd: Double?
    @State private var isLoadingPreview = true
    @State private var previewError: String?

    private var isTrim: Bool { workflow.id == "trim" }
    private var trimRange: TrimRange { model.trimRange(for: url, duration: duration) }

    var body: some View {
        GroupBox {
            VStack(alignment: .leading, spacing: VTSMetrics.spacing) {
                ZStack {
                    VideoPlayer(player: player)
                    if isLoadingPreview {
                        Rectangle().fill(.black.opacity(0.72))
                        ProgressView("Loading preview…")
                            .controlSize(.large)
                            .foregroundStyle(.white)
                    } else if let previewError {
                        Rectangle().fill(.black.opacity(0.82))
                        VStack(spacing: 10) {
                            Image(systemName: "exclamationmark.triangle.fill")
                                .font(.title2)
                                .foregroundStyle(.orange)
                            Text("Preview unavailable")
                                .font(.headline)
                                .foregroundStyle(.white)
                            Text(previewError)
                                .font(.caption)
                                .foregroundStyle(.white.opacity(0.75))
                                .multilineTextAlignment(.center)
                                .frame(maxWidth: 380)
                            Button("Try Again") { configurePlayer() }
                        }
                        .padding()
                    }
                }
                    .frame(minHeight: 220, idealHeight: 360, maxHeight: .infinity)
                    .background(.black)
                    .clipShape(RoundedRectangle(cornerRadius: VTSMetrics.rowRadius))
                    .accessibilityLabel("Video preview for \(url.lastPathComponent)")
                    .accessibilityValue(isLoadingPreview ? "Loading" : (previewError == nil ? "Ready" : "Unavailable"))

                HStack {
                    Label(url.lastPathComponent, systemImage: "film")
                        .lineLimit(1)
                        .truncationMode(.middle)
                    Spacer()
                    Text("\(formatTime(currentTime)) / \(formatTime(duration))")
                        .font(.system(.caption, design: .monospaced))
                        .foregroundStyle(.secondary)
                    Button("Previous frame", systemImage: "backward.frame") { step(by: -1) }
                        .labelStyle(.iconOnly)
                        .help("Previous frame")
                    Button("Next frame", systemImage: "forward.frame") { step(by: 1) }
                        .labelStyle(.iconOnly)
                        .help("Next frame")
                }

                if isTrim && duration > 0 {
                    Divider()
                    VStack(alignment: .leading, spacing: 10) {
                        HStack {
                            Text("Start").frame(width: 38, alignment: .leading)
                            Slider(
                                value: Binding(
                                    get: { trimRange.start },
                                    set: { model.updateTrimRange(for: url, start: $0); seek(to: $0) }
                                ),
                                in: 0...max(0.05, trimRange.end - 0.05)
                            )
                            .accessibilityLabel("Trim start")
                            .accessibilityValue(formatTime(trimRange.start))
                            Text(formatTime(trimRange.start))
                                .font(.system(.caption, design: .monospaced))
                                .frame(width: 74, alignment: .trailing)
                        }
                        HStack {
                            Text("End").frame(width: 38, alignment: .leading)
                            Slider(
                                value: Binding(
                                    get: { trimRange.end },
                                    set: { model.updateTrimRange(for: url, end: $0); seek(to: $0) }
                                ),
                                in: min(duration, trimRange.start + 0.05)...duration
                            )
                            .accessibilityLabel("Trim end")
                            .accessibilityValue(formatTime(trimRange.end))
                            Text(formatTime(trimRange.end))
                                .font(.system(.caption, design: .monospaced))
                                .frame(width: 74, alignment: .trailing)
                        }
                        HStack {
                            Button("Set Start to Playhead") {
                                model.updateTrimRange(for: url, start: currentTime)
                            }
                            Button("Set End to Playhead") {
                                model.updateTrimRange(for: url, end: currentTime)
                            }
                            Spacer()
                            Text("Output: \(formatTime(max(0, trimRange.end - trimRange.start)))")
                                .foregroundStyle(.secondary)
                        }
                        HStack {
                            Button("Preview Selected Range", systemImage: "play.fill") {
                                trimPlaybackEnd = trimRange.end
                                seek(to: trimRange.start)
                                player.play()
                            }
                            Spacer()
                            if trimRange.edited {
                                StatusPill(title: "Edited", tone: .running)
                            }
                            Button("Reset Range", systemImage: "arrow.counterclockwise") {
                                model.resetTrimRange(for: url)
                                seek(to: 0)
                            }
                        }
                    }
                }
            }
            .padding(.top, 5)
        } label: {
            Label(
                isTrim ? "QuickTime Trim Preview" : "QuickTime Preview",
                systemImage: "play.rectangle.fill"
            )
        }
        .onAppear { configurePlayer() }
        .onDisappear { tearDownPlayer() }
    }

    private func configurePlayer() {
        if let observer = timeObserver {
            player.removeTimeObserver(observer)
            timeObserver = nil
        }
        previewError = nil
        isLoadingPreview = true
        player.replaceCurrentItem(with: AVPlayerItem(url: url))
        let interval = CMTime(seconds: 0.1, preferredTimescale: 600)
        timeObserver = player.addPeriodicTimeObserver(forInterval: interval, queue: .main) { time in
            currentTime = time.seconds.isFinite ? max(0, time.seconds) : 0
            if let end = trimPlaybackEnd, currentTime >= end {
                player.pause()
                trimPlaybackEnd = nil
            }
        }
        let asset = AVURLAsset(url: url)
        Task { @MainActor in
            do {
                let loadedDuration = try await asset.load(.duration)
                let seconds = loadedDuration.seconds
                guard seconds.isFinite, seconds > 0 else {
                    previewError = "QuickTime could not read a valid duration from this file."
                    isLoadingPreview = false
                    return
                }
                duration = seconds
                if isTrim { model.installTrimDuration(seconds, for: url) }
                isLoadingPreview = false
            } catch {
                previewError = error.localizedDescription
                isLoadingPreview = false
            }
        }
    }

    private func tearDownPlayer() {
        player.pause()
        if let observer = timeObserver {
            player.removeTimeObserver(observer)
            timeObserver = nil
        }
    }

    private func seek(to seconds: Double) {
        player.seek(to: CMTime(seconds: max(0, seconds), preferredTimescale: 600), toleranceBefore: .zero, toleranceAfter: .zero)
    }

    private func step(by count: Int) {
        player.pause()
        player.currentItem?.step(byCount: count)
    }

    private func formatTime(_ seconds: Double) -> String {
        guard seconds.isFinite else { return "00:00:00.0" }
        let whole = max(0, Int(seconds))
        return String(
            format: "%02d:%02d:%04.1f",
            whole / 3600,
            (whole % 3600) / 60,
            seconds.truncatingRemainder(dividingBy: 60)
        )
    }
}

private struct NativeTrimQueueView: View {
    let workflow: WorkflowStatus
    @ObservedObject var model: PrototypeViewModel
    @State private var isDropTargeted = false

    var body: some View {
        GroupBox {
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    Text("\(model.trimCandidates.count) clip\(model.trimCandidates.count == 1 ? "" : "s") ready")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                    Spacer()
                    if model.isPreparingTrim { ProgressView().controlSize(.small) }
                    Button("Add Videos…") { model.chooseWorkflowInput(for: workflow) }
                    Button("Rescan") {
                        Task { await model.prepareNativeTrim(for: workflow, force: true) }
                    }
                    .disabled(model.isPreparingTrim)
                    Button("Clear") { model.clearWorkflowInput(for: workflow) }
                }

                Text(model.trimSetupMessage)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)

                if model.trimCandidates.isEmpty && !model.isPreparingTrim {
                    PolishedEmptyState(
                        title: "No videos found",
                        message: "The selected folder does not contain videos for this trim scope.",
                        symbol: "line.3.horizontal.decrease.circle"
                    )
                    .frame(minHeight: 80)
                } else {
                    ScrollView {
                        LazyVStack(spacing: 6) {
                            ForEach(model.trimCandidates) { clip in
                                let url = URL(fileURLWithPath: clip.path)
                                let selected = model.previewURL(for: workflow)?.path == clip.path
                                let edited = model.trimRanges[clip.path]?.edited == true
                                Button { model.selectPreview(url, for: workflow) } label: {
                                    HStack(spacing: 9) {
                                        Image(systemName: "film")
                                            .foregroundStyle(.secondary)
                                            .frame(width: 20)
                                        VStack(alignment: .leading, spacing: 3) {
                                            Text(url.lastPathComponent)
                                                .fontWeight(.medium)
                                                .lineLimit(1)
                                                .truncationMode(.middle)
                                            if edited {
                                                Label("Edited range", systemImage: "slider.horizontal.2.square")
                                                    .foregroundStyle(Color.accentColor)
                                            } else {
                                                Text("Full clip")
                                            }
                                        }
                                        Spacer()
                                        Text(formatTime(clip.duration))
                                            .font(.system(.caption, design: .monospaced))
                                            .foregroundStyle(.secondary)
                                    }
                                    .padding(9)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                    .background(selected ? Color.accentColor.opacity(0.14) : Color.secondary.opacity(0.05), in: RoundedRectangle(cornerRadius: VTSMetrics.rowRadius))
                                    .overlay(RoundedRectangle(cornerRadius: VTSMetrics.rowRadius).stroke(selected ? Color.accentColor : Color.clear, lineWidth: 1.5))
                                }
                                .buttonStyle(.plain)
                                .accessibilityLabel(url.lastPathComponent)
                                .accessibilityValue("\(edited ? "edited range" : "full clip")\(selected ? ", selected" : "")")
                                .accessibilityAddTraits(selected ? .isSelected : [])
                            }
                        }
                    }
                    .frame(minHeight: 120)
                }
            }
            .padding(.top, 5)
        } label: {
            Label("1. Clips to Trim", systemImage: "scissors")
        }
        .background(
            isDropTargeted ? Color.accentColor.opacity(0.09) : Color.clear,
            in: RoundedRectangle(cornerRadius: VTSMetrics.panelRadius)
        )
        .overlay {
            RoundedRectangle(cornerRadius: VTSMetrics.panelRadius)
                .stroke(
                    isDropTargeted ? Color.accentColor : Color.clear,
                    style: StrokeStyle(lineWidth: 2, dash: [7, 5])
                )
        }
        .dropDestination(for: URL.self) { urls, _ in
            model.addWorkflowInputs(urls, to: workflow)
        } isTargeted: { targeted in
            isDropTargeted = targeted
        }
        .accessibilityIdentifier("workflow.trim-queue")
        .accessibilityHint("Drop more video files or folders here from Finder")
    }

    private func formatTime(_ seconds: Double) -> String {
        let total = max(0, Int(seconds.rounded()))
        return String(format: "%02d:%02d:%02d", total / 3600, (total % 3600) / 60, total % 60)
    }
}

private struct JobActivityView: View {
    let workflow: WorkflowStatus
    @ObservedObject var model: PrototypeViewModel
    @State private var logsExpanded = false

    private var tone: VTSStatusTone {
        model.lastJobWorkflowID == workflow.id ? model.jobOutcome.tone : .neutral
    }

    private var isRunningThisWorkflow: Bool {
        model.activeWorkflowID == workflow.id
    }

    var body: some View {
        GroupBox {
            if model.lastJobWorkflowID != workflow.id {
                PolishedEmptyState(
                    title: "No activity yet",
                    message: "Progress, preview frames, and results appear here.",
                    symbol: "waveform.path.ecg"
                )
            } else {
                ScrollView {
                    VStack(alignment: .leading, spacing: VTSMetrics.sectionSpacing) {
                    HStack(alignment: .center, spacing: 12) {
                        Image(systemName: tone.symbol)
                            .font(.title2)
                            .foregroundStyle(tone.color)
                            .accessibilityHidden(true)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(model.jobStatus)
                                .font(.headline)
                                .lineLimit(2)
                                .truncationMode(.middle)
                                .fixedSize(horizontal: false, vertical: true)
                            Text(isRunningThisWorkflow ? "Background engine is processing this job." : "Most recent run")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                        Spacer()
                        StatusPill(
                            title: model.jobOutcome.title,
                            tone: tone
                        )
                        if isRunningThisWorkflow {
                            Button("Cancel", role: .destructive) {
                                model.cancelActiveJob(source: "progress pane")
                            }
                        }
                    }

                    ProgressView(value: model.jobProgress, total: 100) {
                        Text("Completed clips")
                    } currentValueLabel: {
                        Text(model.jobProgressLabel)
                            .font(.system(.caption, design: .monospaced))
                    }
                    .accessibilityValue("\(model.jobProgressLabel), \(model.jobStatus)")

                    if !model.jobLogs.isEmpty {
                        DisclosureGroup("Diagnostic Log (\(model.jobLogs.count))", isExpanded: $logsExpanded) {
                            ScrollView {
                                Text(model.jobLogs.suffix(100).joined(separator: "\n"))
                                    .font(.system(.caption, design: .monospaced))
                                    .textSelection(.enabled)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                            }
                            .frame(minHeight: 90, maxHeight: 190)
                            .padding(9)
                            .background(.black.opacity(0.28), in: RoundedRectangle(cornerRadius: VTSMetrics.rowRadius))
                            .padding(.top, 6)
                        }
                    }

                    // Results stay expanded. Hiding what a job found behind a
                    // disclosure means the answer is never on screen when the
                    // job reports Complete.
                    if let result = model.jobResult {
                        VStack(alignment: .leading, spacing: 6) {
                            Text("Results")
                                .font(.headline)
                            Text(result)
                                .font(.callout)
                                .textSelection(.enabled)
                                .frame(maxWidth: .infinity, alignment: .leading)
                        }
                        .padding(10)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(.black.opacity(0.18), in: RoundedRectangle(cornerRadius: VTSMetrics.rowRadius))
                        .accessibilityIdentifier("job.results")
                    }
                    }
                    .padding(.top, 5)
                    .padding(.trailing, 4)
                }
            }
        } label: {
            Label("Progress & Results", systemImage: "waveform.path.ecg")
        }
    }
}

extension PrototypeViewModel {

}

private struct WorkflowOptionEditor: View {
    let option: WorkflowOptionDefinition
    let workflow: WorkflowStatus
    @ObservedObject var model: PrototypeViewModel
    var compact = false

    private var numberRange: ClosedRange<Double> {
        (option.minimum ?? -1_000_000)...(option.maximum ?? 1_000_000)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: compact ? 4 : VTSMetrics.compactSpacing) {
            if option.kind == "boolean" {
                Toggle(option.label, isOn: model.boolBinding(for: option, workflow: workflow))
                    .toggleStyle(.switch)
                    .controlSize(compact ? .small : .regular)
            } else {
                if compact {
                    HStack(spacing: 8) {
                        optionLabel
                            .frame(minWidth: 104, idealWidth: 128, alignment: .leading)
                        Spacer(minLength: 4)
                        compactControl
                    }
                } else {
                    optionLabel
                    switch option.kind {
                    case "choice":
                        Picker(option.label, selection: model.choiceBinding(for: option, workflow: workflow)) {
                            ForEach(option.choices) { choice in Text(choice.label).tag(choice.value) }
                        }
                        .labelsHidden()
                        .frame(maxWidth: .infinity, alignment: .leading)
                    case "number":
                        HStack {
                            TextField(
                                option.label,
                                value: model.numberBinding(for: option, workflow: workflow),
                                format: .number.precision(.fractionLength(0...2))
                            )
                            .labelsHidden()
                            .accessibilityLabel("\(option.label) stepper")
                            .textFieldStyle(.roundedBorder)
                            Stepper(
                                "",
                                value: model.numberBinding(for: option, workflow: workflow),
                                in: numberRange,
                                step: option.step ?? 1
                            )
                            .labelsHidden()
                        }
                    case "date":
                        DatePicker(
                            option.label,
                            selection: dateBinding,
                            displayedComponents: .date
                        )
                        .labelsHidden()
                    case "path":
                        HStack {
                            TextField(option.label, text: model.stringBinding(for: option, workflow: workflow))
                                .textFieldStyle(.roundedBorder)
                            Button("Browse…") { model.choosePath(for: option, workflow: workflow) }
                        }
                    default:
                        TextField(option.label, text: model.stringBinding(for: option, workflow: workflow))
                            .textFieldStyle(.roundedBorder)
                    }
                }
            }

            if !option.helpText.isEmpty {
                Text(option.helpText)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(compact ? 2 : nil)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(compact ? 9 : VTSMetrics.panelPadding)
        .frame(maxWidth: .infinity, minHeight: compact ? 44 : 68, alignment: .topLeading)
        .background(.quaternary.opacity(0.20), in: RoundedRectangle(cornerRadius: VTSMetrics.rowRadius))
        .overlay(
            RoundedRectangle(cornerRadius: VTSMetrics.rowRadius)
                .stroke(Color.secondary.opacity(0.08), lineWidth: 1)
        )
    }

    private var optionLabel: some View {
        HStack(spacing: 3) {
            Text(option.label)
                .font(compact ? .callout : .body)
                .fontWeight(.medium)
                .lineLimit(compact ? 2 : nil)
            if option.required {
                Text("Required")
                    .font(.caption2.bold())
                    .foregroundStyle(.orange)
            }
        }
    }

    @ViewBuilder
    private var compactControl: some View {
        switch option.kind {
        case "choice":
            Picker(option.label, selection: model.choiceBinding(for: option, workflow: workflow)) {
                ForEach(option.choices) { choice in Text(choice.label).tag(choice.value) }
            }
            .labelsHidden()
            .pickerStyle(.menu)
            .frame(maxWidth: 190, alignment: .trailing)
        case "number":
            HStack(spacing: 4) {
                TextField(
                    option.label,
                    value: model.numberBinding(for: option, workflow: workflow),
                    format: .number.precision(.fractionLength(0...2))
                )
                .labelsHidden()
                .accessibilityLabel("\(option.label) stepper")
                .textFieldStyle(.roundedBorder)
                .frame(width: 82)
                Stepper(
                    "",
                    value: model.numberBinding(for: option, workflow: workflow),
                    in: numberRange,
                    step: option.step ?? 1
                )
                .labelsHidden()
            }
        case "date":
            DatePicker(
                option.label,
                selection: dateBinding,
                displayedComponents: .date
            )
            .labelsHidden()
            .frame(maxWidth: 190, alignment: .trailing)
        case "path":
            HStack(spacing: 5) {
                TextField(option.label, text: model.stringBinding(for: option, workflow: workflow))
                    .textFieldStyle(.roundedBorder)
                    .frame(minWidth: 120)
                Button("Browse…") { model.choosePath(for: option, workflow: workflow) }
                    .controlSize(.small)
            }
        default:
            TextField(option.label, text: model.stringBinding(for: option, workflow: workflow))
                .textFieldStyle(.roundedBorder)
                .frame(minWidth: 130)
        }
    }

    private var dateBinding: Binding<Date> {
        Binding(
            get: {
                let components = model.stringBinding(for: option, workflow: workflow).wrappedValue
                    .split(separator: "-")
                    .compactMap { Int($0) }
                guard components.count == 3,
                      let date = Calendar.current.date(
                        from: DateComponents(
                            year: components[0],
                            month: components[1],
                            day: components[2]
                        )
                      )
                else { return Date() }
                return date
            },
            set: { date in
                let parts = Calendar.current.dateComponents([.year, .month, .day], from: date)
                guard let year = parts.year, let month = parts.month, let day = parts.day else { return }
                model.stringBinding(for: option, workflow: workflow).wrappedValue = String(
                    format: "%04d-%02d-%02d",
                    year,
                    month,
                    day
                )
            }
        )
    }
}

private struct SettingsPanelView: View {
    @ObservedObject var model: PrototypeViewModel
    @State private var selectedSection = "General"
    @State private var showResetConfirmation = false

    private let sectionOrder = [
        "General",
        "Timestamps",
        "Video Editing",
        "Finder Integration",
    ]

    private var availableSections: [String] {
        sectionOrder.filter { section in
            section == "Finder Integration" || model.settingsEntries.contains {
                displaySection(for: $0.option.settingsSection) == section
            }
        }
    }

    private var selectedEntries: [SettingsOptionEntry] {
        model.settingsEntries.filter {
            displaySection(for: $0.option.settingsSection) == selectedSection
        }
    }

    var body: some View {
        HStack(spacing: 0) {
            List(availableSections, id: \.self, selection: $selectedSection) { section in
                Label(section, systemImage: symbol(for: section)).tag(section)
            }
            .frame(minWidth: 210, idealWidth: 230, maxWidth: 250)

            Divider()

            VStack(alignment: .leading, spacing: 0) {
                ScrollView {
                    VStack(alignment: .leading, spacing: VTSMetrics.sectionSpacing) {
                        VStack(alignment: .leading, spacing: 5) {
                            Text(selectedSection)
                                .font(.title.bold())
                                .accessibilityHeading(.h1)
                            Text(description(for: selectedSection))
                                .font(.callout)
                                .foregroundStyle(.secondary)
                        }

                        LazyVGrid(
                            columns: [GridItem(.adaptive(minimum: 360), spacing: VTSMetrics.spacing)],
                            alignment: .leading,
                            spacing: VTSMetrics.spacing
                        ) {
                            ForEach(selectedEntries) { entry in
                                WorkflowOptionEditor(
                                    option: entry.option,
                                    workflow: entry.workflow,
                                    model: model,
                                    compact: true
                                )
                            }
                        }

                        if selectedSection == "Finder Integration" {
                            GroupBox {
                                VStack(alignment: .leading, spacing: 12) {
                                    HStack {
                                        Image(systemName: model.finderExtensionEnabled ? "checkmark.circle.fill" : "puzzlepiece.extension")
                                            .font(.title2)
                                            .foregroundStyle(model.finderExtensionEnabled ? .green : .secondary)
                                        Text("VTS Finder Actions")
                                            .font(.headline)
                                        Spacer()
                                    }
                                    Text(model.finderExtensionStatus)
                                        .foregroundStyle(.secondary)
                                    HStack {
                                        Button("Enable or Refresh Finder Actions") {
                                            Task { await model.enableFinderExtension() }
                                        }
                                        .buttonStyle(.borderedProminent)
                                        .disabled(model.isUpdatingFinderExtension)
                                        Button("Check Status") {
                                            Task { await model.refreshFinderExtensionStatus() }
                                        }
                                        .disabled(model.isUpdatingFinderExtension)
                                        if model.isUpdatingFinderExtension { ProgressView().controlSize(.small) }
                                    }
                                }
                                .padding(.top, 5)
                            }
                        }

                        if selectedEntries.isEmpty && selectedSection != "Finder Integration" {
                            PolishedEmptyState(
                                title: "No settings in this section",
                                message: "This VTS build does not currently expose any options here.",
                                symbol: "slider.horizontal.3"
                            )
                            .frame(minHeight: 180)
                        }
                    }
                    .padding(24)
                }

                Divider()
                HStack {
                    StatusPill(
                        title: model.settingsErrorMessage != nil ? "Save failed" : (model.hasUnsavedSettings ? "Unsaved changes" : "Saved"),
                        tone: model.settingsErrorMessage != nil ? .failure : (model.hasUnsavedSettings ? .attention : .ready)
                    )
                    Text(model.settingsMessage)
                        .font(.caption)
                        .foregroundStyle(model.settingsErrorMessage == nil ? Color.secondary : Color.red)
                        .lineLimit(2)
                    if model.settingsErrorMessage != nil {
                        Button("Dismiss settings error", systemImage: "xmark") {
                            model.dismissSettingsError()
                        }
                        .labelStyle(.iconOnly)
                        .buttonStyle(.plain)
                        .help("Dismiss settings error")
                    }
                    Spacer()
                    Button("Restore Defaults…") { showResetConfirmation = true }
                    Button("Save Settings") { Task { await model.saveSettings() } }
                        .buttonStyle(.borderedProminent)
                        .disabled(model.isSavingSettings || !model.hasUnsavedSettings)
                        .keyboardShortcut("s", modifiers: [.command])
                        .accessibilityIdentifier("settings.save")
                    if model.isSavingSettings { ProgressView().controlSize(.small) }
                }
                .padding(16)
                .background(.bar)
            }
        }
        .navigationTitle("Settings")
        .onAppear { selectRequestedSection() }
        .onChange(of: availableSections) { _, sections in
            if model.capabilities != nil,
               !sections.contains(selectedSection),
               let first = sections.first {
                selectedSection = first
            }
            selectRequestedSection()
        }
        .onChange(of: model.requestedSettingsSection) { _, _ in selectRequestedSection() }
        .alert("Restore all settings to their defaults?", isPresented: $showResetConfirmation) {
            Button("Cancel", role: .cancel) { }
            Button("Restore Defaults", role: .destructive) { model.resetSettingsDefaults() }
        } message: {
            Text("This changes the controls locally. Review them, then click Save Settings to use them across VTS.")
        }
    }

    private func selectRequestedSection() {
        guard model.capabilities != nil else { return }
        if let requested = model.requestedSettingsSection {
            let displayed = displaySection(for: requested)
            if availableSections.contains(displayed) {
                selectedSection = displayed
            }
            model.requestedSettingsSection = nil
        } else if !availableSections.contains(selectedSection), let first = availableSections.first {
            selectedSection = first
        }
    }

    private func displaySection(for sourceSection: String?) -> String {
        switch sourceSection {
        case "Time Correction", "Camera Rules", "Date & Naming":
            return "Timestamps"
        case "Editing & Delivery":
            return "Video Editing"
        case "Finder Integration":
            return "Finder Integration"
        default:
            return "General"
        }
    }

    private func symbol(for section: String) -> String {
        switch section {
        case "General": return "slider.horizontal.3"
        case "Timestamps": return "clock.badge.checkmark"
        case "Finder Integration": return "puzzlepiece.extension"
        default: return "scissors"
        }
    }

    private func description(for section: String) -> String {
        switch section {
        case "General": return "Common performance, import, organization, and original-file defaults."
        case "Timestamps": return "Date format, clock correction, and camera-specific timestamp rules."
        case "Finder Integration": return "Install or refresh VTS job actions in Finder's right-click menu."
        default: return "Defaults for trimming, merging, and transcoding videos."
        }
    }
}

private enum WorkflowInspectorPage: String, Identifiable, Hashable {
    case preview
    case activity

    var id: String { rawValue }

    var title: String {
        switch self {
        case .preview: return "Preview"
        case .activity: return "Progress"
        }
    }

    func title(for workflow: WorkflowStatus) -> String {
        if self == .preview && workflow.id == "trim" { return "Preview & Set Trim" }
        return title
    }

    func tabTitle(for workflow: WorkflowStatus) -> String {
        if self == .preview && workflow.id == "trim" { return "Preview & Trim" }
        return title
    }

    var symbol: String {
        switch self {
        case .preview: return "play.rectangle.fill"
        case .activity: return "waveform.path.ecg"
        }
    }
}

private struct WorkflowOptionsPanel: View {
    let workflow: WorkflowStatus
    let options: [WorkflowOptionDefinition]
    let advancedOptions: [WorkflowOptionDefinition]
    @ObservedObject var model: PrototypeViewModel
    var title = "2. Choose Options"

    var body: some View {
        GroupBox {
            VStack(spacing: 6) { optionEditors }
            .padding(.top, 4)
        } label: {
            HStack {
                Label(title, systemImage: "slider.horizontal.3")
                Spacer()
                Button("Reset") { model.resetOptions(for: workflow) }
                    .controlSize(.small)
            }
        }
    }

    @ViewBuilder
    private var optionEditors: some View {
        ForEach(options) { option in
            WorkflowOptionEditor(
                option: option,
                workflow: workflow,
                model: model,
                compact: true
            )
        }
        if !advancedOptions.isEmpty {
            DisclosureGroup("Advanced Options (\(advancedOptions.count))") {
                VStack(spacing: 6) {
                    ForEach(advancedOptions) { option in
                        WorkflowOptionEditor(
                            option: option,
                            workflow: workflow,
                            model: model,
                            compact: true
                        )
                    }
                }
                .padding(.top, 6)
            }
            .font(.callout)
            .padding(8)
            .background(.quaternary.opacity(0.12), in: RoundedRectangle(cornerRadius: VTSMetrics.rowRadius))
        }
    }
}

private struct WorkflowRunPanel: View {
    let workflow: WorkflowStatus
    @ObservedObject var model: PrototypeViewModel
    var stepTitle = "3. Start"

    private var disabledReason: String? { model.runDisabledReason(for: workflow) }

    private var actionTitle: String { workflow.launchLabel }

    var body: some View {
        VStack(alignment: .leading, spacing: VTSMetrics.spacing) {
            Label(stepTitle, systemImage: "play.circle")
                .font(.headline)

            if let error = model.workflowErrors[workflow.id] {
                InlineMessageBanner(message: error, tone: .failure) {
                    model.dismissWorkflowError(for: workflow)
                }
            } else if let disabledReason {
                Label(disabledReason, systemImage: "info.circle")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            } else if let workflowMessage = model.workflowMessages[workflow.id] {
                Text(workflowMessage)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            } else {
                Label("Ready to start", systemImage: "checkmark.circle")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            HStack {
                Button(actionTitle, systemImage: "play.fill") {
                    model.launchWorkflow(workflow)
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .disabled(disabledReason != nil)
                .keyboardShortcut(.return, modifiers: [.command])
                .help(disabledReason ?? "Run \(workflow.title) (Command-Return)")
                .accessibilityHint(disabledReason ?? "Starts this workflow on this Mac")
                .accessibilityIdentifier("workflow.run")

                if model.launchingWorkflowID == workflow.id {
                    ProgressView().controlSize(.small)
                }
                Spacer()
                Text("⌘↩")
                    .font(.system(.caption, design: .rounded).weight(.semibold))
                    .foregroundStyle(.tertiary)
                    .help("Keyboard shortcut: Command-Return")
            }
        }
        .padding(VTSMetrics.panelPadding)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: VTSMetrics.panelRadius))
        .overlay(RoundedRectangle(cornerRadius: VTSMetrics.panelRadius).stroke(Color.secondary.opacity(0.16)))
    }
}

private struct WorkflowModuleView: View {
    let workflow: WorkflowStatus
    @ObservedObject var model: PrototypeViewModel
    let openSettings: (String?) -> Void
    @State private var inspectorPage: WorkflowInspectorPage = .preview
    @AccessibilityFocusState private var inspectorHeadingFocused: Bool

    private func optionValue(_ key: String, fallback: String = "") -> String {
        workflow.options.first(where: { $0.key == key })
            .map { model.value(for: $0, workflow: workflow).stringValue } ?? fallback
    }

    private var jobOptions: [WorkflowOptionDefinition] {
        let options = workflow.options.filter { $0.placement == "workflow" }
        if workflow.id == "import-files" {
            return options.filter { ["import_date", "destination"].contains($0.key) }
        }
        if workflow.id == "clip-order" {
            return options.filter { ["clip_numbers", "auto_populate"].contains($0.key) }
        }
        if workflow.id == "trim" {
            return options.filter { ["output_mode", "include_audio"].contains($0.key) }
        }
        var filtered = options
        if workflow.id == "transcode", optionValue("max_size_enabled") != "true" {
            filtered = filtered.filter { !["max_size_gb", "size_strategy"].contains($0.key) }
        }
        if workflow.id == "merge", optionValue("client_delivery") != "true" {
            filtered = filtered.filter { !["client_quality", "client_max_size_gb"].contains($0.key) }
        }
        return filtered
    }

    private var advancedOptionKeys: Set<String> {
        switch workflow.id {
        case "transcode": return ["resolution", "include_audio", "size_strategy"]
        default: return []
        }
    }

    private var primaryJobOptions: [WorkflowOptionDefinition] {
        jobOptions.filter { !advancedOptionKeys.contains($0.key) }
    }

    private var advancedJobOptions: [WorkflowOptionDefinition] {
        jobOptions.filter { advancedOptionKeys.contains($0.key) }
    }

    private var settingsOptionCount: Int {
        workflow.options.filter { $0.placement == "settings" }.count
    }

    private var selectedURLs: [URL] {
        model.workflowSelection(for: workflow)
    }

    private var previewURL: URL? {
        model.previewURL(for: workflow)
    }

    private var inspectorPages: [WorkflowInspectorPage] {
        if workflow.id == "trim" { return [.preview, .activity] }
        return workflow.selectionMode == "files_or_folder"
            ? [.preview, .activity]
            : [.activity]
    }

    private var resolvedInspectorPage: WorkflowInspectorPage {
        inspectorPages.contains(inspectorPage) ? inspectorPage : (inspectorPages.first ?? .activity)
    }

    private var inspectorSelection: Binding<WorkflowInspectorPage> {
        Binding(
            get: { resolvedInspectorPage },
            set: { inspectorPage = $0 }
        )
    }

    private var displayStatus: WorkflowDisplayStatus {
        model.displayStatus(for: workflow)
    }

    private var outputHint: String? {
        switch workflow.id {
        case "timestamp":
            return "Timestamped videos replace the working clips; the originals are moved into originals. Footage on a camera card keeps its place."
        case "remove-audio":
            return "Video-only MP4 copies replace the working clips; the originals are moved into originals."
        case "clip-order":
            return "This task renames or organizes the queued files in place."
        case "video-minutes":
            return "This is read-only; it calculates totals without changing any video."
        case "trim":
            return optionValue("output_mode", fallback: "replace_and_archive") == "dedicated_folder"
                ? "Trimmed copies go into a trimmed_clips folder beside the source videos."
                : "Trimmed clips replace the working files; the untrimmed originals are moved into originals."
        case "transcode":
            return "Transcoded videos replace the working clips; the originals are moved into originals."
        case "merge":
            return "The combined video is saved in the working folder shared by the queued clips, and the clips it merged are moved into originals."
        default:
            return nil
        }
    }

    var body: some View {
        Group {
            if workflow.selectionMode == "none" {
                standaloneWorkflow
            } else {
                workflowColumns
            }
        }
        .navigationTitle(workflow.title)
        .onAppear {
            inspectorPage = .preview
        }
        .onChange(of: previewURL?.path ?? "") { _, path in
            if !path.isEmpty {
                inspectorPage = .preview
                inspectorHeadingFocused = true
            }
        }
        .onChange(of: model.lastJobWorkflowID) { _, workflowID in
            if workflowID == workflow.id {
                inspectorPage = .activity
                inspectorHeadingFocused = true
            }
        }
        .task(id: workflow.id == "trim" ? model.trimPreparationKey(for: workflow) : "") {
            if workflow.id == "trim" {
                await model.prepareNativeTrim(for: workflow)
            }
        }
    }

    private var workflowColumns: some View {
        GeometryReader { geometry in
            let controlsWidth: CGFloat = min(480, max(340, geometry.size.width * 0.4))

            HStack(spacing: 0) {
                controlsColumn
                    .frame(width: controlsWidth)
                    .frame(maxHeight: .infinity, alignment: .top)

                Divider()

                inspectorColumn
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }

    private var controlsColumn: some View {
        VStack(spacing: 0) {
            ScrollView {
                VStack(alignment: .leading, spacing: VTSMetrics.sectionSpacing) {
                    workflowHeader

                    if workflow.id == "trim", !model.trimCandidates.isEmpty {
                        NativeTrimQueueView(workflow: workflow, model: model)
                            .frame(minHeight: 210, idealHeight: 270, maxHeight: 340)
                    } else {
                        InputQueueView(workflow: workflow, model: model)
                            .frame(minHeight: selectedURLs.isEmpty ? 170 : 210, idealHeight: 250, maxHeight: 320)
                    }

                    if !jobOptions.isEmpty {
                        WorkflowOptionsPanel(
                            workflow: workflow,
                            options: primaryJobOptions,
                            advancedOptions: advancedJobOptions,
                            model: model
                        )
                    }

                    workflowHelpLinks
                }
                .padding(VTSMetrics.sectionSpacing)
                .frame(maxWidth: .infinity, alignment: .topLeading)
            }

            Divider()
            WorkflowRunPanel(
                workflow: workflow,
                model: model,
                stepTitle: jobOptions.isEmpty ? "2. Start" : "3. Start"
            )
                .padding(VTSMetrics.sectionSpacing)
        }
        .background(Color(nsColor: .windowBackgroundColor))
    }

    private var standaloneWorkflow: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: VTSMetrics.sectionSpacing) {
                workflowHeader

                if !jobOptions.isEmpty {
                    WorkflowOptionsPanel(
                        workflow: workflow,
                        options: primaryJobOptions,
                        advancedOptions: advancedJobOptions,
                        model: model,
                        title: "1. Choose Source and Destination"
                    )
                }

                workflowHelpLinks

                WorkflowRunPanel(
                    workflow: workflow,
                    model: model,
                    stepTitle: "2. Start"
                )

                if model.lastJobWorkflowID == workflow.id {
                    JobActivityView(workflow: workflow, model: model)
                        .frame(minHeight: 300)
                }
            }
            .padding(28)
            .frame(maxWidth: 820)
            .frame(maxWidth: .infinity)
        }
        .background(Color(nsColor: .windowBackgroundColor))
    }

    private var workflowHeader: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: workflow.symbol)
                .font(.system(size: 30))
                .foregroundStyle(Color.accentColor)
                .frame(width: 38)
            VStack(alignment: .leading, spacing: 4) {
                Text(workflow.title)
                    .font(.title2.bold())
                    .accessibilityHeading(.h1)
                Text(workflow.summary)
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 8)
            StatusPill(title: displayStatus.title, tone: displayStatus.tone)
                .help(displayStatus.detail)
        }
    }

    @ViewBuilder
    private var workflowHelpLinks: some View {
        if settingsOptionCount > 0 || workflow.interactiveNote != nil || outputHint != nil {
            VStack(alignment: .leading, spacing: 6) {
                if let outputHint {
                    Label(outputHint, systemImage: "folder.badge.checkmark")
                }
                if let note = workflow.interactiveNote {
                    Label(note, systemImage: "info.circle")
                }
                if settingsOptionCount > 0 {
                    Button {
                        openSettings(workflow.options.first(where: { $0.placement == "settings" })?.settingsSection)
                    } label: {
                        Label("Change defaults for this task", systemImage: "gearshape")
                    }
                    .buttonStyle(.link)
                    .help("Open settings shared by this workflow")
                }
            }
            .font(.caption)
            .foregroundStyle(.secondary)
            .padding(.horizontal, 6)
        }
    }

    private var inspectorColumn: some View {
        VStack(spacing: 0) {
            HStack {
                if inspectorPages.count > 1 {
                    Picker("Workspace", selection: inspectorSelection) {
                        ForEach(inspectorPages) { page in
                            Text(page.tabTitle(for: workflow)).tag(page)
                        }
                    }
                    .labelsHidden()
                    .pickerStyle(.segmented)
                    .frame(maxWidth: 560)
                    .accessibilityIdentifier("workflow.inspector-tabs")
                } else {
                    Label(resolvedInspectorPage.title(for: workflow), systemImage: resolvedInspectorPage.symbol)
                        .font(.headline)
                }
            }
            .frame(maxWidth: .infinity)
            .accessibilityHeading(.h2)
            .accessibilityFocused($inspectorHeadingFocused)
            .padding(.horizontal, 16)
            .padding(.vertical, 11)
            .background(.bar)

            Divider()

            inspectorContent
                .padding(16)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .background(Color(nsColor: .controlBackgroundColor))
    }

    @ViewBuilder
    private var inspectorContent: some View {
        switch resolvedInspectorPage {
        case .preview:
            if let previewURL {
                NativeVideoPreview(url: previewURL, workflow: workflow, model: model)
                    .id("\(workflow.id)-\(previewURL.path)")
            } else {
                PolishedEmptyState(
                    title: "No preview selected",
                    message: "Add a playable video, then select it to open the QuickTime preview.",
                    symbol: "play.rectangle"
                )
            }
        case .activity:
            JobActivityView(workflow: workflow, model: model)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        }
    }
}

private struct GlobalStatusBar: View {
    @ObservedObject var model: PrototypeViewModel
    @State private var confirmsGlobalCancel = false

    private var tone: VTSStatusTone {
        if model.errorMessage != nil { return .failure }
        if model.activeWorkflowID != nil { return .running }
        if model.capabilities == nil { return .neutral }
        return .ready
    }

    private var statusText: String {
        if model.jobOutcome == .failed, model.lastJobWorkflowID != nil {
            return "Job failed — open Progress for details."
        }
        if let error = model.errorMessage { return error }
        if model.activeWorkflowID != nil { return model.jobStatus }
        return model.message
    }

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: tone.symbol)
                .foregroundStyle(tone.color)
                .accessibilityHidden(true)
            Text(statusText)
                .font(.caption)
                .foregroundStyle(model.errorMessage == nil ? Color.secondary : Color.red)
                .lineLimit(1)
                .truncationMode(.middle)
            Spacer()
            if model.activeWorkflowID != nil {
                ProgressView(value: model.jobProgress, total: 100)
                    .frame(width: 170)
                Text(model.jobProgressLabel)
                    .font(.system(.caption2, design: .monospaced))
                    .foregroundStyle(.secondary)
                // A running job must be stoppable from anywhere, not only
                // from the Progress tab the user may have navigated away from.
                // Confirmed, because this button is always on screen beside a
                // scroll region and a single stray click was indistinguishable
                // from a deliberate stop.
                Button("Cancel", role: .destructive) { confirmsGlobalCancel = true }
                    .controlSize(.small)
                    .accessibilityIdentifier("global.cancel-job")
                    .confirmationDialog(
                        "Stop the running job?",
                        isPresented: $confirmsGlobalCancel
                    ) {
                        Button("Stop Job", role: .destructive) {
                            model.cancelActiveJob(source: "global status bar")
                        }
                        Button("Keep Running", role: .cancel) {}
                    } message: {
                        Text("Source videos and recorded decisions are never changed by stopping; finished work is kept where the job supports resuming.")
                    }
            }
        }
        .padding(.horizontal, 14)
        .frame(height: 36)
        .background(.bar)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Application status")
        .accessibilityValue(statusText)
        .accessibilityIdentifier("global.status")
    }
}

private struct StartTask: Identifiable {
    let id: String
    let title: String
    let description: String
    let symbol: String
    let category: String
    let launchLabel: String
    var workflowID: String { id }
    var optionDefaults: [String: JSONValue] = [:]
}

private enum StandaloneWorkflowCatalog {
    static let categories = ["Import & Timestamp", "Edit Video", "Utilities"]

    // Ordered for an investigator's camcorder and covert-camera workflow.
    static let tasks = [
        StartTask(
            id: "import-files", title: "Import Camera Media",
            description: "Copy camcorder and covert-camera footage for the selected recording date.",
            symbol: "square.and.arrow.down", category: "Import & Timestamp", launchLabel: "Import Media"
        ),
        StartTask(
            id: "timestamp", title: "Timestamp Videos",
            description: "Add recording date and time overlays, with camera-specific clock corrections.",
            symbol: "clock.badge.checkmark", category: "Import & Timestamp", launchLabel: "Timestamp Videos"
        ),
        StartTask(
            id: "remove-audio", title: "Remove Audio",
            description: "Create video-only copies without re-encoding the video.",
            symbol: "speaker.slash", category: "Edit Video", launchLabel: "Remove Audio"
        ),
        StartTask(
            id: "trim", title: "Trim Clips",
            description: "Set the start and end of each clip with frame-level controls.",
            symbol: "scissors", category: "Edit Video", launchLabel: "Trim Selected Clips"
        ),
        StartTask(
            id: "merge", title: "Merge Clips",
            description: "Join clips in chronological order into one video.",
            symbol: "rectangle.3.group", category: "Edit Video", launchLabel: "Merge Clips"
        ),
        StartTask(
            id: "transcode", title: "Transcode Videos",
            description: "Convert video quality and resolution, with optional file-size limits.",
            symbol: "arrow.triangle.2.circlepath", category: "Edit Video", launchLabel: "Transcode Videos"
        ),
        StartTask(
            id: "video-minutes", title: "Calculate Runtime",
            description: "Count clips and calculate their total runtime.",
            symbol: "sum", category: "Utilities", launchLabel: "Calculate Runtime"
        ),
        StartTask(
            id: "clip-order", title: "Order Clips",
            description: "Rename LawMate clips by recording time and number clips chronologically.",
            symbol: "list.number", category: "Utilities", launchLabel: "Order Clips"
        ),
    ]

    static func workflows(from capabilities: [WorkflowStatus]) -> [WorkflowStatus] {
        tasks.compactMap { task in
            guard var workflow = capabilities.first(where: { $0.id == task.workflowID }) else { return nil }
            workflow.title = task.title
            workflow.summary = task.description
            workflow.category = task.category
            workflow.symbol = task.symbol
            workflow.launchLabel = task.launchLabel
            workflow.options = workflow.options.compactMap { source in
                var option = source
                switch (workflow.id, option.key) {
                case ("import-files", "import_date"):
                    option.helpText = "Import footage recorded on this date."
                case ("transcode", "max_size_enabled"):
                    option.label = "Limit output file size"
                case ("transcode", "max_size_gb"):
                    option.label = "Maximum file size (GB)"
                case ("merge", "client_delivery"):
                    option.label = "Compress merged video"
                case ("merge", "client_quality"):
                    option.label = "Compression quality"
                case ("merge", "client_max_size_gb"):
                    option.label = "Maximum file size (GB)"
                default: break
                }
                return option
            }
            return workflow
        }
    }
}

private struct StartHereView: View {
    @ObservedObject var model: PrototypeViewModel
    let openTask: (StartTask) -> Void

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                VStack(alignment: .leading, spacing: 6) {
                    Text("Field Video Tools")
                        .font(.largeTitle.bold())
                        .accessibilityHeading(.h1)
                }

                if let error = model.engineErrorMessage {
                    InlineMessageBanner(message: error, tone: .failure)
                } else {
                    Label(
                        model.capabilities == nil
                            ? "Checking local processing components…"
                            : "Ready",
                        systemImage: model.capabilities == nil ? "circle.dotted" : "checkmark.circle.fill"
                    )
                    .font(.callout)
                    .foregroundStyle(model.capabilities == nil ? Color.secondary : Color.green)
                }

                ForEach(StandaloneWorkflowCatalog.categories, id: \.self) { category in
                    VStack(alignment: .leading, spacing: 12) {
                        Text(category)
                            .font(.headline)
                            .accessibilityHeading(.h2)
                        LazyVGrid(
                            columns: [GridItem(.flexible(), spacing: 14), GridItem(.flexible(), spacing: 14)],
                            alignment: .leading,
                            spacing: 14
                        ) {
                            ForEach(StandaloneWorkflowCatalog.tasks.filter { $0.category == category }) { task in
                                taskCard(task, compact: category == "Utilities")
                            }
                        }
                    }
                }

            }
            .padding(32)
            .frame(maxWidth: 1040)
            .frame(maxWidth: .infinity, alignment: .top)
        }
        .navigationTitle("Start Here")
        .background(Color(nsColor: .windowBackgroundColor))
    }

    private func taskCard(_ task: StartTask, compact: Bool = false) -> some View {
        let isAvailable = model.workflows.contains { $0.id == task.workflowID && model.isWorkflowVisible($0) }
        return Button { openTask(task) } label: {
            HStack(alignment: .top, spacing: 13) {
                Image(systemName: task.symbol)
                    .font(.system(size: compact ? 22 : 27))
                    .foregroundStyle(Color.accentColor)
                    .frame(width: 34, height: 34)
                VStack(alignment: .leading, spacing: 5) {
                    Text(task.title)
                        .font(compact ? .headline : .title3.bold())
                        .foregroundStyle(.primary)
                    Text(task.description)
                        .font(.callout)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: 0)
            }
            .padding(compact ? 14 : 17)
            .frame(maxWidth: .infinity, minHeight: compact ? 72 : 88, alignment: .topLeading)
            .background(.quaternary.opacity(0.18), in: RoundedRectangle(cornerRadius: 12))
            .overlay(
                RoundedRectangle(cornerRadius: 12)
                    .stroke(Color.secondary.opacity(0.13), lineWidth: 1)
            )
            .contentShape(RoundedRectangle(cornerRadius: 12))
        }
        .buttonStyle(.plain)
        .disabled(!isAvailable)
        .opacity(isAvailable ? 1 : 0.55)
        .accessibilityIdentifier("start.task.\(task.id)")
    }
}

private struct ContentView: View {
    @StateObject private var model = PrototypeViewModel.shared
    @State private var selection: String

    private let categories = StandaloneWorkflowCatalog.categories

    init() {
        let requested = Bundle.main.object(forInfoDictionaryKey: "VTSInitialSelection") as? String
        let requestedSelection = requested.flatMap { $0.isEmpty ? nil : $0 } ?? "home"
        let initialSelection = requestedSelection == "bridge" ? "status" : requestedSelection
        let supported = Set(StandaloneWorkflowCatalog.tasks.map(\.workflowID) + ["home", "status", "settings"])
        _selection = State(initialValue: supported.contains(initialSelection) ? initialSelection : "home")
    }

    var body: some View {
        NavigationSplitView {
            VStack(spacing: 0) {
                HStack(spacing: 11) {
                    Image(nsImage: NSApplication.shared.applicationIconImage)
                        .resizable()
                        .scaledToFit()
                        .frame(width: 34, height: 34)
                        .accessibilityHidden(true)
                    VStack(alignment: .leading, spacing: 1) {
                        Text("VTS")
                            .font(.title3.bold())
                        Text("Camera Video Toolkit")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                }
                .padding(.horizontal, 14)
                .padding(.vertical, 11)
                .accessibilityElement(children: .combine)
                .accessibilityLabel("VTS, Camera Video Toolkit")

                Divider()

                List(selection: $selection) {
                    Section {
                        Label("Start Here", systemImage: "house.fill")
                            .tag("home")
                            .accessibilityIdentifier("sidebar.start-here")
                    }

                    ForEach(categories, id: \.self) { category in
                        let workflows = model.workflows.filter {
                            $0.category == category && model.isWorkflowVisible($0)
                        }
                        if !workflows.isEmpty {
                            Section(category) {
                                ForEach(workflows) { workflow in
                                    Label(workflow.title, systemImage: workflow.symbol)
                                        .tag(workflow.id)
                                        .accessibilityIdentifier("sidebar.workflow.\(workflow.id)")
                                }
                            }
                        }
                    }

                    if model.workflows.isEmpty {
                        Section("Workflows") {
                            HStack { ProgressView().controlSize(.small); Text("Loading workflows…") }
                                .foregroundStyle(.secondary)
                        }
                    }

                    Section("VTS") {
                        Label("System Status", systemImage: "checkmark.circle")
                            .tag("status")
                            .accessibilityIdentifier("sidebar.system-status")
                        HStack {
                            Label("Settings", systemImage: "gearshape")
                            Spacer()
                            if model.hasUnsavedSettings {
                                Circle()
                                    .fill(.orange)
                                    .frame(width: 7, height: 7)
                                    .help("Unsaved settings")
                                    .accessibilityLabel("Unsaved settings")
                            }
                        }
                        .tag("settings")
                        .accessibilityIdentifier("sidebar.settings")
                    }
                }
                .listStyle(.sidebar)
            }
            .navigationSplitViewColumnWidth(min: 220, ideal: 245, max: 280)
        } detail: {
            VStack(spacing: 0) {
                selectedContent
                Divider()
                GlobalStatusBar(model: model)
            }
        }
        .task {
            if model.capabilities == nil { await model.refreshCapabilities() }
        }
        .onReceive(NotificationCenter.default.publisher(for: .vtsOpenSettings)) { _ in
            selection = "settings"
        }
        .onChange(of: model.requestedWorkflowID) { _, requested in
            guard let requested else { return }
            selection = requested
            model.requestedWorkflowID = nil
        }
    }

    @ViewBuilder
    private var selectedContent: some View {
        if selection == "home" {
            StartHereView(model: model) { task in
                open(task)
            }
        } else if selection == "status" || selection == "bridge" {
            SystemStatusView(model: model)
        } else if selection == "settings" {
            SettingsPanelView(model: model)
        } else if let workflow = model.workflows.first(where: { $0.id == selection }) {
            WorkflowModuleView(
                workflow: workflow,
                model: model,
                openSettings: { section in
                    model.requestedSettingsSection = section
                    selection = "settings"
                }
            )
                .id(workflow.id)
        } else if model.capabilities == nil {
            ProgressView("Loading VTS workflows…")
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else {
            VStack(spacing: 10) {
                Image(systemName: "questionmark.folder")
                    .font(.system(size: 36))
                    .foregroundStyle(.secondary)
                Text("Workflow Unavailable").font(.headline)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }

    private func open(_ task: StartTask) {
        guard let workflow = model.workflows.first(where: { $0.id == task.workflowID }) else {
            selection = task.workflowID
            return
        }
        for (key, value) in task.optionDefaults {
            if let option = workflow.options.first(where: { $0.key == key }) {
                model.setValue(value, for: option, workflow: workflow)
            }
        }
        selection = workflow.id
    }
}

private extension Notification.Name {
    static let vtsOpenSettings = Notification.Name("VTSOpenSettings")
}

/// The app is a menu bar agent. Its work starts from the Finder, so it has no
/// Dock icon and opens no window until one is asked for, and it keeps running
/// between jobs rather than paying a cold launch on every right-click.
@MainActor
/// Finder Sync only offers menus inside directories the extension monitors, and
/// a File Provider domain -- iCloud Drive above all -- can never be one of
/// them. That left the six jobs unreachable in exactly the folders the day's
/// footage is filed in. A service reads the Finder selection instead of the
/// enclosing folder, so these reach the same jobs anywhere, iCloud Drive
/// included.
private final class VTSServiceProvider: NSObject {
    static let shared = VTSServiceProvider()

    @objc func vtsTimestamp(
        _ pasteboard: NSPasteboard,
        userData: String?,
        error: AutoreleasingUnsafeMutablePointer<NSString>?
    ) {
        start("timestamp", from: pasteboard, reporting: error)
    }

    @objc func vtsRemoveAudio(
        _ pasteboard: NSPasteboard,
        userData: String?,
        error: AutoreleasingUnsafeMutablePointer<NSString>?
    ) {
        start("remove-audio", from: pasteboard, reporting: error)
    }

    @objc func vtsMerge(
        _ pasteboard: NSPasteboard,
        userData: String?,
        error: AutoreleasingUnsafeMutablePointer<NSString>?
    ) {
        start("merge", from: pasteboard, reporting: error)
    }

    @objc func vtsTranscode(
        _ pasteboard: NSPasteboard,
        userData: String?,
        error: AutoreleasingUnsafeMutablePointer<NSString>?
    ) {
        start("transcode", from: pasteboard, reporting: error)
    }

    @objc func vtsVideoMinutes(
        _ pasteboard: NSPasteboard,
        userData: String?,
        error: AutoreleasingUnsafeMutablePointer<NSString>?
    ) {
        start("video-minutes", from: pasteboard, reporting: error)
    }

    @objc func vtsClipOrder(
        _ pasteboard: NSPasteboard,
        userData: String?,
        error: AutoreleasingUnsafeMutablePointer<NSString>?
    ) {
        start("clip-order", from: pasteboard, reporting: error)
    }

    /// The job manifest is the one format the app already validates, so a
    /// service starts work through the same door as the Finder extension
    /// rather than growing a second way in.
    private func start(
        _ action: String,
        from pasteboard: NSPasteboard,
        reporting failure: AutoreleasingUnsafeMutablePointer<NSString>?
    ) {
        let selected = (pasteboard.readObjects(forClasses: [NSURL.self]) as? [URL]) ?? []
        let paths = selected.filter(\.isFileURL).map(\.path).filter { !$0.isEmpty }
        guard !paths.isEmpty else {
            failure?.pointee = "VTS received no files from the Finder selection." as NSString
            return
        }

        let jobID = UUID().uuidString.lowercased()
        let directory = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/VTS/Finder Jobs", isDirectory: true)
        let manifest: [String: Any] = [
            "version": 3,
            "job_id": jobID,
            "action": action,
            "paths": paths,
            "auto_start": true,
        ]
        do {
            try FileManager.default.createDirectory(
                at: directory,
                withIntermediateDirectories: true
            )
            let data = try JSONSerialization.data(withJSONObject: manifest)
            try data.write(
                to: directory.appendingPathComponent("\(jobID).json"),
                options: .atomic
            )
        } catch {
            failure?.pointee = "VTS could not stage this job: \(error.localizedDescription)" as NSString
            return
        }

        guard let jobURL = URL(string: "vts://finder-job/\(jobID)") else {
            failure?.pointee = "VTS could not address this job." as NSString
            return
        }
        Task { @MainActor in
            let model = PrototypeViewModel.shared
            guard let workflowID = await model.openFinderJob(jobURL) else { return }
            VTSWindowOpener.shared.openMainWindow()
            model.requestedWorkflowID = workflowID
        }
    }
}

private final class VTSAppDelegate: NSObject, NSApplicationDelegate {
    // A menu bar agent has no window to carry `onOpenURL`, so the Finder's job
    // URLs are delivered here instead. An auto-started job reports in its
    // floating panel and opens nothing; a job that still needs its options
    // opens the window and lands on the right tool.
    func application(_ application: NSApplication, open urls: [URL]) {
        for url in urls {
            Task { @MainActor in
                let model = PrototypeViewModel.shared
                guard let workflowID = await model.openFinderJob(url) else { return }
                VTSWindowOpener.shared.openMainWindow()
                model.requestedWorkflowID = workflowID
            }
        }
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        // Static services are advertised by Info.plist. The provider answers
        // a request when macOS starts VTS for a selected service.
        NSApplication.shared.servicesProvider = VTSServiceProvider.shared
        NSUpdateDynamicServices()
        // The app is installed for every account on this Mac. A default
        // PlugInKit election can recur after a failed setup or an update;
        // an explicit ignore election remains the user's choice.
        Task { @MainActor in
            await PrototypeViewModel.shared.repairFinderExtensionElectionIfNeeded()
        }
        VTSMenuBarController.shared.install()
        NotificationCenter.default.addObserver(
            forName: NSWindow.willCloseNotification,
            object: nil,
            queue: .main
        ) { _ in
            MainActor.assumeIsolated { VTSWindowOpener.shared.returnToAgentIfIdle() }
        }
    }

    // Quitting is the menu bar item's job, not a side effect of closing a
    // window an operator only opened to change a setting.
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        false
    }
}

/// SwiftUI hands out `openWindow` only inside a view, so the menu bar label --
/// the one view that is alive for as long as the agent is -- lends it to the
/// delegate and the progress panel.
@MainActor
private final class VTSWindowOpener {
    static let shared = VTSWindowOpener()

    private var window: NSWindow?

    private init() {}

    /// An agent has no menu bar of its own until a real window is on screen.
    /// Trim and Settings are ordinary windows and need one, so the policy
    /// changes with them and changes back when the last one closes.
    /// The scene never builds a window while the app is an agent -- verified
    /// on a running build, where the Window menu had nothing to restore -- so
    /// this owns the window instead of waiting for one to appear. It is built
    /// once and kept, so reopening returns to the same state.
    func openMainWindow() {
        NSApp.setActivationPolicy(.regular)
        mainWindow().makeKeyAndOrderFront(nil)
        // Activating in the same turn as the policy change does not take.
        DispatchQueue.main.async {
            NSApp.activate(ignoringOtherApps: true)
        }
    }

    private func mainWindow() -> NSWindow {
        if let window { return window }
        let controller = NSHostingController(
            rootView: ContentView().frame(minWidth: 1120, minHeight: 720)
        )
        let created = NSWindow(contentViewController: controller)
        created.title = "VTS"
        created.setContentSize(NSSize(width: 1440, height: 900))
        created.isReleasedWhenClosed = false
        created.center()
        window = created
        return created
    }

    func returnToAgentIfIdle() {
        // The close notification arrives before the window leaves the list.
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) {
            MainActor.assumeIsolated {
                let hasVisibleWindow = NSApp.windows.contains { window in
                    window.isVisible && !(window is NSPanel)
                }
                guard !hasVisibleWindow else { return }
                NSApp.setActivationPolicy(.accessory)
            }
        }
    }
}

@MainActor
private enum VTSLoginItem {
    static var isEnabled: Bool { SMAppService.mainApp.status == .enabled }

    static func setEnabled(_ enabled: Bool) {
        do {
            if enabled {
                try SMAppService.mainApp.register()
            } else {
                try SMAppService.mainApp.unregister()
            }
        } catch {
            NSLog("VTS could not change its login item: %@", error.localizedDescription)
        }
    }
}

/// SwiftUI's `MenuBarExtra` gives no control over where its item lands, and on
/// a crowded menu bar it was placed behind this Mac's notch: present, sized,
/// and invisible. An explicit status item can be named, which is what lets
/// macOS keep its position, and can say "VTS" in text if its image ever fails,
/// because an item that draws nothing looks exactly like a broken install.
@MainActor
private final class VTSMenuBarController: NSObject {
    static let shared = VTSMenuBarController()

    private var statusItem: NSStatusItem?

    /// macOS fills the menu bar right to left and, when it is full, drops the
    /// newcomer into the leftmost gap -- which on this Mac is behind the notch,
    /// where the item occupies space and draws nothing. Measured: without this
    /// the item sits at x=755 on a 1512-point screen and is invisible; with it,
    /// x=1295, in the status area. Seed the position once only, so that the
    /// operator's own placement is never overwritten afterwards.
    private static let preferredPositionKey = "NSStatusItem Preferred Position VTS"

    private static func seedPreferredPosition() {
        let defaults = UserDefaults.standard
        guard defaults.object(forKey: preferredPositionKey) == nil else { return }
        defaults.set(0.0, forKey: preferredPositionKey)
    }

    func install() {
        guard statusItem == nil else { return }
        Self.seedPreferredPosition()
        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        // Without an autosave name the item is a new stranger on every launch
        // and macOS never remembers where the operator put it.
        item.autosaveName = "VTS"
        item.isVisible = true
        if let button = item.button {
            if let icon = VTSMenuBarIcon.image {
                button.image = icon
                button.imagePosition = .imageOnly
            } else {
                button.title = "VTS"
            }
            button.toolTip = "VTS"
            button.setAccessibilityLabel("VTS")
        }
        item.menu = buildMenu()
        statusItem = item
    }

    private func buildMenu() -> NSMenu {
        let menu = NSMenu(title: "VTS")
        let open = NSMenuItem(
            title: "Open VTS…",
            action: #selector(openApp),
            keyEquivalent: ""
        )
        open.target = self
        menu.addItem(open)
        menu.addItem(.separator())
        let login = NSMenuItem(
            title: "Launch at Login",
            action: #selector(toggleLoginItem(_:)),
            keyEquivalent: ""
        )
        login.target = self
        login.state = VTSLoginItem.isEnabled ? .on : .off
        menu.addItem(login)
        menu.addItem(.separator())
        let quit = NSMenuItem(
            title: "Quit VTS",
            action: #selector(quitApp),
            keyEquivalent: "q"
        )
        quit.target = self
        menu.addItem(quit)
        return menu
    }

    @objc private func openApp() {
        VTSWindowOpener.shared.openMainWindow()
    }

    @objc private func toggleLoginItem(_ sender: NSMenuItem) {
        VTSLoginItem.setEnabled(!VTSLoginItem.isEnabled)
        sender.state = VTSLoginItem.isEnabled ? .on : .off
    }

    @objc private func quitApp() {
        NSApp.terminate(nil)
    }
}

private enum VTSMenuBarIcon {
    /// The app's own icon is a filled black tile, which a menu bar renders as a
    /// solid blob, so the menu bar uses a template symbol that inverts itself
    /// for light and dark. The real logo still fronts the progress panel, where
    /// it is drawn at a size that shows it.
    static let image: NSImage? = {
        guard let symbol = NSImage(
            systemSymbolName: "clock.badge.checkmark",
            accessibilityDescription: "VTS"
        ) else { return nil }
        symbol.isTemplate = true
        return symbol
    }()
}

@main
struct VTSApp: App {
    @NSApplicationDelegateAdaptor(VTSAppDelegate.self) private var appDelegate

    var body: some Scene {
        // The agent owns its window in VTSWindowOpener. A Window scene here
        // would be a second owner: suppressed at launch it still built one of
        // its own once the app activated, and the operator got two. This scene
        // carries the app's menus and never opens anything.
        Settings {
            EmptyView()
        }
        .commands {
            CommandGroup(replacing: .appSettings) {
                Button("Settings…") {
                    NotificationCenter.default.post(name: .vtsOpenSettings, object: nil)
                }
                .keyboardShortcut(",", modifiers: [.command])
            }
            // Without this the New Window shortcut still appears and is the
            // main way the extra windows kept arriving.
            CommandGroup(replacing: .newItem) { }
        }
    }
}

// MARK: - Finder quick action progress

/// A Finder quick action should feel like a Finder file operation. The app has
/// to launch, but nothing should take the screen away from the window the
/// operator started in, so every auto-started job reports through one small
/// floating panel and the main window stays hidden until it is asked for.
/// Calculate Runtime is the clearest case: the answer is a number, and reading
/// it should not cost a window.
@MainActor
private final class FinderJobProgressPanelController {
    static let shared = FinderJobProgressPanelController()

    private var panel: NSPanel?
    private var resizeObserver: NSObjectProtocol?

    private init() {}

    // The agent opens no window of its own, so there is nothing to hide and
    // nothing to race: the panel is the entire on-screen presence of a job
    // started from the Finder.
    func present(model: PrototypeViewModel) {
        showPanel(model: model)
    }

    func dismiss() {
        panel?.orderOut(nil)
    }

    /// Reveal what the job produced, in the Finder the operator started from.
    func reveal(_ urls: [URL]) {
        guard !urls.isEmpty else { return }
        NSWorkspace.shared.activateFileViewerSelecting(urls)
        dismiss()
    }

    private func showPanel(model: PrototypeViewModel) {
        if let panel {
            panel.orderFrontRegardless()
            return
        }
        let controller = NSHostingController(
            rootView: FinderJobProgressView(
                model: model,
                onReveal: { [weak self] urls in self?.reveal(urls) },
                onDismiss: { [weak self] in self?.dismiss() }
            )
        )
        controller.sizingOptions = [.preferredContentSize]
        let created = NSPanel(
            contentRect: NSRect(x: 0, y: 0, width: 380, height: 96),
            styleMask: [.titled, .closable, .utilityWindow, .nonactivatingPanel],
            backing: .buffered,
            defer: false
        )
        created.title = "VTS"
        created.isFloatingPanel = true
        created.level = .floating
        created.hidesOnDeactivate = false
        created.isReleasedWhenClosed = false
        created.becomesKeyOnlyIfNeeded = true
        // Without this the panel would vanish with the window it replaces.
        created.canHide = false
        created.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        created.contentViewController = controller
        created.setFrameOrigin(Self.bottomTrailingOrigin(for: created.frame.size))
        created.orderFrontRegardless()
        panel = created
        // A finishing job adds its result, and the panel stays anchored to its
        // corner rather than drifting across the screen as it grows.
        resizeObserver = NotificationCenter.default.addObserver(
            forName: NSWindow.didResizeNotification,
            object: created,
            queue: .main
        ) { [weak created] _ in
            guard let created else { return }
            MainActor.assumeIsolated {
                created.setFrameOrigin(
                    Self.bottomTrailingOrigin(for: created.frame.size)
                )
            }
        }
    }

    /// The top right is where macOS puts notifications, and one covered a
    /// reporting panel outright. The bottom right is the corner nothing else
    /// claims -- except a Dock set to hide, which `visibleFrame` does not
    /// reserve space for because it is not on screen when we ask. When nothing
    /// is reserved along the bottom, leave room for it to slide up into.
    private static func bottomTrailingOrigin(for size: NSSize) -> NSPoint {
        guard let screen = NSScreen.main else { return NSPoint(x: 120, y: 120) }
        let visible = screen.visibleFrame
        let bottomIsUnreserved = visible.minY <= screen.frame.minY + 1
        let bottomMargin: CGFloat = bottomIsUnreserved ? 96 : 24
        return NSPoint(x: visible.maxX - size.width - 24, y: visible.minY + bottomMargin)
    }
}

private struct FinderJobProgressView: View {
    @ObservedObject var model: PrototypeViewModel
    let onReveal: ([URL]) -> Void
    let onDismiss: () -> Void

    /// The operator started this from the Finder, so the useful destination is
    /// what the job produced, not the app. Only `outputs` is trusted here:
    /// timestamp's `processed_files` are source paths that may have been moved
    /// into originals/ by the time the job ends, and remove-audio's
    /// `output_folder` is only the first output's parent, which names one
    /// folder even when a selection spanned several.
    private var revealTargets: [URL] {
        guard isFinished, model.jobOutcome == .succeeded,
              let data = model.jobResult?.data(using: .utf8),
              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { return [] }
        if let outputs = object["outputs"] as? [String], !outputs.isEmpty {
            let urls = outputs.map { URL(fileURLWithPath: $0) }
            let parents = Set(urls.map { $0.deletingLastPathComponent().path })
            // Selecting files opens one Finder window per folder they live in,
            // so past a handful spread across folders, show the folders.
            if parents.count > 1, urls.count > 12 {
                return parents.sorted().map { URL(fileURLWithPath: $0) }
            }
            return urls
        }
        for key in ["output_folder", "working_folder", "archive_root"] {
            if let folder = object[key] as? String, !folder.isEmpty {
                return [URL(fileURLWithPath: folder)]
            }
        }
        return []
    }

    private var isFinished: Bool {
        [JobOutcome.succeeded, .failed, .cancelled].contains(model.jobOutcome)
    }

    /// What the panel says under the title. The engine's status carries each
    /// worker's own running commentary -- ffmpeg's per-file lines for a merge
    /// -- which is log material rather than something to read in a HUD, and
    /// every line of a different length resized the window while the job ran.
    /// The panel says what it is doing; the detail stays in the app's job log.
    private var caption: String {
        guard isFinished else { return "Working…" }
        switch model.jobOutcome {
        case .failed: return model.jobErrorMessage ?? "The job failed."
        case .cancelled: return "Cancelled."
        default: return readableResult ?? "Complete"
        }
    }

    /// Counting runtime answers with a sentence worth reading. Most workflows
    /// answer with their machine-readable record instead, which filled the
    /// panel with braces and absolute paths, so only the sentence is shown.
    /// A record may carry a `summary` sentence for an outcome the counts alone
    /// would misreport, such as a timestamp run that skipped every clip.
    private var readableResult: String? {
        guard let result = model.jobResult else { return nil }
        let trimmed = result.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        if trimmed.hasPrefix("{"),
           let data = trimmed.data(using: .utf8),
           let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let rawSummary = object["summary"] as? String {
            let summary = rawSummary.trimmingCharacters(in: .whitespacesAndNewlines)
            if !summary.isEmpty { return summary }
        }
        guard !trimmed.hasPrefix("{"), !trimmed.hasPrefix("[") else { return nil }
        return trimmed
    }

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(nsImage: NSApp.applicationIconImage)
                .resizable()
                .interpolation(.high)
                .frame(width: 38, height: 38)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 6) {
                Text(model.finderJobTitle ?? "VTS")
                    .font(.system(size: 13, weight: .semibold))
                if !isFinished {
                    if model.jobProgress > 0 {
                        ProgressView(value: min(model.jobProgress, 100), total: 100)
                            .progressViewStyle(.linear)
                    } else {
                        ProgressView()
                            .progressViewStyle(.linear)
                    }
                }
                // A counting job's whole answer is its result, so the panel
                // shows it here rather than sending the operator to a window.
                Text(caption)
                    .font(.system(size: 11))
                    .foregroundStyle(
                        model.jobOutcome == .failed
                            ? Color.red
                            : (isFinished && readableResult != nil ? Color.primary : Color.secondary)
                    )
                    .lineLimit(2)
                    .truncationMode(.middle)
                    .textSelection(.enabled)
            }
            Spacer(minLength: 0)
            VStack(alignment: .trailing, spacing: 6) {
                if isFinished {
                    // A read-only task made nothing, so it offers nothing.
                    let targets = revealTargets
                    if !targets.isEmpty {
                        Button("Reveal") { onReveal(targets) }
                    }
                    Button("Close") { onDismiss() }
                } else {
                    Button("Cancel") {
                        model.cancelActiveJob(source: "finder-progress-panel")
                    }
                }
            }
            .font(.system(size: 11))
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 12)
        .frame(width: 380, height: 84, alignment: .leading)
        // A job that finished with nothing to read and nothing to reveal
        // closes itself the way a Finder copy does. A result worth reading, an
        // output worth opening, and any failure all stay: dismissing a panel
        // whose Reveal button was never clicked throws the button away.
        .onChange(of: model.jobOutcome) { _, outcome in
            guard outcome == .succeeded || outcome == .cancelled else { return }
            Task {
                try? await Task.sleep(nanoseconds: 4_000_000_000)
                guard model.jobOutcome == outcome else { return }
                // Decided here rather than when the outcome arrived: the job's
                // result is a separate event and can be applied after it, and
                // a panel that read "nothing to show" a moment too early threw
                // away a Reveal button that existed by the time it closed.
                guard readableResult == nil, revealTargets.isEmpty else { return }
                onDismiss()
            }
        }
    }
}
