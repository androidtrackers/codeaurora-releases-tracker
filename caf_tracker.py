import json
import re
from datetime import datetime
from os import environ, system
from pathlib import Path
from time import sleep

from bs4 import BeautifulSoup
from requests import get, head, post

TELEGRAM_CHATS = ["@CAFReleases", "@CLOReleases"]
BOT_TOKEN = environ["bottoken"]
GIT_OAUTH_TOKEN = environ["XFU"]

BRANCHES = ["la", "le"]


class Scraper:
    def __init__(self, url):
        self.url = url
        self.table = BeautifulSoup(get(self.url).content, "html.parser").select_one("table")
        self.name = f'{self.url.split("/")[-2].split("-")[-1]}_release'
        self.head = [th.string.strip() for th in self.table.select("th")]
        self.data = {}
        self.to_json()

    def to_json(self):
        for row in self.table.select("tr")[1:]:
            cells = row.select("td")
            self.data.update(
                {
                    cells[1].string.strip(): {
                        title: cell.string.strip() if cell.string else ""
                        for title, cell in zip(self.head, cells)
                    }
                }
            )
        return self.data

    def to_markdown(self):
        markdown = f"{'|'.join(i for i in self.head)}|\n"
        markdown += f"|{''.join('---|' for _ in range(len(self.head)))}\n"
        for _, data in self.data.items():
            markdown += f"{'|'.join(i for __, i in data.items())}|\n"
        return markdown


def diff(old, new):
    return [new.get(item) for item in new.keys() if item not in old.keys()]


def get_android_versions(commit_sha: str):
    security_patch, android_version = "", ""
    version_defaults = get(
        f"https://git.codelinaro.org/clo/la/platform/build_repo/-/raw/{commit_sha}/core/version_defaults.mk"
    ).text
    security_patch_match = re.search(
        r"PLATFORM_SECURITY_PATCH := ([\w-]+)",
        version_defaults,
    )
    if security_patch_match:
        security_patch = security_patch_match.group(1)
    android_version_match = re.search(
        r"PLATFORM_VERSION_LAST_STABLE :=\s+([\w.]+)", version_defaults
    )
    if android_version_match:
        android_version = android_version_match.group(1)
    return security_patch, android_version


def get_build_id(commit_sha):
    build_id = re.search(
        r"BUILD_ID=(.*)",
        get(
            f"https://git.codelinaro.org/clo/la/platform/build_repo/-/raw/{commit_sha}/core/build_id.mk"
        ).text,
    )
    if build_id:
        return build_id.group(1)


def get_manifests(tag):
    manifests_pattern = re.compile(
        r"name=\"(?P<name>[\w.]+)\"\s+project=\"(?P<project>[\w./]+)\".*"
        r"tag=\"(?P<tag>[\w.]+)\"\s+targets=\"(?P<targets>[\w.]+)\""
    )
    manifests = [
        match.groupdict()
        for match in manifests_pattern.finditer(
            get(
                f"https://git.codelinaro.org/clo/la/la/vendor/manifest/-/raw/{tag}/{tag}.xml"
            ).text
        )
    ]
    if manifests:
        return manifests


def get_kernel_version(manifest):
    kernel_repo_regex = re.search(
        r"name=\"(.*kernel/msm-[0-9.]+)\".*revision=\"([\d\w]{40})\".*upstream=\"(?:refs/heads/)?([\w/.-]+)\"",
        manifest,
    )
    if not kernel_repo_regex:
        return
    kernel_repo = kernel_repo_regex.group(1)
    if kernel_repo.startswith("clo/la/"):
        kernel_repo = kernel_repo.replace("clo/la/", "")
    kernel_version = re.search(
        r"VERSION = (\d+)\nPATCHLEVEL = (\d+)\nSUBLEVEL = (\d+)",
        get(
            f"https://git.codelinaro.org/clo/la/{kernel_repo}/-/raw/{kernel_repo_regex.group(2)}/Makefile"
        ).text,
    )
    if kernel_version:
        return f"{kernel_version.group(1)}.{kernel_version.group(2)}.{kernel_version.group(3)} ({kernel_repo_regex.group(3)})"


def get_info_from_system_manifest(manifest):
    version_defaults_revision = re.search(
        r"name=\"platform/build_repo\"\s+path=\"[\w\d/]+\"\s+revision=\"([\d\w]{40})\"",
        manifest,
    )
    if version_defaults_revision:
        commit_sha = version_defaults_revision.group(1)
        security_patch, android_version = get_android_versions(commit_sha)
        build_id = get_build_id(commit_sha)
        return security_patch, android_version, build_id


