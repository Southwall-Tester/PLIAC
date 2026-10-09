"""Allow only installed Playwright binaries to create a sandbox on Linux CI."""
import os
import re
import subprocess
from pathlib import Path


def main():
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_OS") != "Linux":
        raise SystemExit("This setup is only for the ephemeral Linux GitHub Actions runner.")
    cache = Path.home() / ".cache" / "ms-playwright"
    browsers = [*cache.glob("chromium-*/chrome-linux64/chrome"),
                *cache.glob("chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell")]
    if len(browsers) != 2:
        raise SystemExit("Expected the two freshly installed Playwright browsers.")
    policy = "abi <abi/4.0>,\ninclude <tunables/global>\n"
    for index, browser in enumerate(browsers):
        browser = browser.resolve(strict=True)
        if not (browser.is_file() and browser.is_relative_to(cache.resolve())
                and re.fullmatch(r"[A-Za-z0-9_./-]+", str(browser))):
            raise SystemExit("Unexpected browser path.")
        policy += (f'profile pliac-ci-browser-{index} "{browser}" '
                   'flags=(unconfined) {\n  userns,\n}\n')
    path = Path(os.environ["RUNNER_TEMP"]) / "pliac-ci-chromium"
    path.write_text(policy, encoding="utf-8")
    target = "/etc/apparmor.d/pliac-ci-chromium"
    subprocess.run(["sudo", "install", "-o", "root", "-g", "root", "-m", "644", str(path), target], check=True)
    subprocess.run(["sudo", "apparmor_parser", "-r", target], check=True)


if __name__ == "__main__":
    main()
