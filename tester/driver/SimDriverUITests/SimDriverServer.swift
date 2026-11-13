// SimDriver - a tiny UI driver for the iOS Simulator, built on Apple's XCTest.
//
// It runs as one never-ending UI test. It attaches to an app that is already installed (and usually
// already running) by bundle id and serves one JSON command per TCP connection on 127.0.0.1:
//
//   request : {"token": "...", "cmd": "snapshot", "args": {...}}\n
//   response: {"ok": true, ...}\n   or   {"ok": false, "error": "..."}\n
//
// Commands: ping, state, activate, launch, terminate, snapshot, tap, long_press, type, delete, swipe,
//           hittable, alerts, tap_alert, stop.  Coordinates are screen points, the same as the snapshot frames.
//
// Configuration comes from environment variables. xcodebuild forwards TEST_RUNNER_<NAME> to the test
// process as <NAME>:  SIMCHAT_PORT, SIMCHAT_TOKEN, SIMCHAT_BUNDLE_ID.

import Foundation
import XCTest

final class SimDriverServer: XCTestCase {
    private var lastIssue: String?

    override func setUp() {
        super.setUp()
        continueAfterFailure = true
    }

    // XCTest reports UI problems (element not hittable, no keyboard focus, ...) as test issues.
    // Remember the message and return it to the client instead of failing the never-ending test.
    override func record(_ issue: XCTIssue) {
        lastIssue = issue.compactDescription
    }

    func testServe() throws {
        let env = ProcessInfo.processInfo.environment
        let port = UInt16(env["SIMCHAT_PORT"] ?? "") ?? 8787
        let token = env["SIMCHAT_TOKEN"] ?? ""
        let bundleId = env["SIMCHAT_BUNDLE_ID"] ?? ""
        if bundleId.isEmpty {
            NSLog("SIMCHAT error: SIMCHAT_BUNDLE_ID is not set")
            return
        }
        let server = try TCPServer(port: port)
        let handler = CommandHandler(bundleId: bundleId, issue: { [unowned self] in
            let message = self.lastIssue
            self.lastIssue = nil
            return message
        })
        NSLog("SIMCHAT ready on 127.0.0.1:\(port) for \(bundleId)")

        while !handler.stopRequested {
            guard let client = server.waitForClient(timeoutMs: 250) else { continue }
            autoreleasepool {
                var reply: [String: Any]
                if let line = client.readLine(),
                   let data = line.data(using: .utf8),
                   let request = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] {
                    if !token.isEmpty && (request["token"] as? String) != token {
                        reply = ["ok": false, "error": "bad token"]
                    } else {
                        let cmd = request["cmd"] as? String ?? ""
                        let args = request["args"] as? [String: Any] ?? [:]
                        lastIssue = nil
                        reply = handler.handle(cmd, args)
                    }
                } else {
                    reply = ["ok": false, "error": "request must be one JSON object per line"]
                }
                client.writeLine(Json.encode(reply))
                client.close()
            }
        }
        server.close()
        NSLog("SIMCHAT stopped")
    }
}

// MARK: - Commands

final class CommandHandler {
    let bundleId: String
    let app: XCUIApplication
    let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")
    private let issue: () -> String?
    private(set) var stopRequested = false

    init(bundleId: String, issue: @escaping () -> String?) {
        self.bundleId = bundleId
        self.app = XCUIApplication(bundleIdentifier: bundleId)
        self.issue = issue
    }

