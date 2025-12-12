import json
import re
from datetime import datetime, timedelta
from os import environ
from subprocess import run
from pathlib import Path
from time import sleep

from httpx import Client, codes

TELEGRAM_CHATS = ["@CAFReleases", "@CLOReleases"]
BOT_TOKEN = environ["bottoken"]
GIT_OAUTH_TOKEN = environ["XFU"]

BRANCHES = {
    "la": {
        "platform": 13321,
        "system": 13127,
        "vendor": 13079,
    },
    "le": {
        "manifest": 22314,
    },
}

chipsets_base_exclude = [
    "wlan",
    "sepolicy",
    "sepolicy_vndr",
    "common",
    "vendor-common",
    "kernelscripts",
]
chipsets_exclude = {
    r"LA\.UM\.\d+\.1.*": [*chipsets_base_exclude, "sdm845", "msm8996"],
    r"LA\.UM\.\d+\.2.*": [
        *chipsets_base_exclude,
        "sdm845",
        "atoll",
        "msm8909",
        "msm8909go",
        "msm8937_32go",
        "msm8996",
        "msmnile",
        "sm6150",
    ],
    r"LA\.UM\.\d+\.6.*": [
        *chipsets_base_exclude,
        "msmnile",
        "atoll",
        "msm8909",
        "msm8909go",
        "msm8996",
        "sdm845",
        "sm6150",
        "trinket",
    ],
    r"LA\.UM\.\d+\.8.*": [
        *chipsets_base_exclude,
        "atoll",
        "msm8909",
        "msm8909go",
        "msmnile",
        "sdm845",
        "sm6150",
        "msm8996",
    ],
    r"LA\.UM\.\d+\.11.*": [
        *chipsets_base_exclude,
        "atoll",
        "msm8909",
        "msm8909go",
        "msmnile",
        "sdm845",
        "sm6150",
        "msm8996",
    ],
    r"LA\.UM\.\d+\.12.*": [
        *chipsets_base_exclude,
        "msm8909",
        "msm8909go",
        "msm8996",
        "msmnile",
        "sdm845",
    ],
    r"LA\.UM\.\d+\.14.*": [
        *chipsets_base_exclude,
        "holi",
        "kona",
    ],
    r"LA\.UM\.\d+\.15.*": [
        *chipsets_base_exclude,
        "kona",
        "lito",
        "msm8909",
        "msm8909go",
        "msm8996",
        "msmnile",
        "sdm845",
    ],
    r"LA\.UM\.\d+\.16.*": [
        *chipsets_base_exclude,
        "kona",
        "lahaina",
    ],
    r"LA\.VENDOR\.1\.0.*": [
        *chipsets_base_exclude,
        "lahaina",
    ],
    r"LA\.VENDOR\.12\.2.*": [
        *chipsets_base_exclude,
        "lahaina",
        "taro",
    ],
    r"LA\.VENDOR\.12\.3.*": [
        *chipsets_base_exclude,
        "lahaina",
        "taro",
    ],
    r"LA\.VENDOR\.13\.2\.1.*": [
        *chipsets_base_exclude,
        "crow",
        "kalama",
        "lahaina",
        "taro",
    ],
    r"LA\.VENDOR\.13\.2\.2.*": [
        *chipsets_base_exclude,
        "crow",
        "kalama",
        "lahaina",
        "taro",
    ],
    r"LA\.VENDOR\.13\.2\.5.*": [
        *chipsets_base_exclude,
        "crow",
        "kalama",
        "lahaina",
        "taro",
    ],
    r"LA\.VENDOR\.13\.2\.6.*": [
        *chipsets_base_exclude,
        "crow",
        "lahaina",
        "taro",
    ],
    r"LA\.VENDOR\.13\.2\.8.*": [
        *chipsets_base_exclude,
        "crow",
        "lahaina",
        "taro",
    ],
    r"LA\.VENDOR\.14\.3\.0.*": [
        *chipsets_base_exclude,
        "blair",
        "kalama",
        "lahaina",
        "pitti",
        "pitti_32go"
        "taro",
    ],
    r"LA\.VENDOR\.14\.3\.1.*": [
        *chipsets_base_exclude,
        "kalama",
        "lahaina",
        "pineapple",
        "taro",
    ],
    r"LA\.VENDOR\.14\.3\.2.*": [
        *chipsets_base_exclude,
        "blair",
        "kalama",
        "lahaina",
        "pineapple",
        "taro",
    ],
    r"LA\.VENDOR\.14\.3\.4.*": [
        *chipsets_base_exclude,
        "lahaina",
        "taro",
    ],
}

client = Client(timeout=30)