def generate_telegram_message(update):
    tag = update.get("Tag / Build ID")
    chipset = update.get("Chipset")
    message = (
        f"New CodeLinaro OSS release detected!\n"
        f"Chipset: *{chipset}* \n"
        f"*Tag:* `{tag}` \n"
    )
    if chipset in ["camera", "display", "video"]:
        tech_pack = (
            f"Techpack: [{chipset}]"
            f"(https://git.codelinaro.org/clo/la/techpack/{chipset}/"
            f"manifest/-/blob/{tag}/{tag}.xml)"
        )
        message = re.sub("Chipset:.*", tech_pack, message)
        message += f"Date: {update.get('Date')}"
        return message
    if tag.startswith("LE.BR.") or tag.startswith("LNX.LE."):
        manifest_url = (
            f"https://git.codelinaro.org/clo/le/le/manifest/-/blob/{tag}/{tag}.xml"
        )
        message += f"Manifest: [Here]({manifest_url}) \n"
        message += f"Date: {update.get('Date')}"
        return message
    manifest_url = f"https://git.codelinaro.org/clo/la/platform/manifest/-/raw/{tag}/{update.get('Manifest')}"
    manifest = get(manifest_url).text
    android_version = update.get("Android Version")
    kernel_version = None
    system_info = None
    if android_version:
        android_version_number = android_version
        if android_version[0].isdigit():
            android_version_number = int(android_version.split(".")[0])
        if not manifest.startswith("<!DOCTYPE html>"):
            system_info = get_info_from_system_manifest(manifest)
        try:
            if head(manifest_url).ok:
                message += (
                    f"Manifest: [Platform]({manifest_url.replace('/raw/', '/blob/')})\n"
                )
            elif android_version_number >= 11:
                if chipset.startswith("qssi"):
                    system_manifest = (
                        f"https://git.codelinaro.org/clo/la/la/"
                        f"system/manifest/-/raw/{tag}/{update.get('Manifest')}"
                    )
                    if head(system_manifest).ok:
                        message += f"Manifest: [System]({system_manifest})\n"
                        system_info = get_info_from_system_manifest(get(system_manifest).text)
                else:
                    message += (
                        f"Manifests: [Vendor](https://git.codelinaro.org/clo/la/la/"
                        f"vendor/manifest/-/blob/{tag}/{tag}.xml) - "
                    )
                    manifests = get_manifests(tag)
                    if manifests:
                        for manifest_data in manifests:
                            sub_manifest_url = (
                                f"https://git.codelinaro.org/clo/la/{manifest_data.get('project')}/-/"
                                f"raw/{manifest_data.get('tag')}/"
                                f"{manifest_data.get('tag')}.xml"
                            )
                            if head(sub_manifest_url).ok:
                                message += (
                                    f"[{manifest_data.get('targets')} ({manifest_data.get('name')})]"
                                    f"(https://git.codelinaro.org/clo/la/{manifest_data.get('project')}"
                                    f"/-/blob/{manifest_data.get('tag')}/"
                                    f"{manifest_data.get('tag')}.xml) - "
                                )
                            if manifest_data.get("project") == "la/system/manifest":
                                system_info = get_info_from_system_manifest(
                                    get(sub_manifest_url).text
                                )
                            if (
                                manifest_data.get("project")
                                == "kernelplatform/manifest"
                            ):
                                kernel_version = get_kernel_version(
                                    get(sub_manifest_url).text
                                )
                    message = message.rstrip(" - ")
                    message += "\n"

            if system_info:
                security_patch, real_android_version, build_id = system_info
                if real_android_version:
                    message += f"Android: *{real_android_version}* \n"
                if security_patch:
                    message += f"Security Patch: *{security_patch}*\n"
                if build_id:
                    message += f"Build ID: *{build_id}*\n"
            else:
                message += f"Android: *{update.get('Android Version')}* \n"

        except AttributeError:
            pass
    else:
        manifest_url = (
            f"https://git.codelinaro.org/clo/le/le/manifest/-/blob/{tag}/{tag}.xml"
        )
        if head(manifest_url).ok:
            message += f"Manifest: [Here]({manifest_url}) \n"

    if not kernel_version:
        kernel_version = get_kernel_version(manifest)
    if kernel_version:
        message += f"Kernel Version: *{kernel_version}* \n"
    message += f"Date: {update.get('Date')}"
    return message


def send_telegram_message(telegram_message, chat):
    params = (
        ("chat_id", chat),
        ("text", telegram_message),
        ("parse_mode", "Markdown"),
        ("disable_web_page_preview", "yes"),
    )
    telegram_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    response = post(telegram_url, params=params)
    if not response.status_code == 200:
        print(f"Response: {response.reason}")
    sleep(3)


def post_updates(changes):
    for update in changes:
        telegram_message = generate_telegram_message(update)
        print(telegram_message)
        for chat in TELEGRAM_CHATS:
            send_telegram_message(telegram_message, chat)


def write_markdown(file, content):
    with open(file, "w") as out:
        out.write(content)


def write_json(file, content):
    with open(file, "w") as out:
        json.dump(content, out, indent=1)


def read_json(file):
    with open(file, "r") as json_file:
        return json.load(json_file)


def git_command_push():
    # commit and push
    system(
        f'git add *.md *.json && git -c "user.name=XiaomiFirmwareUpdater" -c '
        f'"user.email=xiaomifirmwareupdater@gmail.com" commit -m '
        f'"[skip ci] sync: {datetime.today().strftime("%d-%m-%Y %H:%M:%S")}" && '
        f"git push -q https://{GIT_OAUTH_TOKEN}@github.com/androidtrackers/"
        f"codeaurora-releases-tracker.git HEAD:master"
    )


def main():
    for branch in BRANCHES:
        scraper = Scraper(f"https://wiki.codelinaro.org/en/wiki-{branch}/release")
        print(f"Working on {scraper.name}")
        file = Path(f"{scraper.name}.json")
        if file.exists():
            file.rename(f"{file}.bak")
        if not scraper.data:
            continue
        write_json(file, scraper.data)
        write_markdown(f"{file.stem}.md", scraper.to_markdown())
        changes = diff(read_json(f"{file}.bak"), scraper.data)
        if changes:
            post_updates(changes)
    git_command_push()


if __name__ == "__main__":
    main()