    func handle(_ cmd: String, _ args: [String: Any]) -> [String: Any] {
        var result: [String: Any]
        switch cmd {
        case "ping":
            result = ["driver": "simchat", "version": 2, "bundle_id": bundleId]
        case "state":
            result = ["app_state": stateName(app.state)]
        case "activate":
            app.activate()
            result = ["app_state": stateName(app.state)]
        case "launch":
            if app.state != .notRunning { app.terminate() }
            app.launchArguments = (args["arguments"] as? [String]) ?? []
            app.launchEnvironment = (args["environment"] as? [String: String]) ?? [:]
            app.launch()
            result = ["app_state": stateName(app.state)]
        case "terminate":
            app.terminate()
            result = ["app_state": stateName(app.state)]
        case "snapshot":
            result = snapshot()
        case "tap":
            guard let p = point(args) else { return fail("tap needs numeric x and y") }
            coordinate(p).tap()
            result = [:]
        case "long_press":
            guard let p = point(args) else { return fail("long_press needs numeric x and y") }
            coordinate(p).press(forDuration: number(args["duration"]) ?? 1.0)
            result = [:]
        case "type":
            guard let text = args["text"] as? String, !text.isEmpty else { return fail("type needs text") }
            app.typeText(text)
            result = [:]
        case "delete":
            let count = max(0, min(Int(number(args["count"]) ?? 0), 5000))
            if count > 0 {
                app.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: count))
            }
            result = [:]
        case "swipe":
            guard let a = point(args, "x1", "y1"), let b = point(args, "x2", "y2") else {
                return fail("swipe needs x1, y1, x2, y2")
            }
            switch args["speed"] as? String ?? "normal" {
            case "fast":
                coordinate(a).press(forDuration: 0.05, thenDragTo: coordinate(b),
                                    withVelocity: .fast, thenHoldForDuration: 0)
            case "slow":
                coordinate(a).press(forDuration: 0.05, thenDragTo: coordinate(b),
                                    withVelocity: .slow, thenHoldForDuration: 0)
            default:
                coordinate(a).press(forDuration: 0.05, thenDragTo: coordinate(b))
            }
            result = [:]
        case "hittable":
            // Which elements with this type and label (or id) can really be hit. Hidden copies of old buttons
            // stay in the accessibility tree; a tap on them lands on whatever is drawn underneath.
            let label = args["label"] as? String ?? ""
            let ident = args["id"] as? String ?? ""
            guard !label.isEmpty || !ident.isEmpty else { return fail("hittable needs label or id") }
            let type = knownTypes.first { typeName($0) == (args["type"] as? String ?? "") } ?? .any
            let predicate = label.isEmpty ? NSPredicate(format: "identifier == %@", ident)
                                          : NSPredicate(format: "label == %@", label)
            var found: [[String: Any]] = []
            for el in app.descendants(matching: type).matching(predicate).allElementsBoundByIndex.prefix(12)
            where el.exists {
                let f = el.frame
                found.append(["x": Double(f.origin.x), "y": Double(f.origin.y), "w": Double(f.width),
                              "h": Double(f.height), "hittable": el.isHittable])
            }
            result = ["elements": found]
        case "alerts":
            result = ["alerts": alerts()]
        case "tap_alert":
            guard let label = args["label"] as? String else { return fail("tap_alert needs label") }
            let button = springboard.alerts.buttons[label]
            guard button.exists else { return fail("no system alert button '\(label)'") }
            button.tap()
            result = [:]
        case "stop":
            stopRequested = true
            result = [:]
        default:
            return fail("unknown command '\(cmd)'")
        }
        if let message = issue() {
            return fail(message)
        }
        result["ok"] = true
        return result
    }

    private func fail(_ message: String) -> [String: Any] {
        return ["ok": false, "error": message]
    }

    private func coordinate(_ p: CGPoint) -> XCUICoordinate {
        return app.coordinate(withNormalizedOffset: CGVector(dx: 0, dy: 0))
            .withOffset(CGVector(dx: p.x, dy: p.y))
    }

    private func number(_ any: Any?) -> Double? {
        if let n = any as? NSNumber { return n.doubleValue }
        if let s = any as? String { return Double(s) }
        return nil
    }

    private func point(_ args: [String: Any], _ xKey: String = "x", _ yKey: String = "y") -> CGPoint? {
        guard let x = number(args[xKey]), let y = number(args[yKey]) else { return nil }
        return CGPoint(x: x, y: y)
    }

    private func snapshot() -> [String: Any] {
        let state = app.state
        guard state == .runningForeground else {
            return ["app_state": stateName(state), "elements": [], "keyboard": false,
                    "alerts": alerts()]
        }
        guard let root = try? app.snapshot() else {
            return ["app_state": stateName(state), "elements": [], "keyboard": false,
                    "alerts": alerts(), "warning": issue() ?? "snapshot failed"]
        }
        var elements: [[String: Any]] = []
        var keyboard = false
        walk(root, depth: 0, into: &elements, keyboard: &keyboard)
        let f = root.frame
        return ["app_state": stateName(state),
                "screen": ["w": Double(f.width), "h": Double(f.height)],
                "keyboard": keyboard,
                "elements": elements,
                "alerts": alerts()]
    }

    private func walk(_ s: XCUIElementSnapshot, depth: Int, into out: inout [[String: Any]],
                      keyboard: inout Bool) {
        if s.elementType == .keyboard {
            keyboard = true
            return  // individual keys are noise
        }
        let f = s.frame
        var value = ""
        if let v = s.value as? String { value = v } else if let v = s.value { value = "\(v)" }
        let label = s.label
        let ident = s.identifier
        let placeholder = s.placeholderValue ?? ""
        let interesting = !label.isEmpty || !ident.isEmpty || !value.isEmpty
            || interactiveTypes.contains(s.elementType)
        if interesting && f.width > 0 && f.height > 0 {
            out.append([
                "type": typeName(s.elementType), "label": label, "id": ident, "value": value,
                "placeholder": placeholder, "enabled": s.isEnabled, "selected": s.isSelected,
                "x": Double(f.origin.x), "y": Double(f.origin.y),
                "w": Double(f.width), "h": Double(f.height), "depth": depth,
            ])
        }
        for child in s.children {
            walk(child, depth: depth + 1, into: &out, keyboard: &keyboard)
        }
    }

    private func alerts() -> [[String: Any]] {
        var list: [[String: Any]] = []
        for alert in springboard.alerts.allElementsBoundByIndex where alert.exists {
            let buttons = alert.buttons.allElementsBoundByIndex.map { $0.label }
            list.append(["label": alert.label, "buttons": buttons])
        }
        return list
    }

    // Reported even without a label: things to tap/type into, and scroll containers to swipe (carousels).
    private let interactiveTypes: Set<XCUIElement.ElementType> = [
        .button, .textField, .secureTextField, .textView, .searchField, .link, .cell, .`switch`,
        .slider, .scrollView, .collectionView, .table, .toggle, .checkBox, .radioButton, .segmentedControl,
        .picker, .pickerWheel, .stepper, .webView, .alert, .sheet,
    ]

    // Types the "hittable" command can be asked about (by the names typeName() gives them).
    private let knownTypes: [XCUIElement.ElementType] = [
        .button, .staticText, .link, .cell, .other, .textView, .textField, .image, .`switch`, .toggle,
        .checkBox, .radioButton, .slider, .segmentedControl, .picker, .pickerWheel, .stepper, .webView,
        .alert, .sheet,
    ]

    private func typeName(_ t: XCUIElement.ElementType) -> String {
        switch t {
        case .button: return "button"
        case .staticText: return "text"
        case .textField: return "textField"
        case .secureTextField: return "secureTextField"
        case .textView: return "textView"
        case .searchField: return "searchField"
        case .image: return "image"
        case .cell: return "cell"
        case .link: return "link"
        case .`switch`: return "switch"
        case .slider: return "slider"
        case .toggle: return "toggle"
        case .checkBox: return "checkBox"
        case .radioButton: return "radioButton"
        case .segmentedControl: return "segmentedControl"
        case .picker: return "picker"
        case .pickerWheel: return "pickerWheel"
        case .stepper: return "stepper"
        case .alert: return "alert"
        case .sheet: return "sheet"
        case .navigationBar: return "navigationBar"
        case .tabBar: return "tabBar"
        case .toolbar: return "toolbar"
        case .scrollView: return "scrollView"
        case .table: return "table"
        case .collectionView: return "collectionView"
        case .webView: return "webView"
        case .window: return "window"
        case .application: return "application"
        case .other: return "other"
        default: return "type\(t.rawValue)"
        }
    }

    private func stateName(_ s: XCUIApplication.State) -> String {
        switch s {
        case .notRunning: return "notRunning"
        case .runningBackgroundSuspended: return "backgroundSuspended"
        case .runningBackground: return "background"
        case .runningForeground: return "foreground"
        default: return "unknown"
        }
    }
}

