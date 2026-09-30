const { withPodfile } = require("expo/config-plugins");

const PLUGIN_TAG = "studyroom-fmt-xcode-26-compatibility";
const BLOCK_START = `    # @generated begin ${PLUGIN_TAG}`;
const BLOCK_END = `    # @generated end ${PLUGIN_TAG}`;
const POST_INSTALL_ANCHOR = "  post_install do |installer|\n";

const PODFILE_PATCH = `${BLOCK_START}
    fmt_base_header = File.join(
      installer.sandbox.root,
      'fmt',
      'include',
      'fmt',
      'base.h'
    )
    if File.exist?(fmt_base_header)
      fmt_base_contents = File.read(fmt_base_header)
      fmt_version = '#define FMT_VERSION 110002'
      fmt_original_condition = '#elif defined(__apple_build_version__) && __apple_build_version__ < 14000029L'
      fmt_xcode_26_condition = '#elif defined(__apple_build_version__) && (__apple_build_version__ < 14000029L || FMT_CLANG_VERSION >= 2100)'

      if fmt_base_contents.include?(fmt_version)
        if fmt_base_contents.include?(fmt_original_condition)
          fmt_base_contents = fmt_base_contents.sub(
            fmt_original_condition,
            fmt_xcode_26_condition
          )
          File.chmod(0644, fmt_base_header)
          File.write(fmt_base_header, fmt_base_contents)
        elsif !fmt_base_contents.include?(fmt_xcode_26_condition)
          raise 'StudyRoom expected the React Native fmt 11.0.2 consteval condition'
        end
      end
    end
${BLOCK_END}`;

function injectFmtCompatibilityPatch(podfile) {
  const blockStart = podfile.indexOf(BLOCK_START);
  const blockEnd = podfile.indexOf(BLOCK_END);

  if ((blockStart === -1) !== (blockEnd === -1)) {
    throw new Error("StudyRoom found an incomplete generated fmt compatibility block");
  }

  if (blockStart !== -1) {
    const existingBlockEnd = blockEnd + BLOCK_END.length;
    return `${podfile.slice(0, blockStart)}${PODFILE_PATCH}${podfile.slice(existingBlockEnd)}`;
  }

  if (!podfile.includes(POST_INSTALL_ANCHOR)) {
    throw new Error("StudyRoom could not find the CocoaPods post_install hook");
  }

  return podfile.replace(
    POST_INSTALL_ANCHOR,
    `${POST_INSTALL_ANCHOR}${PODFILE_PATCH}\n`,
  );
}

function withFmtXcode26Compatibility(config) {
  return withPodfile(config, (podfileConfig) => {
    podfileConfig.modResults.contents = injectFmtCompatibilityPatch(
      podfileConfig.modResults.contents,
    );
    return podfileConfig;
  });
}

module.exports = withFmtXcode26Compatibility;
module.exports.injectFmtCompatibilityPatch = injectFmtCompatibilityPatch;
