import json
import re
from datetime import datetime
from os import environ, system
from pathlib import Path
from time import sleep
from requests.exceptions import MissingSchema

from bs4 import BeautifulSoup
from requests import get, post, head

telegram_chat = "@CAFReleases"
bottoken = environ['bottoken']
GIT_OAUTH_TOKEN = environ['XFU']

URLS = ['https://wiki.codeaurora.org/xwiki/bin/QAEP/release',
        'https://wiki.codeaurora.org/xwiki/bin/QLBEP/release']


class Scraper:
    def __init__(self, url):
        self.url = url
        self.table = BeautifulSoup(
            get(self.url).content, 'html.parser').find("table")
        self.name = '_'.join(self.url.split('/')[5:])
        self.head = [th.text.strip() for th in self.table.find_all('th')]
        self.data = {}
        self.to_json()

    def to_json(self):
        for row in self.table.find_all('tr')[1:]:
            cells = row.find_all('td')
            self.data.update({
                cells[1].text.strip(): {
                    title: cell.text.strip() for title, cell in zip(self.head, cells)
                }
            })
        return self.data

    def to_markdown(self):
        markdown = '|'.join(i for i in self.head) + '|\n'
        markdown += '|' + ''.join('---|' for _ in range(len(self.head))) + '\n'
        for item in self.data.keys():
            markdown += '|'.join(i for i in self.data[item].values()) + '|\n'
        return markdown


def diff(old, new):
    return [new.get(item) for item in new.keys() if item not in old.keys()]


def get_security_patch(tag):
    try:
        return re.search(r'(?:PLATFORM_SECURITY_PATCH := )(\d{4}-\d{2}-\d{2})',
                         BeautifulSoup(get(f"https://source.codeaurora.org/quic/la/platform/build/"
                                           f"tree/core/version_defaults.mk?h={tag}").content,
                                       "html.parser").get_text()).group(1)
    except AttributeError:
        return


def get_build_id(tag):
    try:
        return re.search(r'(?:BUILD_ID=)(.*)',
                         BeautifulSoup(get(f"https://source.codeaurora.org/quic/la/platform/build/"
                                           f"tree/core/build_id.mk?h={tag}").content,
                                       "html.parser").get_text()).group(1)
    except AttributeError:
        pass


def get_system_manifest(tag):
    try:
        vendor_hint = re.search(r'(AU_LINUX[^;\n]+)(\d{2})',
                                BeautifulSoup(get(f"https://source.codeaurora.org/quic/la/la/vendor/manifest/tree/"
                                                  f"{tag}.xml").content,
                                              "html.parser").get_text()).group(0)
        length = len(vendor_hint)
        flag = 0
        if tag.endswith('KAMORTA.0'):
            if(vendor_hint[+49:-31]):
                if(vendor_hint[+49:-31] != '.00'):
                    flag = 1
                    vendor_hint = vendor_hint[+46:-34]
            else:
                vendor_hint = vendor_hint[+46:-31]
        elif (length < 50):
            vendor_hint = vendor_hint[-3:]
        elif(vendor_hint[-3:] != '.00'):
            flag = 1
            vendor_hint = vendor_hint[-6:-3]
        else:
            vendor_hint = vendor_hint[-6:-3]

        regex = '[^;\n]+'
        system = re.findall(regex + vendor_hint + regex,
                            BeautifulSoup(get(f"https://source.codeaurora.org/quic/la/la/system/manifest/tree/").content,
                                          "html.parser").get_text())
        if flag:
            return system[1][+10:-23]
        else:
            return system[0][+10:-23]

    except (IndexError, AttributeError):
        return


def get_kernel_version(manifest_url, tag):
    try:
        kernel_repo = re.search(r'name=\"(kernel/msm-[0-9.]+)\".*upstream=\"(?:refs/heads/)?(.*)\"/?>',
                                BeautifulSoup(get(manifest_url).content,
                                              "html.parser").get_text())
        regex = re.search(r'(?:VERSION = )(\d+)(?:\nPATCHLEVEL = )(\d+)(?:\nSUBLEVEL = )(\d+)',
                          BeautifulSoup(get(f"https://source.codeaurora.org/quic/la/{kernel_repo.group(1)}/"
                                            f"tree/Makefile?h={tag}").content,
                                        "html.parser").get_text())
        return f"{regex.group(1)}.{regex.group(2)}.{regex.group(3)} ({kernel_repo.group(2)})"
    except (IndexError, AttributeError, MissingSchema):
        pass