// MARK: - JSON

enum Json {
    static func encode(_ object: [String: Any]) -> String {
        guard JSONSerialization.isValidJSONObject(object),
              let data = try? JSONSerialization.data(withJSONObject: object),
              let text = String(data: data, encoding: .utf8) else {
            return "{\"ok\":false,\"error\":\"response not JSON-serialisable\"}"
        }
        return text
    }
}

// MARK: - Minimal blocking TCP server on 127.0.0.1 (BSD sockets, one request per connection)

enum SocketError: Error {
    case failed(String)
}

final class TCPServer {
    private let fd: Int32

    init(port: UInt16) throws {
        fd = socket(AF_INET, SOCK_STREAM, 0)
        guard fd >= 0 else { throw SocketError.failed("socket() errno \(errno)") }
        var yes: Int32 = 1
        setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &yes, socklen_t(MemoryLayout<Int32>.size))
        var addr = sockaddr_in()
        addr.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
        addr.sin_family = sa_family_t(AF_INET)
        addr.sin_port = port.bigEndian
        addr.sin_addr.s_addr = inet_addr("127.0.0.1")
        let bound = withUnsafePointer(to: &addr) { pointer in
            pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                bind(fd, $0, socklen_t(MemoryLayout<sockaddr_in>.size))
            }
        }
        guard bound == 0 else {
            Darwin.close(fd)
            throw SocketError.failed("bind 127.0.0.1:\(port) errno \(errno) - port in use?")
        }
        guard listen(fd, 8) == 0 else {
            Darwin.close(fd)
            throw SocketError.failed("listen() errno \(errno)")
        }
    }

    func waitForClient(timeoutMs: Int32) -> TCPClient? {
        var pfd = pollfd(fd: fd, events: Int16(POLLIN), revents: 0)
        guard poll(&pfd, 1, timeoutMs) > 0 else { return nil }
        let client = Darwin.accept(fd, nil, nil)
        return client >= 0 ? TCPClient(fd: client) : nil
    }

    func close() {
        Darwin.close(fd)
    }
}