class Scraper:
    def __init__(self, project: str, parts: dict[str, int]) -> None:
        self._base_url = "https://git.codelinaro.org/api/v4/projects/{}/repository/tags?page={}&per_page=100"
        self.project = project
        self.parts = parts
        self.data = {}

    def _get_data(self, project_id: int, page: int) -> tuple[dict, bool]:
        response = client.get(self._base_url.format(project_id, page))
        return response.json(), response.headers.get("X-Next-Page", False)

    def _add_to_data(self, data: dict, project: str):
        for tag in data:
            self.data[tag["name"]] = {
                "tag": tag["name"],
                "project": project,
                "date": tag["commit"]["committed_date"],
            }

    def fetch(self):
        for part, project_id in self.parts.items():
            page = 1
            response, next_page = self._get_data(project_id, page)
            self._add_to_data(response, f"{self.project}_{part}")
            while next_page:
                page += 1
                response, next_page = self._get_data(project_id, page)
                self._add_to_data(response, f"{self.project}_{part}")

    def to_markdown(self):
        header = ["date", "tag"]
        markdown = f"{'|'.join(header)}\n"
        markdown += f"|{''.join('---|' for _ in range(len(header)))}\n"
        for _, release in self.data.items():
            markdown += f"{'|'.join(f'{release.get(key)}' for key in header)}\n"
        return markdown


def diff(old, new):
    return [new.get(item) for item in new.keys() if item not in old.keys()]


def get_android_versions(commit_sha: str):
    security_patch, android_version = "", ""
    version_defaults = client.get(
        f"https://git.codelinaro.org/clo/la/platform/build_repo/-/raw/{commit_sha}/core/version_defaults.mk"
    ).text
    if security_patch_match := re.search(
        r"PLATFORM_SECURITY_PATCH := ([\w-]+)",
        version_defaults,
    ):
        security_patch = security_patch_match.group(1)
    if android_version_match := re.search(
        r"PLATFORM_VERSION_LAST_STABLE :=\s+([\w.]+)", version_defaults
    ):
        android_version = android_version_match.group(1)
    return security_patch, android_version


def get_build_id(commit_sha):
    if build_id := re.search(
        r"BUILD_ID=(.*)",
        client.get(
            f"https://git.codelinaro.org/clo/la/platform/build_repo/-/raw/{commit_sha}/core/build_id.mk"
        ).text,
    ):
        return build_id.group(1)


def get_manifests(tag):
    manifests_pattern = re.compile(
        r"name=\"(?P<name>[\w.]+)\"\s+project=\"(?P<project>[\w./]+)\".*"
        r"tag=\"(?P<tag>[\w.]+)\"\s+targets=\"(?P<targets>[\w.]+)\""
    )
    manifests = [
        match.groupdict()
        for match in manifests_pattern.finditer(
            client.get(
                f"https://git.codelinaro.org/clo/la/la/vendor/manifest/-/raw/{tag}/{tag}.xml"
            ).text
        )
    ]
    if manifests:
        return manifests


def get_kernel_version(manifest):
    kernel_repo_regex = re.search(
        r"name=\"(.*kernel/msm-[0-9.]+)\".*revision=\"(\w{40})\".*upstream=\"(?:refs/heads/)?([\w/.-]+)\"",
        manifest,
    )
    if not kernel_repo_regex:
        return
    kernel_repo = kernel_repo_regex.group(1)
    if kernel_repo.startswith("clo/la/"):
        kernel_repo = kernel_repo.replace("clo/la/", "")
    kernel_version = re.search(
        r"VERSION = (\d+)\nPATCHLEVEL = (\d+)\nSUBLEVEL = (\d+)",
        client.get(
            f"https://git.codelinaro.org/clo/la/{kernel_repo}/-/raw/{kernel_repo_regex.group(2)}/Makefile"
        ).text,
    )
    if kernel_version:
        return (
            f"{kernel_version.group(1)}.{kernel_version.group(2)}.{kernel_version.group(3)} "
            f"({kernel_repo_regex.group(3)})"
        )


def get_info_from_system_manifest(manifest):
    if version_defaults_revision := re.search(
        r"name=\"platform/build_repo\"\s+path=\"[\w/]+\"\s+revision=\"(\w{40})\"",
        manifest,
    ):
        commit_sha = version_defaults_revision.group(1)
        security_patch, android_version = get_android_versions(commit_sha)
        build_id = get_build_id(commit_sha)
        return security_patch, android_version, build_id


def get_chipsets(tag: str, manifest: str) -> str:
    properties = ["path", "name"]
    chipsets = set()
    for _property in properties:
        pattern = re.compile(r"<project.*?{}=\"device/qcom/(.*?)\"".format(_property))
        matches = pattern.finditer(manifest)
        chipsets.update(
            match.group(1)
            for match in matches
            if not any(
                re.match(tag_pattern, tag) and match.group(1) in items
                for tag_pattern, items in chipsets_exclude.items()
            )
        )
        if chipsets:
            break
    return ", ".join(sorted(chipsets))


