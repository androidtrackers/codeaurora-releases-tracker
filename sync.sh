#Fetching latest list
curl -s https://wiki.codeaurora.org/xwiki/bin/QAEP/release | grep '<table>' > releases

#Convert to MD
pandoc +RTS -K1073741824 -RTS releases -f html -t markdown_github+pipe_tables -o releases.md
sed -i 's/  */ /g' ./releases.md
mv releases.md README.md

#Compare
git diff | grep -P '^\+(?:(?!\+\+))|^-(?:(?!--))' | cut -d + -f2 > changes

#Push
git add README.md; git -c "user.name=$gituser" -c "user.email=$gitmail" commit -m "Sync: $(date +%d.%m.%Y)"
git push -q https://$GIT_OAUTH_TOKEN_XFU@github.com/yshalsager/codeaurora-releases-tracker.git HEAD:master

#Telegram
cat changes | while read line; do
	date=$(echo $line | cut -d '|' -f2)
	tag=$(echo $line | cut -d '|' -f3)
	chipset=$(echo $line | cut -d '|' -f4)
	manifest=$(echo $line | cut -d '|' -f5)
	android=$(echo $line | cut -d '|' -f6)
	python telegram.py -t $bottoken -c @CAFReleases -M "New CAF release detected!
	Chipset:*$chipset*
	Android:*$android* 
	Tag:*$tag*
	Manifest:*$manifest*
	Date:*$date* "
done