final class TCPClient {
    private let fd: Int32

    init(fd: Int32) {
        self.fd = fd
        var yes: Int32 = 1
        setsockopt(fd, SOL_SOCKET, SO_NOSIGPIPE, &yes, socklen_t(MemoryLayout<Int32>.size))
        var timeout = timeval(tv_sec: 10, tv_usec: 0)
        setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, socklen_t(MemoryLayout<timeval>.size))
    }

    func readLine() -> String? {
        var data = Data()
        var buffer = [UInt8](repeating: 0, count: 65536)
        while data.count < 4_000_000 {
            let n = recv(fd, &buffer, buffer.count, 0)
            if n <= 0 { break }
            data.append(contentsOf: buffer[0..<n])
            if buffer[0..<n].contains(10) { break }
        }
        guard let newline = data.firstIndex(of: 10) else {
            return data.isEmpty ? nil : String(data: data, encoding: .utf8)
        }
        return String(data: data[data.startIndex..<newline], encoding: .utf8)
    }

    func writeLine(_ text: String) {
        let bytes = Array((text + "\n").utf8)
        var offset = 0
        while offset < bytes.count {
            let sent = bytes[offset...].withUnsafeBytes { raw in
                send(fd, raw.baseAddress, raw.count, 0)
            }
            if sent <= 0 { break }
            offset += sent
        }
    }

    func close() {
        Darwin.close(fd)
    }
}
