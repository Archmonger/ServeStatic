"""Parses Keep a Changelog format and ensures it is valid"""

# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

# ruff: noqa: PERF401
import re
import sys

GITHUB_COMPARE_URL_START_RE = r"https?://github.com/[^/]+/[^/]+/compare/"
GITHUB_COMPARE_URL_RE = GITHUB_COMPARE_URL_START_RE + r"([\w.]+)\.\.\.([\w.]+)"
GITHUB_RELEASE_TAG_URL_START_RE = r"https?://github.com/[^/]+/[^/]+/releases/tag/"
GITHUB_RELEASE_TAG_URL_RE = GITHUB_RELEASE_TAG_URL_START_RE + r"([\w.]+)"
UNRELEASED_HEADER = "## [Unreleased]\n"
VERSION_HEADER_START_RE = r"## \[([\w.]+)\]"
VERSION_HEADER_FULL_RE = VERSION_HEADER_START_RE + r" - \d{4}-\d{2}-\d{2}\n"
UNRELEASED_HYPERLINK_RE = r"\[Unreleased\]: " + GITHUB_COMPARE_URL_RE + r"\n"
VERSION_HYPERLINK_START_RE = r"\[([\w.]+)\]: "
VERSION_HYPERLINK_RE = VERSION_HYPERLINK_START_RE + GITHUB_COMPARE_URL_RE + r"\n"
INITIAL_VERSION_RE = VERSION_HYPERLINK_START_RE + GITHUB_RELEASE_TAG_URL_RE + r"\n"
SECTION_HEADER_RE = r"### ([^\n]+)\n"
HTML_COMMENT_RE = r"<!--.*?-->", re.DOTALL


def validate_changelog(changelog_path="CHANGELOG.md"):
    errors = []
    # Read the contents of the changelog file
    with open(changelog_path, encoding="UTF-8") as file:
        changelog = file.read()

    # Remove HTML comments
    changelog = re.sub(HTML_COMMENT_RE[0], "", changelog, flags=HTML_COMMENT_RE[1])

    # Replace duplicate newlines with a single newline
    changelog = re.sub(r"\n+", "\n", changelog)

    # Ensure `## [Unreleased]\n` is present
    if changelog.find(UNRELEASED_HEADER) == -1:
        errors.append("Changelog does contain '## [Unreleased]'")

    # Ensure unreleased has a URL
    unreleased_url = re.search(UNRELEASED_HYPERLINK_RE, changelog)
    if unreleased_url is None:
        errors.append("Unreleased does not have a URL")

    # Ensure UNRELEASED_URL_REGEX ends in "HEAD"
    if unreleased_url and unreleased_url[2] != "HEAD":
        errors.append("The hyperlink for unreleased does not point the latest version to HEAD")

    # Ensure the unreleased URL's version is the previous version (version text proceeding [Unreleased])
    previous_version_linked_in_unreleased = unreleased_url[1]
    previous_version = re.search(r"\[([^\]]+)\] -", changelog)
    if previous_version and previous_version[1] != previous_version_linked_in_unreleased:
        errors.append("The hyperlink for unreleased does not point to the previous version")

    # Gather all version headers. Note that the 'Unreleased' hyperlink is validated separately.
    version_headers = re.findall(VERSION_HEADER_START_RE, changelog)
    version_headers = [header for header in version_headers if header != "Unreleased"]

    # Ensure each version header has a hyperlink
    for version in version_headers:
        if re.search(VERSION_HYPERLINK_START_RE.replace(r"[\w.]+", version), changelog) is None:
            errors.append(f"Version '{version}' does not have a URL")

    # Gather all hyperlinks. Note that the 'Unreleased' hyperlink is validated separately
    hyperlinks = re.findall(VERSION_HYPERLINK_RE, changelog)
    hyperlinks = [hyperlink for hyperlink in hyperlinks if hyperlink[0] != "Unreleased"]

    # Ensure each hyperlink has a header
    for hyperlink in hyperlinks:
        if hyperlink[0] not in version_headers:
            errors.append(f"Hyperlink '{hyperlink[0]}' does not have a version title '## [{hyperlink[0]}]'")

    # Ensure there is only one initial version
    initial_version = re.findall(INITIAL_VERSION_RE, changelog)
    if len(initial_version) > 1:
        errors.append(
            "There is more than one link to a tagged version, "
            "which is usually reserved only for the initial version."
        )

    # Ensure the initial version's tag name matches the version name
    if initial_version:
        initial_version_tag = initial_version[0][0]
        if initial_version_tag != initial_version[0][1]:
            errors.append(
                f"The initial version tag name '{initial_version[0][1]}' does "
                f"not match the version header '{initial_version[0][0]}'"
            )

    # Ensure all versions headers have dates
    full_version_headers = re.findall(VERSION_HEADER_FULL_RE, changelog)
    if len(full_version_headers) != len(version_headers):
        for version in version_headers:
            if re.search(VERSION_HEADER_FULL_RE.replace(r"([\w.]+)", rf"({version})"), changelog) is None:
                errors.append(f"Version header '## [{version}]' does not have a date in the correct format")

    # Ensure version links always diff to the previous version
    comparable_versions = [hyperlinks[0] for hyperlinks in hyperlinks]
    comparable_versions.append(initial_version[0][0])
    for position, version in enumerate(comparable_versions):
        if position == len(comparable_versions) - 1:
            break

        pattern = rf"\[{version}\]: {GITHUB_COMPARE_URL_START_RE}{comparable_versions[position + 1]}\.\.\.{version}"
        if re.search(pattern, changelog) is None:
            errors.append(
                f"URL for version '{version}' does not diff to the previous version '{comparable_versions[position + 1]}'"
            )

    # Check if the user is using something other than <Added||Changed||Deprecated||Removed||Fixed||Security>
    section_headers = re.findall(SECTION_HEADER_RE, changelog)
    for header in section_headers:
        if header not in {"Added", "Changed", "Deprecated", "Removed", "Fixed", "Security"}:
            errors.append(f"Using non-standard section header '{header}'")

    if errors:
        raise ValueError("\n".join(errors))


if __name__ == "__main__":
    if len(sys.argv) == 2:
        validate_changelog(sys.argv[1])
    if len(sys.argv) > 2:
        print("Usage: python validate_changelog.py [changelog_path]")
        sys.exit(1)
    validate_changelog()
    print("Changelog is valid! ✅")
    sys.exit(0)
