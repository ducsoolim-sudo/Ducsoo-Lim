require 'xcodeproj'
require 'fileutils'
root = 'native-source/mobile/ios/App'
FileUtils.mkdir_p("#{root}/UITests")
FileUtils.cp('ios-smoke-test.swift', "#{root}/UITests/SmokeTests.swift")
project = Xcodeproj::Project.open("#{root}/App.xcodeproj")
app = project.targets.find { |target| target.name == 'App' }
abort 'Missing App target' unless app
tests = project.new_target(:ui_test_bundle, 'Go13Smoke', :ios, '15.0')
tests.add_dependency(app)
group = project.main_group.new_group('UITests', 'UITests')
tests.source_build_phase.add_file_reference(group.new_file('SmokeTests.swift'))
tests.build_configurations.each do |config|
  config.build_settings.merge!({
    'PRODUCT_BUNDLE_IDENTIFIER' => 'com.saistudio.go13.preview.smoketests',
    'GENERATE_INFOPLIST_FILE' => 'YES', 'TEST_TARGET_NAME' => 'App',
    'PRODUCT_NAME' => '$(TARGET_NAME)', 'PRODUCT_MODULE_NAME' => 'Go13Smoke',
    'SWIFT_VERSION' => '5.0', 'TARGETED_DEVICE_FAMILY' => '1',
    'SUPPORTED_PLATFORMS' => 'iphonesimulator',
    'CODE_SIGN_IDENTITY' => '-', 'CODE_SIGN_STYLE' => 'Automatic'
  })
end
project.save
scheme = Xcodeproj::XCScheme.new
scheme.add_build_target(app)
scheme.add_test_target(tests)
scheme.set_launch_target(app)
scheme.save_as(project.path, 'Go13Smoke', true)
