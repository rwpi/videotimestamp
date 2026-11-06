#!/bin/bash
# Elect the installed Finder extensions and confirm Finder loaded Finder Sync.
set -euo pipefail

APP_PATH="${1:?usage: activate_finder_extension.sh /Applications/VTS.app}"
EXTENSION="$APP_PATH/Contents/PlugIns/VTSFinderExtension.appex"
EXECUTABLE="$EXTENSION/Contents/MacOS/VTSFinderExtension"
EXTENSION_ID="net.rwebber.vts.finder.extension"
ACTION_SLUGS="timestamp remove-audio merge transcode video-minutes clip-order"
ACTION_ID_PREFIX="net.rwebber.vts.quick-action."

LSREGISTER="${VTS_LSREGISTER_PATH:-/System/Library/Frameworks/CoreServices.framework/Versions/A/Frameworks/LaunchServices.framework/Versions/A/Support/lsregister}"
PLUGINKIT="${VTS_PLUGINKIT_PATH:-/usr/bin/pluginkit}"
OPEN="${VTS_OPEN_PATH:-/usr/bin/open}"
PGREP="${VTS_PGREP_PATH:-/usr/bin/pgrep}"
KILLALL="${VTS_KILLALL_PATH:-/usr/bin/killall}"
SLEEP="${VTS_SLEEP_PATH:-/bin/sleep}"
LOG="${VTS_LOG_PATH:-/usr/bin/log}"
PBS="${VTS_PBS_PATH:-/System/Library/CoreServices/pbs}"
PLISTBUDDY="${VTS_PLISTBUDDY_PATH:-/usr/libexec/PlistBuddy}"

if [[ ! -x "$EXECUTABLE" ]]; then
    echo "Finder extension is missing from $APP_PATH" >&2
    exit 1
fi

current_finder_pid() {
    "$PGREP" -u "$(/usr/bin/id -u)" -x Finder \
        | /usr/bin/awk '/^[0-9]+$/ { print; exit }'
}

ACTION_EXTENSIONS_PRESENT=0
validate_action_extensions() {
    local candidate slug path actual_id actual_point expected_id known
    for candidate in "$APP_PATH"/Contents/PlugIns/VTSQuickAction-*.appex; do
        [[ -d "$candidate" ]] || continue
        ACTION_EXTENSIONS_PRESENT=1
        known=0
        for slug in $ACTION_SLUGS; do
            if [[ "$candidate" == "$APP_PATH/Contents/PlugIns/VTSQuickAction-$slug.appex" ]]; then
                known=1
                break
            fi
        done
        if [[ "$known" != "1" ]]; then
            echo "Unexpected VTS Quick Action bundle: $candidate" >&2
            return 1
        fi
    done
    [[ "$ACTION_EXTENSIONS_PRESENT" == "1" ]] || return 0
    for slug in $ACTION_SLUGS; do
        path="$APP_PATH/Contents/PlugIns/VTSQuickAction-$slug.appex"
        expected_id="$ACTION_ID_PREFIX$slug"
        if [[ ! -x "$path/Contents/MacOS/VTSQuickAction" ]]; then
            echo "Finder Quick Action is missing from $path" >&2
            return 1
        fi
        actual_id="$("$PLISTBUDDY" -c 'Print :CFBundleIdentifier' "$path/Contents/Info.plist" 2>/dev/null)" || {
            echo "Could not read Finder Quick Action bundle ID in $path" >&2
            return 1
        }
        if [[ "$actual_id" != "$expected_id" ]]; then
            echo "Finder Quick Action bundle ID mismatch in $path: $actual_id" >&2
            return 1
        fi
        actual_point="$("$PLISTBUDDY" -c 'Print :NSExtension:NSExtensionPointIdentifier' "$path/Contents/Info.plist" 2>/dev/null)" || {
            echo "Could not read Finder Quick Action extension point in $path" >&2
            return 1
        }
        if [[ "$actual_point" != "com.apple.services" ]]; then
            echo "Finder Quick Action extension point mismatch in $path: $actual_point" >&2
            return 1
        fi
    done
}
validate_action_extensions

# Installing the app is system-wide, but Finder Sync election and these live
# activation checks belong to the invoking user's GUI session. Static Services
# are discovered from Info.plist; they do not require this SSH user to launch VTS.
if [[ -z "$(current_finder_pid || true)" ]]; then
    echo "Finder activation deferred: no Finder GUI session for $(/usr/bin/id -un)."
    exit 3
fi

# Start watching before registration and app launch. A surviving appex process
# can have a cancelled Finder connection, so process presence alone is not a
# useful post-install success signal.
LOG_FILE="$(/usr/bin/mktemp "${TMPDIR:-/tmp}/vts-finder-activation.XXXXXX")"
"$LOG" stream --style compact --level debug \
    --predicate 'process == "VTSFinderExtension" AND (subsystem == "com.apple.extensionkit" OR subsystem == "com.apple.PlugInKit")' \
    > "$LOG_FILE" 2>&1 &