def generate_telegram_message(update):
    tag = update.get("tag", "")
    message = f"New CodeLinaro OSS release detected!\n" f"*Tag:* `{tag}` \n"
    if tag.startswith("LE.BR.") or tag.startswith("LNX.LE."):
        manifest_url = (
            f"https://git.codelinaro.org/clo/le/le/manifest/-/blob/{tag}/{tag}.xml"
        )
        message += f"Manifest: [Here]({manifest_url}) \n"
        message += f"Date: {update.get('date')}"
        return message
    project = update.get("project", "").split("_")[1]
    try:
        system_info = None
        kernel_version = None
        manifest = ""
        if project == "platform":
            manifest_url = f"https://git.codelinaro.org/clo/la/platform/manifest/-/raw/{tag}/{tag}.xml"
            if client.head(manifest_url).status_code == codes.OK:
                message += f"Manifest: [Platform]({manifest_url})\n"
                manifest = client.get(manifest_url).text
                system_info = get_info_from_system_manifest(manifest)
                kernel_version = get_kernel_version(manifest)
        if project == "system":
            manifest_url = (
                f"https://git.codelinaro.org/clo/la/la/"
                f"system/manifest/-/raw/{tag}/{tag}.xml"
            )
            if client.head(manifest_url).status_code == codes.OK:
                message += f"Manifest: [System]({manifest_url})\n"
                manifest = client.get(manifest_url).text
                system_info = get_info_from_system_manifest(manifest)
        if project == "vendor":
            manifest_url = f"https://git.codelinaro.org/clo/la/la/vendor/manifest/-/raw/release/{tag}.xml"
            manifest = client.get(manifest_url).text
            message += f"Manifests: [Vendor]({manifest_url}) - "
            if manifests := get_manifests(tag):
                for manifest_data in manifests:
                    sub_manifest_url = (
                        f"https://git.codelinaro.org/clo/la/{manifest_data.get('project')}/-/"
                        f"raw/{manifest_data.get('tag')}/"
                        f"{manifest_data.get('tag')}.xml"
                    )
                    if client.head(sub_manifest_url).status_code == codes.OK:
                        message += (
                            f"[{manifest_data.get('targets')} ({manifest_data.get('name')})]"
                            f"(https://git.codelinaro.org/clo/la/{manifest_data.get('project')}"
                            f"/-/blob/{manifest_data.get('tag')}/"
                            f"{manifest_data.get('tag')}.xml) - "
                        )
                    if manifest_data.get("project") == "la/system/manifest":
                        system_info = get_info_from_system_manifest(
                            client.get(sub_manifest_url).text
                        )
                    if manifest_data.get("project") == "kernelplatform/manifest":
                        kernel_version = get_kernel_version(
                            client.get(sub_manifest_url).text
                        )
            message = message.rstrip(" - ")
            message += "\n"

        if manifest:
            if chipsets := get_chipsets(tag, manifest):
                message += f"Chipsets: `{chipsets}`\n"

        if system_info:
            security_patch, real_android_version, build_id = system_info
            if real_android_version:
                message += f"Android: *{real_android_version}* \n"
            if security_patch:
                message += f"Security Patch: *{security_patch}*\n"
            if build_id:
                message += f"Build ID: *{build_id}*\n"

        if kernel_version:
            message += f"Kernel Version: *{kernel_version}* \n"
    except AttributeError:
        pass

    message += f"Date: {update.get('date')}"
    return message.replace("/raw/", "/blob/")


def send_telegram_message(telegram_message, chat):
    params = (
        ("chat_id", chat),
        ("text", telegram_message),
        ("parse_mode", "Markdown"),
        ("disable_web_page_preview", "yes"),
    )
    telegram_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    response = client.post(telegram_url, params=params)
    if response.status_code != codes.OK:
        print(f"Response: {response.reason_phrase}")
    sleep(3)


def post_updates(changes):
    for update in changes:
        # safe to ignore
        if update.get("tag").startswith("AU_LINUX_"):
            continue
        # post only last 15 days updates
        update_date = datetime.strptime(update.get("date"), "%Y-%m-%dT%H:%M:%S.%f%z")
        if (datetime.now(update_date.tzinfo) - update_date) > timedelta(days=15):
            continue
        telegram_message = generate_telegram_message(update)
        print(telegram_message)
        for chat in TELEGRAM_CHATS:
            send_telegram_message(telegram_message, chat)


def git_command_push():
    run(
        f'git add *.md *.json && git -c "user.name=XiaomiFirmwareUpdater" -c '
        f'"user.email=xiaomifirmwareupdater@gmail.com" commit -m '
        f'"[skip ci] sync: {datetime.today().strftime("%d-%m-%Y %H:%M:%S")}" && '
        f"git push -q https://{GIT_OAUTH_TOKEN}@github.com/androidtrackers/"
        f"codeaurora-releases-tracker.git HEAD:master",
        shell=True,
        check=True,
        capture_output=True,
        encoding="utf-8",
    )


def main():
    for project, parts in BRANCHES.items():
        scraper = Scraper(project, parts)
        print(f"Working on {project}")
        file = Path(f"{project}_release.json")
        if file.exists():
            file.rename(f"{file}.bak")
        scraper.fetch()
        if not scraper.data:
            continue
        file.with_suffix(".json").write_text(json.dumps(scraper.data, indent=1))
        file.with_suffix(".md").write_text(scraper.to_markdown())
        changes = diff(json.loads(Path(f"{file}.bak").read_text()), scraper.data)
        if changes:
            post_updates(changes)
    git_command_push()


if __name__ == "__main__":
    main()
