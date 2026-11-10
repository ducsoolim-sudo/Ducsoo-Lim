"""Apply reviewed native fixes to the hash-verified preview source."""
from pathlib import Path

root = Path("native-source/mobile")

def replace_checked(path, before, after):
    text = path.read_text()
    if after in text:
        return
    if text.count(before) != 1:
        raise RuntimeError(f"Unexpected source layout: {path}")
    path.write_text(text.replace(before, after))

replace_checked(
    root / "ios/App/App/SceneDelegate.swift",
    "rootViewController = CAPBridgeViewController()",
    "rootViewController = Go13ViewController()",
)
plugin = root / "ios/App/App/Go13SessionPlugin.swift"
replace_checked(plugin, 'call.reject("Local app required")',
                'call.reject("Local app required", "LOCAL_APP_REQUIRED")')
replace_checked(plugin, 'call.reject("Secure session unavailable")',
                r'call.reject("Secure session unavailable", "KEYCHAIN_READ_\(status)")')
replace_checked(plugin, 'call.reject("Secure session write failed")',
                r'call.reject("Secure session write failed", "KEYCHAIN_WRITE_\(status)")')
replace_checked(
    root / "test/project.test.mjs",
    "assert.match(read('ios/App/App/Base.lproj/Main.storyboard'),/Go13ViewController/);",
    "assert.match(read('ios/App/App/SceneDelegate.swift'),/rootViewController = Go13ViewController\\(\\)/);\n"
    " assert.match(read('ios/App/App/Go13AudioPlugin.swift'),/registerPluginInstance\\(Go13SessionPlugin\\(\\)\\)/);\n"
    " assert.match(read('ios/App/App/Base.lproj/Main.storyboard'),/Go13ViewController/);",
)
print("Verified scene controller and native plugin registration fix applied")
