#!/bin/bash
# Builds (when the sources changed) and runs the SimDriver XCTest server on one simulator.
#   driver/run-driver.sh --build-only                         build only (install.py does this)
#   driver/run-driver.sh <simulator-udid> <bundle-id> [port] [token]
# Normally started for you by the MCP server / CLI (start_driver). Running it by hand in a terminal
# shows everything xcodebuild prints. Extra xcodebuild flags (e.g. CODE_SIGNING_ALLOWED=NO) can be
# given in SIMCHAT_XCODEBUILD_ARGS.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
build="$here/.build"
mkdir -p "$build"
stamp="$build/built.stamp"
project=(-project "$here/SimDriver.xcodeproj" -scheme SimDriver -derivedDataPath "$build/DerivedData")
# shellcheck disable=SC2206
extra=(${SIMCHAT_XCODEBUILD_ARGS:-})

build_driver() {
  if [ ! -f "$stamp" ] || [ "$here/SimDriverUITests/SimDriverServer.swift" -nt "$stamp" ] \
     || [ "$here/SimDriver.xcodeproj/project.pbxproj" -nt "$stamp" ]; then
    echo "SIMCHAT building driver (first time takes 1-3 minutes)..."
    xcodebuild build-for-testing "${project[@]}" -destination "generic/platform=iOS Simulator" \
      ${extra[@]+"${extra[@]}"}
    touch "$stamp"
  else
    echo "SIMCHAT driver is up to date"
  fi
}

if [ "${1:-}" = "--build-only" ]; then
  build_driver
  exit 0
fi

udid="${1:?simulator udid}"
bundle="${2:?app bundle id}"
port="${3:-8787}"
token="${4:-}"
build_driver
echo "SIMCHAT starting driver on 127.0.0.1:$port for $bundle"
export TEST_RUNNER_SIMCHAT_PORT="$port"
export TEST_RUNNER_SIMCHAT_TOKEN="$token"
export TEST_RUNNER_SIMCHAT_BUNDLE_ID="$bundle"
exec xcodebuild test-without-building "${project[@]}" -destination "platform=iOS Simulator,id=$udid" \
  ${extra[@]+"${extra[@]}"} -only-testing:SimDriverUITests/SimDriverServer/testServe
