# Prompt: adapt a private copy of this tool

**For the human.** You made a private repo from this tool's files (one commit, no history), and its folder
holds the copied files, not committed yet. Start Copilot in the folder that contains both the public clone and
the new folder, and say:

```text
Follow ios-chat-tester/docs/ADAPT-PRIVATE-COPY.md for the folder <new folder>
```

---

**For the agent.** Adapt the documentation of the folder the human named (TARGET) so it describes that private
repository instead of the public one. Change **only** the text listed below, in TARGET only. Don't change code,
tests, templates, earlier CHANGELOG sections or anything in the public clone. **Don't commit or push.**

## 0. Values and preconditions
Run in TARGET and note the values:
- `NEW_URL` = output of `git -C TARGET remote get-url origin`
- `NEW_NAME` = the last part of `NEW_URL` without `.git`. It must equal TARGET's folder name; if not, stop and
  ask the human which name to use.
- `OLD_URL` = `https://github.com/momchilantonov/ios-chat-tester.git`
- `OLD_NAME` = `ios-chat-tester`

Stop and ask the human if any of these is not true:
- `git -C TARGET log` has no commits yet (the files are uncommitted).
- `grep -c "OLD_URL" TARGET/README.md` prints `4` (the README is still the original). If it isn't, it can be
  restored with `git -C ios-chat-tester show HEAD:README.md > TARGET/README.md`.

## 1. README.md
1. Title: `# iOS chat tester` becomes `# iOS chat tester (NEW_NAME)`.
2. Every `OLD_URL` becomes `NEW_URL` (the clone commands in "Quick start", "Case 1", "Case 2" and "Case 2b").
3. Every remaining `OLD_NAME` becomes `NEW_NAME`: the example in the placeholder table, the paths in "Quick
   start", the `cd` lines in "Case 2" and "Case 2b", and the line `.github/OLD_NAME/` in "Case 2", step 3.
4. In "2. What you need", add this as the first bullet (with the real NEW_URL):
   ```markdown
   - **Read access to NEW_URL** (a private repository). If `git clone` says *Repository not found*, ask its
     owner for access.
   ```
5. Nothing else in the README changes.

## 2. GUIDE_FOR_AGENTS.md
1. Under **Ground rules**, replace the first bullet (`This repository is **public**. ...` up to
   `tester/runs/*`.) with exactly:
   ```markdown
   - This repository is **private** to the organisation. Commit or push only when the human asks. Keep
     machine-specific and personal values (paths, bundle ids, session ids, test-user data) out of tracked files:
     they belong in the git-ignored local files `tester/config.json`, `tester/profile.md`, `tester/plans/*` and
     `tester/runs/*`. Never write customer data or credentials anywhere.
   ```
2. In **6. Evaluate and report back**:
   - replace the line `The report reaches the maintainer as **photos of the screen**. Nothing from this machine
     is uploaded.` with `The report is for the human and the maintainers of this repository. It stays on this
     machine unless the human shares it.`
   - keep the bullet `Write it to tester/runs/REPORT-FOR-MAINTAINER.md ...` unchanged;
   - replace the bullet `Make it readable in a few photos: ...` (all its lines) with
     `- Keep it short and in English, the most important items first.`
   - replace the bullet `Keep it free of project data: ...` (all its lines) with
     `- No customer data and no credentials. Project, flow and field names are fine.`
   - keep the rest of section 6 unchanged.
3. In **Local changes and updates**, replace the first bullet (`This clone is **read-only for you**: ...` up to
   `and you pull.`) with exactly:
   ```markdown
   - Update with `git pull`. Change tracked files, commit or push only when the human asks. A change to the tool
     gets a section in `CHANGELOG.md` and must keep `python3 -m unittest discover -s tests` passing.
   ```
   Keep the other bullets.

## 3. tester/profile.example.md
Replace `here - it stays in your repository, it is not part of the public chat-tester project.` with
`here - it stays on this machine (git-ignored) and is never committed to the tool's repository.`

## 4. CHANGELOG.md
Insert after the line that starts with `Newest first.`, followed by an empty line:
```markdown
## Private copy: NEW_NAME
**After pulling:** nothing to do. No code changes.

- Documentation adapted for this private repository: its address and folder name in the README, a note on
  access, and rules for agents (GUIDE_FOR_AGENTS.md, profile example) that no longer describe a public repo.
```
(with the real NEW_NAME).

## 5. Verify, show, stop
Run in TARGET and report each result:
- `grep -rn -i "momchil\|ios-chat-tester\|public" README.md GUIDE_FOR_AGENTS.md tester/profile.example.md`
  prints nothing.
- `grep -c "NEW_URL" README.md` prints `5` (4 clone commands and the access note).
- `find . -path ./.git -prune -o -type f -print | wc -l` still prints the same number as before (no file
  added or removed).
- `git log` still has no commits.

Then show the human every changed passage as **old → new**, and stop. The human reviews it and makes the first
commit.
