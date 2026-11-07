import XCTest

final class SmokeTests: XCTestCase {
    override func setUp() { continueAfterFailure = false }
    override func tearDown() { if let testRun = testRun, !testRun.hasSucceeded { let app = XCUIApplication(); picture(app, "failure-screen"); print(app.debugDescription) } }
    private func picture(_ app: XCUIApplication, _ name: String) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = name; attachment.lifetime = .keepAlways; add(attachment)
    }
    private func ready(_ element: XCUIElement) {
        XCTAssertTrue(element.waitForExistence(timeout: 30))
        let enabled = XCTNSPredicateExpectation(predicate: NSPredicate(format: "enabled == true"), object: element)
        XCTAssertEqual(XCTWaiter.wait(for: [enabled], timeout: 30), .completed)
    }
    func testHomeMenuAndSecureGuestRelaunch() {
        let app = XCUIApplication(); app.launch()
        let web = app.webViews.firstMatch
        let play = web.buttons["Play"].firstMatch
        ready(play); picture(app, "01-home")
        play.tap()
        let ai = web.buttons["Play with AI"].firstMatch
        ready(ai); ai.tap()
        XCTAssertTrue(web.buttons["Black"].waitForExistence(timeout: 10))
        XCTAssertTrue(web.buttons["White"].exists)
        picture(app, "02-ai-choice")
        web.buttons["Close"].firstMatch.tap()
        web.buttons["Home"].firstMatch.tap()
        let page = web.buttons["My Page"].firstMatch
        ready(page); page.tap()
        let field = web.textFields["Display name"].firstMatch
        let retry = web.buttons["Retry connection"].firstMatch
        if retry.waitForExistence(timeout: 5) { retry.tap() }
        ready(field); field.tap()
        field.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: 40))
        field.typeText("Smoke" + String(UUID().uuidString.prefix(4)))
        let expected = field.value as? String
        XCTAssertNotNil(expected)
        web.buttons["Save"].firstMatch.tap()
        XCTAssertTrue(app.staticTexts["Profile saved."].firstMatch.waitForExistence(timeout: 20))
        picture(app, "03-profile-saved")
        app.terminate(); app.launch()
        let reopened = app.webViews.firstMatch
        ready(reopened.buttons["My Page"].firstMatch)
        reopened.buttons["My Page"].firstMatch.tap()
        let restored = reopened.textFields["Display name"].firstMatch
        XCTAssertTrue(restored.waitForExistence(timeout: 30))
        let restoredValue = XCTNSPredicateExpectation(predicate: NSPredicate(format: "value == %@", expected!), object: restored)
        XCTAssertEqual(XCTWaiter.wait(for: [restoredValue], timeout: 30), .completed)
        XCTAssertEqual(restored.value as? String, expected)
        picture(app, "04-profile-after-relaunch")
    }
}
