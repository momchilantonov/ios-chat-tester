import re
import unittest

from helpers import ROOT

DRIVER = ROOT / "tester" / "driver"


class DriverProjectTest(unittest.TestCase):
    """Static checks - the Swift/Xcode side can only really be verified on a Mac."""

    def test_pbxproj_references_are_defined(self):
        text = (DRIVER / "SimDriver.xcodeproj" / "project.pbxproj").read_text()
        defined = set(re.findall(r"^\s*([0-9A-F]{24}) (?:/\*.*?\*/ )?= \{", text, re.M))
        used = set(re.findall(r"\b([0-9A-F]{24})\b", text))
        self.assertTrue(defined)
        self.assertEqual(used - defined, set())
        self.assertEqual(text.count("{"), text.count("}"))
        self.assertEqual(text.count("("), text.count(")"))

    def test_scheme_points_at_the_target(self):
        pbx = (DRIVER / "SimDriver.xcodeproj" / "project.pbxproj").read_text()
        target = re.search(r"([0-9A-F]{24}) /\* SimDriverUITests \*/ = \{\s*isa = PBXNativeTarget", pbx).group(1)
        scheme = (DRIVER / "SimDriver.xcodeproj" / "xcshareddata" / "xcschemes" / "SimDriver.xcscheme").read_text()
        self.assertEqual(set(re.findall(r'BlueprintIdentifier = "(\w+)"', scheme)), {target})

    def test_python_uses_only_commands_the_swift_driver_serves(self):
        swift = (DRIVER / "SimDriverUITests" / "SimDriverServer.swift").read_text()
        served = set(re.findall(r'case "(\w+)":', swift))
        py = "".join(p.read_text() for p in (ROOT / "tester" / "simchat").glob("*.py"))
        used = set(re.findall(r'(?:_call|\.call)\("(\w+)"', py))
        self.assertTrue(used)
        self.assertEqual(used - served, set())
        self.assertEqual(swift.count("{"), swift.count("}"))

    def test_test_name_matches_run_script(self):
        script = (DRIVER / "run-driver.sh").read_text()
        swift = (DRIVER / "SimDriverUITests" / "SimDriverServer.swift").read_text()
        cls, method = re.search(r"-only-testing:SimDriverUITests/(\w+)/(\w+)", script).groups()
        self.assertIn("class %s: XCTestCase" % cls, swift)
        self.assertIn("func %s()" % method, swift)
        for env in re.findall(r"TEST_RUNNER_(\w+)=", script):
            self.assertIn('env["%s"]' % env, swift)


if __name__ == "__main__":
    unittest.main()