LOG_STREAM_PID=$!
cleanup() {
    /bin/kill "$LOG_STREAM_PID" 2>/dev/null || true
    wait "$LOG_STREAM_PID" 2>/dev/null || true
    /bin/rm -f "$LOG_FILE"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
"$SLEEP" 1
if ! /bin/kill -0 "$LOG_STREAM_PID" 2>/dev/null; then
    echo "Could not read the Finder extension initialization log." >&2
    exit 1
fi

# A process from the replaced bundle keeps the same path in ps. Require a new
# PID so that a still-running old appex cannot pass the post-install check.
OLD_EXTENSION_PIDS="$("$PGREP" -u "$(/usr/bin/id -u)" -x VTSFinderExtension \
    | /usr/bin/awk '/^[0-9]+$/ { printf "%s ", $1 }' || true)"

new_installed_extension_pids() {
    local processes
    processes="$("$PGREP" -u "$(/usr/bin/id -u)" -fl VTSFinderExtension || true)"
    printf '%s\n' "$processes" | /usr/bin/awk \
        -v expected="$EXECUTABLE" -v old=" $OLD_EXTENSION_PIDS" '
        /^[0-9]+ / {
            pid = $1
            command = $0
            sub(/^[0-9]+ /, "", command)
            if (index(old, " " pid " ") == 0 &&
                (command == expected || index(command, expected " ") == 1)) printf "%s ", pid
        }
    '
}

finder_initialized_extension() {
    local extension_pids="$1" finder_pid="$2"
    [[ -n "$extension_pids" && -n "$finder_pid" ]] || return 1
    /usr/bin/awk -v allowed=" $extension_pids " -v finder="$finder_pid" '
        /VTSFinderExtension\[[0-9]+:/ {
            match($0, /VTSFinderExtension\[[0-9]+:/)
            appex_pid = substr($0, RSTART + 19, RLENGTH - 20)
            if (index(allowed, " " appex_pid " ") == 0) next
            if (index($0, "creating principle object:") &&
                index($0, "VTSFinderSync:") &&
                match($0, "connection from pid " finder "([^0-9]|$)")) {
                attached[appex_pid] = 1
            }
            if (match($0, "host connection from pid " finder " invalidated")) {
                delete attached[appex_pid]
            }
        }
        END {
            for (pid in attached) if (attached[pid]) exit 0
            exit 1
        }
    ' "$LOG_FILE"
}

# Finder Sync can only serve directories it monitors, so a File Provider domain
# such as iCloud Drive is permanently out of its reach. The services carry the
# same jobs there, which makes them part of a working install, not a nicety.
SERVICE_MESSAGES="vtsTimestamp vtsRemoveAudio vtsMerge vtsTranscode vtsVideoMinutes vtsClipOrder"

services_registered() {
    # Each cached service must name this installed bundle. Checking messages
    # and the path independently accepts a stale VTS alongside an unrelated
    # entry for the new bundle. Parse every record through its closing brace;
    # grep -q also risks a broken-pipe false negative on a large pbs dump.
    "$PBS" -dump 2>/dev/null | /usr/bin/awk -v expected="$APP_PATH" \
        -v required="$SERVICE_MESSAGES" '
        BEGIN {
            count = split(required, names, " ")
            for (i = 1; i <= count; i++) wanted[names[i]] = 1
        }
        /^        \{$/ {
            record = 1
            installed = owner = port = 0
            message = ""
            next
        }
        record && /^    \},?$/ {
            if (installed && owner && port && wanted[message]) found[message] = 1
            record = 0
            next
        }
        record && $0 == "        NSBundlePath = \"" expected "\";" { installed = 1 }
        record && $0 == "        NSBundleIdentifier = \"net.rwebber.vts\";" { owner = 1 }
        record && $0 == "        NSPortName = VTS;" { port = 1 }
        record && /^        NSMessage = / {
            message = $0
            sub(/^        NSMessage = /, "", message)
            sub(/;$/, "", message)
        }
        END {
            for (name in wanted) if (!found[name]) exit 1
        }
    '
}

wait_for_services() {
    local attempt
    for attempt in 1 2 3 4 5 6 7 8 9 10; do
        if services_registered; then
            return 0
        fi
        "$PBS" -update >/dev/null 2>&1 || true
        "$SLEEP" 1
    done
    return 1
}

extension_is_enabled() {
    local listing
    listing="$("$PLUGINKIT" -m -p com.apple.FinderSync -vvv)" || return 1
    printf '%s\n' "$listing" | /usr/bin/awk -v id="$EXTENSION_ID" '
        $1 == "+" && index($2, id "(") == 1 { found = 1 }
        END { exit !found }
    '
}

action_extension_is_enabled() {
    local id="$1" path="$2" listing
    listing="$("$PLUGINKIT" -m -i "$id" -vvv)" || return 1
    printf '%s\n' "$listing" | /usr/bin/awk -v id="$id" -v expected="$path" '
        /^[+ -] +[^ ]+\(/ {
            selected = ($1 == "+" && index($2, id "(") == 1)
            next
        }
        selected && /^[[:space:]]*Path = / {
            path = $0
            sub(/^[[:space:]]*Path = /, "", path)
            if (path == expected) found = 1
        }
        END { exit !found }
    '
}

wait_for_actions() {
    local attempt slug path id all_enabled
    [[ "$ACTION_EXTENSIONS_PRESENT" == "1" ]] || return 0
    for attempt in 1 2 3 4 5 6 7 8 9 10; do
        all_enabled=1
        for slug in $ACTION_SLUGS; do
            path="$APP_PATH/Contents/PlugIns/VTSQuickAction-$slug.appex"
            id="$ACTION_ID_PREFIX$slug"
            if ! action_extension_is_enabled "$id" "$path"; then
                all_enabled=0
                break
            fi
        done
        [[ "$all_enabled" == "1" ]] && return 0
        "$SLEEP" 1
    done
    return 1
}

wait_for_extension() {
    local attempt extension_pids finder_pid
    for attempt in 1 2 3 4 5 6 7 8 9 10; do
        if ! /bin/kill -0 "$LOG_STREAM_PID" 2>/dev/null; then
            return 1
        fi
        extension_pids="$(new_installed_extension_pids)"
        finder_pid="$(current_finder_pid || true)"
        if [[ -n "$finder_pid" && "$finder_pid" != "$RESTARTED_FINDER_PID" ]] && \
            extension_is_enabled && \
            finder_initialized_extension "$extension_pids" "$finder_pid"; then
            return 0
        fi
        "$SLEEP" 1
    done
    return 1
}

ACTION_MENU_CHANGED=0
if [[ "$ACTION_EXTENSIONS_PRESENT" == "1" ]]; then
    for slug in $ACTION_SLUGS; do
        action_path="$APP_PATH/Contents/PlugIns/VTSQuickAction-$slug.appex"
        if ! action_extension_is_enabled "$ACTION_ID_PREFIX$slug" "$action_path"; then
            ACTION_MENU_CHANGED=1
            break
        fi
    done
fi

"$LSREGISTER" -f "$APP_PATH"
"$PLUGINKIT" -a "$EXTENSION"
"$PLUGINKIT" -e use -i "$EXTENSION_ID"
if [[ "$ACTION_EXTENSIONS_PRESENT" == "1" ]]; then
    for slug in $ACTION_SLUGS; do
        "$PLUGINKIT" -a "$APP_PATH/Contents/PlugIns/VTSQuickAction-$slug.appex"
        "$PLUGINKIT" -e use -i "$ACTION_ID_PREFIX$slug"
    done
fi

# On this Mac, registering and electing a replaced bundle did not publish it
# to Finder until the containing app launched. It is a menu bar agent, so this
# does not open the main window or take focus from the operator.
"$OPEN" -g -a "$APP_PATH"

# Registering an update can start a second session alongside Finder's old
# session. Restart to retire those sessions, then require a different Finder
# PID so a pre-restart handshake cannot satisfy the check during shutdown.
RESTARTED_FINDER_PID=""
restart_finder() {
    RESTARTED_FINDER_PID="$(current_finder_pid || true)"
    "$KILLALL" -u "$(/usr/bin/id -un)" Finder
}
if [[ -n "$OLD_EXTENSION_PIDS" || "$ACTION_MENU_CHANGED" == "1" ]]; then
    restart_finder
fi

if ! wait_for_extension; then
    if ! /bin/kill -0 "$LOG_STREAM_PID" 2>/dev/null; then
        echo "Could not read the Finder extension initialization log." >&2
        exit 1
    fi
    # A first installation may also need a fresh Finder connection.
    if [[ -n "$RESTARTED_FINDER_PID" ]] || ! restart_finder || ! wait_for_extension; then
        if ! /bin/kill -0 "$LOG_STREAM_PID" 2>/dev/null; then
            echo "Could not read the Finder extension initialization log." >&2
            exit 1
        fi
        echo "Finder did not confirm initialization of the installed VTS extension from $EXECUTABLE" >&2
        exit 1
    fi
fi

if ! wait_for_services; then
    echo "macOS did not register the VTS services from $APP_PATH" >&2
    exit 1
fi

if ! wait_for_actions; then
    echo "macOS did not enable all six installed VTS Finder Quick Actions." >&2
    exit 1
fi

echo "Finder initialized the installed VTS extension: $EXECUTABLE"
echo "macOS registered the installed VTS services for file selections."
if [[ "$ACTION_EXTENSIONS_PRESENT" == "1" ]]; then
    echo "macOS enabled all six installed VTS Finder Quick Actions."
fi
