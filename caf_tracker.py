import difflib
from datetime import date
from os import environ, rename, path, system

from bs4 import BeautifulSoup
from requests import get, post

today = str(date.today())
telegram_chat = "@CAFReleases"
bottoken = environ['bottoken']
GIT_OAUTH_TOKEN = environ['XFU']

url = 'https://wiki.codeaurora.org/xwiki/bin/QAEP/release'
response = get(url)
page = BeautifulSoup(response.content, 'html.parser')
data = page.find("table")

if path.exists('README.md'):
    rename('README.md', 'README_old.md')
with open('README.md', 'w') as o:
    for th in data.find_all('th'):
        o.write("|" + str(th.text).strip())
    o.write("|" + '\n')
    o.write("|---|---|---|---|" + '\n')
    for row in data.find_all('tr')[1:]:
        for cell in row.find_all('td'):
            o.write("|" + str(cell.text).strip())
        o.write("|" + '\n')

# diff
with open('README_old.md', 'r') as old, open('README.md', 'r') as new:
    o = old.readlines()
    n = new.readlines()
diff = difflib.unified_diff(o, n, fromfile='README_old.md', tofile='README.md')
changes = []
for line in diff:
    if line.startswith('+'):
        changes.append(str(line))
new = ''.join(changes[1:]).replace("+", "")
with open('README_changes.md', 'w') as o:
    o.write(new)

# post to tg
with open('README_changes.md', 'r') as c:
    for line in c:
        info = line.split("|")
        date = info[1]
        tag = info[2]
        chipset = info[3]
        manifest = info[4]
        android = info[5]
        manifest_url = "https://source.codeaurora.org/quic/la/platform/manifest/tree/" + manifest + "?h=" + tag
        telegram_message = "New CAF release detected!: \nChipset: *{0}* \nAndroid: *{1}* \n*Tag:* `{2}` \n" \
                           "Manifest: [Here]({3}) \nDate: {4}".format(chipset, android, tag, manifest_url, date)
        params = (
            ('chat_id', telegram_chat),
            ('text', telegram_message),
            ('parse_mode', "Markdown"),
            ('disable_web_page_preview', "yes")
        )
        telegram_url = "https://api.telegram.org/bot" + bottoken + "/sendMessage"
        telegram_req = post(telegram_url, params=params)
        telegram_status = telegram_req.status_code
        if telegram_status == 200:
            print("{0}: Telegram Message sent".format(tag))
        else:
            print("Telegram Error")

# commit and push
system("git add branches tags && git -c \"user.name=XiaomiFirmwareUpdater\" "
       "-c \"user.email=xiaomifirmwareupdater@gmail.com\" commit -m \"[skip ci] sync: {0}\" && "" \
   ""git push -q https://{1}@github.com/androidtrackers/codeaurora-releases-tracker.git HEAD:master"
       .format(today, GIT_OAUTH_TOKEN))
