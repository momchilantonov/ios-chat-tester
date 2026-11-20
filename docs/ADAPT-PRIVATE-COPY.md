# Prompt: make a private copy of this tool

**For the human.** You created an empty private repo and cloned it next to this public clone (same parent
folder). Nothing is committed in it yet; earlier copies or edits in it don't matter. Start Copilot in the
parent folder and say:

```text
Follow ios-chat-tester/docs/ADAPT-PRIVATE-COPY.md for the folder <new folder>
```

The result: the tool's files, a README for users of your private repo (how to install and use the agents; no
development history), without `CHANGELOG.md` and `GUIDE_FOR_AGENTS.md`. Nothing is committed.

---

**For the agent.** Run the commands below **in order**, from the parent folder that holds both `ios-chat-tester`
and the new folder. Replace `<new folder>` with the folder the human named. Don't change anything else, don't
improvise steps, **don't commit or push**. If a check fails, stop and report it to the human.

## 1. Values and checks
```bash
T="<new folder>"
NEW_URL=$(git -C "$T" remote get-url origin)
NEW_NAME=$(basename "$NEW_URL" .git)
echo "T=$T  NEW_URL=$NEW_URL  NEW_NAME=$NEW_NAME"
git -C "$T" rev-list --all --count                        # must print 0 (no commits yet)
ls "$T/tester/config.json" "$T/tester/profile.md" 2>/dev/null   # must print nothing
ls ios-chat-tester/docs/private-copy/README.template.md    # must exist
```
- `NEW_NAME` must equal the folder name `$T`. If not, stop and ask the human.
- If `config.json` or `profile.md` exist in `$T/tester/`, stop: they are the human's settings.

## 2. Start from the original files
Removes everything in `$T` except `.git`, then copies the files of the public clone's current version.
```bash
find "$T" -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
git -C ios-chat-tester archive HEAD | tar -x -C "$T"
rm -rf "$T/docs"
```

## 3. The README for the private repo
```bash
sed "s|{{REPO_URL}}|$NEW_URL|g; s|{{REPO_NAME}}|$NEW_NAME|g" \
    ios-chat-tester/docs/private-copy/README.template.md > "$T/README.md"
```

## 4. Remove what belongs to the public project's development
```bash
rm "$T/GUIDE_FOR_AGENTS.md" "$T/CHANGELOG.md"
grep -v -e '^REPORT-FOR-MAINTAINER.md$' -e '^TEST_AGENT_REQUIREMENTS.md$' "$T/.gitignore" > "$T/.gitignore.new" && mv "$T/.gitignore.new" "$T/.gitignore"
perl -pi -e 's/here - it stays in your repository, it is not part of the public chat-tester project\./here - it stays on this machine (git-ignored) and is never committed to this repository./' "$T/tester/profile.example.md"
```

## 5. Verify
```bash
grep -rn -i "momchil\|ios-chat-tester\|GUIDE_FOR_AGENTS\|CHANGELOG\|REPORT-FOR-MAINTAINER\|TEST_AGENT_REQUIREMENTS\|{{REPO_URL}}\|{{REPO_NAME}}" "$T" --exclude-dir=.git   # must print nothing
grep -n -i "public" "$T/README.md" "$T/tester/profile.example.md"                                                      # must print nothing
grep -c "$NEW_URL" "$T/README.md"                                         # must print 5
find "$T" -path "$T/.git" -prune -o -type f -print | wc -l                # must print 43
git -C "$T" rev-list --all --count                                        # must print 0
```
`grep` ends with exit code 1 when it finds nothing - that is the expected result here.

## 6. Report and stop
Tell the human, in a short table: each check, what it printed, OK or not. Then the next step for the human:
review `README.md`, then commit and push:
```bash
cd "<new folder>" && git add -A && git commit -m "Import iOS chat tester" && git push -u origin main
```
Don't run that yourself.