def generate_telegram_message(update):
    manifest_url = ""
    tag = update.get('Tag / Build ID')
    message = f"New CAF release detected!\n" \
              f"Chipset: *{update.get('Chipset')}* \n" \
              f"*Tag:* `{tag}` \n"
    manifest = f"https://source.codeaurora.org/quic/la/platform/manifest/tree/{update.get('Manifest')}?h={tag}"
    android_version = update.get('Android Version')
    if android_version:
        security_patch = get_security_patch(tag)
        build_id = get_build_id(tag)
        try:
            if head(manifest).ok:
                manifest_url = manifest
                message += f"Manifest: [Platform]({manifest})"
            elif android_version.startswith('11'):
                if update.get('Chipset').startswith('qssi'):
                    system_manifest = f"https://source.codeaurora.org/quic/la/la/system/manifest/tree/{update.get('Manifest')}"
                    if head(system_manifest).ok:
                        manifest_url = system_manifest
                        message += f"Manifest: [System]({system_manifest})"
                else:
                    system_tag = get_system_manifest(tag)
                    system_manifest = f"https://source.codeaurora.org/quic/la/la/system/manifest/tree/{system_tag}.xml"
                    vendor_manifest = f"https://source.codeaurora.org/quic/la/la/vendor/manifest/tree/{update.get('Manifest')}"
                    if head(vendor_manifest).ok:
                        message += f"Manifest: [Vendor]({vendor_manifest})"
                    if head(system_manifest).ok:
                        message += f" | [System]({system_manifest})"
                        security_patch = get_security_patch(system_tag)
                        build_id = get_build_id(system_tag)
                        manifest_url = vendor_manifest

            message += f"\nAndroid: *{update.get('Android Version')}* \n"
            if security_patch:
                message += f"Security Patch: *{security_patch}*\n"
            if build_id:
                message += f"Build ID: *{build_id}*\n"
        except AttributeError:
            pass
    elif tag.startswith('LE.BR.') or tag.startswith('LNX.LE.'):
        manifest_url = f"https://source.codeaurora.org/quic/le/manifest/tree/{update.get('Manifest')}?h={tag}"
        message += f"Manifest: [Here]({manifest_url}) \n"
    else:
        manifest_url = f"https://source.codeaurora.org/quic/le/le/manifest/tree/{update.get('Manifest')}?h={tag}"
        if head(manifest_url).ok:
            message += f"Manifest: [Here]({manifest_url}) \n"

    kernel_version = get_kernel_version(manifest_url, tag)
    if kernel_version:
        message += f"Kernel Version: *{get_kernel_version(manifest_url, tag)}* \n"
    message += f"Date: {update.get('Date')}"
    return message


def send_telegram_message(telegram_message, chat):
    params = (
        ('chat_id', chat),
        ('text', telegram_message),
        ('parse_mode', "Markdown"),
        ('disable_web_page_preview', "yes")
    )
    telegram_url = "https://api.telegram.org/bot" + bottoken + "/sendMessage"
    response = post(telegram_url, params=params)
    if not response.status_code == 200:
        print(f"Response: {response.reason}")
    sleep(3)


def post_updates(changes, chat):
    for update in changes:
        telegram_message = generate_telegram_message(update)
        print(telegram_message)
        send_telegram_message(telegram_message, chat)


def write_markdown(file, content):
    with open(file, 'w') as out:
        out.write(content)


def write_json(file, content):
    with open(file, 'w') as out:
        json.dump(content, out, indent=1)


def read_json(file):
    with open(file, 'r') as json_file:
        return json.load(json_file)


def git_command_push():
    # commit and push
    system(
        f'git add *.md *.json && git -c "user.name=XiaomiFirmwareUpdater" -c '
        f'"user.email=xiaomifirmwareupdater@gmail.com" commit -m '
        f'"[skip ci] sync: {datetime.today().strftime("%d-%m-%Y %H:%M:%S")}" && '
        f'git push -q https://{GIT_OAUTH_TOKEN}@github.com/androidtrackers/'
        f'codeaurora-releases-tracker.git HEAD:master')


def main():
    for url in URLS:
        scraper = Scraper(url)
        print(f"Working on {scraper.name}")
        file = Path(f"{scraper.name}.json")
        if file.exists():
            file.rename(f'{file}.bak')
        write_json(file, scraper.data)
        write_markdown(f'{file.stem}.md', scraper.to_markdown())
        changes = diff(read_json(f'{file}.bak'), scraper.data)
        if changes:
            post_updates(changes, telegram_chat)
    git_command_push()


if __name__ == '__main__':
    main()
