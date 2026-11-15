# Decisions

Why the project works the way it does. Newest decisions go at the bottom of each section.

## Scope

**1. Do one job well: clean a Downloads folder safely.**
Why: one clear story (tidy, ask first, undo) beats a little of everything. Health checks, Simple mode and other ideas come after the core works.

**2. Ideas saved for later, not the MVP:** "ask your laptop where a setting is" / a new-device guide, near-duplicate detection, fuzzy matching for typo names, user-editable folders or AI-suggested new folders, startup-app cleanup, cross-device (phone) features.
Why: Pixel, Samsung and Windows already answer basic settings questions. Undo and trust are what's different here, so they come first.

## Setup

**3. Windows, Python 3.15, Streamlit for the screens.**
Why: Windows is where Lenovo's users are. I tested 3.15 and every library I need installed cleanly. Streamlit gives a clickable app in plain Python.

**4. Local AI only: Ollama with llama3.2:1b. No cloud APIs.**
Why: the agent reads inside personal files (receipts, school work), so their text should never leave the laptop. It also works offline, costs nothing per file, and matches Lenovo's on-device AI pitch.

**5. The 1B model, not 3B (for now).**
Why: my laptop has 8 GB of RAM and a GTX 1650. The 1B model runs fully on the GPU (`ollama ps` shows 100% GPU). The first reply is slow while the model loads; after that it's fast. I'll compare against 3B in the evals and decide by the numbers.

## Safety

**6. Only touch the test folder set in `config.py`.**
Why: real files are never at risk while I build and test.

**7. Never delete, never overwrite, nothing moves without approval, every move is logged.**
Why: "deleted" files go to `_safe_to_remove`, name clashes get " (2)", and the undo log lets one command put everything back. Trust is the whole point of the product.
Later: a real delete was added on the done screen, but it is still restorable (see 51).

**8. The planner only prints a plan; it never moves files.**
Why: you see exactly what will happen before anything changes.

**9. A wrong move is worse than sending a file to Review.**
Why: Review asks the user; a wrong move hides a file somewhere unexpected. Evals count wrong moves separately from accuracy.

## Test data

**10. Generate a fake messy folder instead of using real files.**
Why: it's safe, repeatable and quick to reset. `--count 50` while building (fast to check by eye), `--count 120` for evals and the demo (enough files for a meaningful accuracy number).

**11. Varied screenshots and photos, with a fixed `--seed`.**
Why: identical images could be wrongly flagged as duplicates and look fake on camera. A fixed seed means the same test folder every time, so results can be reproduced.

**12. `labels.csv` is the answer key, created with the test files and kept outside the test folder.**
Why: the agent sees the list of categories (the choices) but never the answers. The labels are only used to grade it. The agent must never write its own labels.

**13. Hand-added test files get labeled with `add_label.py`, and the scanner warns about any file without a label.**
Why: every file in the test has a known right answer.

**14. Built-in test cases:** a typo-named file (`homewrok.docx`), and a duplicate group with set dates (both created and modified):
- `invoice (1).pdf`: Jan 1 (oldest, but a copy-style name, so it should be set aside)
- `inovice_march.pdf`: Jan 2 (oldest plain name, so it should be kept)
- `invoice.pdf`: Jan 3 (newer plain name, so it should be set aside)

In every other duplicate group, the original gets the earliest date and each copy is one day later. Created dates are set with Windows' `SetFileTime` (through ctypes, no extra library).
Why: tests that sorting handles typos, that duplicates are found by contents rather than names, and every part of the keep rule.

**15. `labels.csv` has an `is_duplicate` column.**
Why: duplicates go to `_safe_to_remove`, not their category, so evals score sorting and duplicate detection separately.

**16. Added 5 "hard" test files with none of the rule keywords** (a cover letter, a history essay, a reading summary, a gym payment, a lease).
Why: with only keyword-friendly files, rules sorted almost everything and the AI never had a real job. Real Downloads folders are full of files like `doc1.docx` and `scan_0042.pdf`.

## Scanning

**17. The scanner is read-only and previews only the first 300 characters of PDFs, Word files and text files.**
Why: it's fast on a slow laptop, and short input suits the small model.

**18. Duplicates are found by sha256 of the contents, exact matches only.**
Why: the file name doesn't matter, and there's no guessing. An edited file is never a duplicate. Near-duplicates (a resized photo, an edited doc) are a later feature.

**19. The scanner checks the top level plus the agent's own folders, one level deep** (Receipts, School, Work, Screenshots, Installers, Archives, Photos, Other, Review). It skips `_safe_to_remove` and any folder the user made.
Why: duplicates or misplaced files inside the agent's folders were invisible before. Folders the user made are theirs, so the agent stays out of them.

**20. Keep rule for duplicates, in order:**
1. Copy-style names ("(1)", "(2)", " - Copy") always lose when a plain-named copy exists.
2. Among plain names, the earliest **created** date wins (when it arrived in the folder).
3. A tie on created date goes to the older **modified** date.
4. If still tied, alphabetical order decides.

Why: people expect the plain name to stay and the newer arrival to be the extra. Created date is used first because real Windows copies keep the original's modified date but get a new created date, so modified dates often tie.

## Sorting

**21. Rules first, AI only for the leftovers.**
Why: rules (extension, "Screenshot" names, keywords like invoice/receipt/lecture/meeting) are fast, free and explainable. On the current test folder, rules sort 44 of 52 unique files.

**22. A fixed category list, at temperature 0.**
Why: a 1B model handles a small, closed question far better than inventing folder names. Temperature 0 gives the same answer every time.

**23. Guardrail: the AI's answer must fit the file type, otherwise the file goes to Review.**
Why: in testing, the 1B model sent text files (`export.csv`, `scratch.txt`) to Installers. A text file can never be an installer, so impossible answers are caught instead of acted on.

**24. The AI only chooses between Receipts, School, Work, Other and Review.**
Why: the model answered "Installers" for almost every document. Rules already decide the file-type folders, so offering them to the AI only gave it wrong answers to fall into.

**25. Files with no readable text skip the AI and go straight to Review.**
Why: given an empty `export.csv`, the model made up an answer (Receipts). With nothing to read, there's nothing to decide.

**26. Structured output: the model must return JSON with one category from the allowed list. A system message says it only labels files by topic.**
Why: before this, the 1B model rambled, and it refused a gym payment and a lease as if they were sensitive. Structured output gives a clean, valid answer every time.

**27. The prompt puts the file name and text first, then the question, with short examples (including what counts as Other). `planner.py --debug` shows the exact prompt and raw answer.**
Why: I couldn't fix the model's mistakes until I could see exactly what it was given and what it said.

**28. Stop tuning the prompt at this point.**
Why: further changes would just fit these few test files (teaching to the test). Real files in the evals will show what actually needs improving.

**29. Files the user already placed in a category folder are only suggested for a move, never moved automatically, and only when a rule disagrees.**
Why: the user may have put a file there on purpose. The AI made 2 wrong moves in testing, so it shouldn't second-guess the user's choices. Suggestions get their own yes/no, which defaults to no.

## Applying and undo

**30. Approval means typing "yes".** `executor.py --apply` shows the plan and waits; anything other than "yes" moves nothing. Suggested fixes get a separate yes/no.
Why: a deliberate action before any change. The app's Approve button will replace typing later.

**31. The undo log is one JSON line per move: `{timestamp, run_id, from, to}`.** `--undo` reverses the most recent run, newest move first. `--runs` lists past runs.
Why: plain text that's easy to read and check. Reversing in order puts every file back exactly, including suggested fixes.
Later: each line also has a sha256, folders a run creates are logged, and a delete is logged with where its copy is kept. Lines for a finished undo or restore are removed (see 53).

**32. If a file was moved or removed after a run, undo skips it, reports it, and keeps going.**
Why: people change things between tidying and undoing. One missing file shouldn't stop everything else from coming back.

**33. Undo removes only the folders that run created, and only if they're empty (`os.rmdir`).**
Why: undo used to leave empty category folders behind. `os.rmdir` can't delete a folder with anything in it, so a folder the user put files into is left alone and reported.

**34. The undo test compares folders as well as files, and covers duplicates inside category folders, a suggested fix applied and undone, and the keep rule.**
Why: the first version only compared files, which is why it passed while empty folders were left behind.

## Results so far (52 unique test files)

| Setup | Correct | Review | Wrong moves |
|---|---|---|---|
| Rules only | 44 | 8 | 0 |
| Rules + llama3.2:1b | 49 | 1 | 2 |

The AI fixes 5 files and gets 2 wrong (a gym payment filed as Other, a lease filed as Work). That's why every plan needs the user's approval before anything moves.

## Planned

**35. In the app, label AI decisions ("AI guess") so the user knows which ones to double-check.**

**36. Evals: rules only vs rules + 1B vs rules + 3B, on the generated folder and on 20 real files I label myself. Report accuracy, Review count, wrong moves and seconds per file.**
Why: the generated test may be easier than real life, since the same project wrote the files and the rules. Honest numbers matter more than high ones.



- Test folder - "C:\LaptopCareTest\Downloads", outside the working project directory
- Test on a generated folder so real files are never at risk
- Labels are generated with the test files and kept outside the test folder, so the agent can’t see the answers.
- "python make_test_folder.py --count 50" - Running it a second time refuses instead of overwriting
- Varied test images so duplicate detection is tested fairly; fixed seed so the test folder is repeatable
- "python scanner.py"
Result:
Files: 50
Total size: 718677 bytes
Duplicates: 4
- Duplicates found by sha256: exact match only, no guessing.
- Ran: powershell -Command "Measure-Command { python scanner.py }"
Results:
Days              : 0
Hours             : 0
Minutes           : 0
Seconds           : 1
Milliseconds      : 219
Ticks             : 12192630
TotalDays         : 1.41118402777778E-05
TotalHours        : 0.000338684166666667
TotalMinutes      : 0.02032105
TotalSeconds      : 1.219263
TotalMilliseconds : 1219.263

## The app

Newest screen decisions. Each one is something we settled on after using the review screen.

**37. Approve is the only way to keep a change.**
The top row is Approve and Cancel, with "Nothing moves until you approve." There is no Save button.
Why: Save was easy to mix up with Approve, and it stored folder names before any file had moved.

**38. A label you make is kept only after Approve really moves files.**
On the next scan it shows up only if that Approve ran in the test folder. Approving any other folder says "Nothing was moved." and does not keep the label.
Why: a name that was only typed was coming back on the next scan, as if it had been approved.

**39. Undo steps back one edit. Reset puts this scan back to the start.**
Both sit beside Cancel. Undo is a grey pill and is faded until something changes. Reset puts the cards back to how the scan first arranged them, and clears a similar-name warning. Neither rewrites saved folder names. The old Reset labels button is gone.
Why: Undo is the last edit. Reset is "start this scan over." Reset labels rewrote the saved names immediately, which was a different job.

**40. The nav shows one group at a time.**
Files shows every file. Duplicates, Review, Other, No folder, Large files, and AI guesses each show that group. An AI guess is blue text beside the file name, not part of the name. The mode (Rules only, or Rules + AI) sits at the end of the bar.
Why: one screen of every card was hard to read. A tab answers "what did the AI do?" without a second list under the cards.

**41. No folder is a real card.**
It stays on Files even when it is empty, so a file can be dropped in, and it has its own tab. Removing a label sends that label's files there. Approve does not move a file until you place it in a folder.
Why: removing Work used to hide those files. Every scanned file stays visible.

**42. A file already in the right folder stays on the screen, and Approve leaves it there.**
Why: the plan skipped those files, so the file count and the chips did not match.

**43. Other notes stay the note from the scan.**
Moving a file does not replace them with "moved by you." A duplicate still says which copy is kept, where each copy sits, and why this one is the extra. "Last location" sits just above Move to.
Why: the note is why the file was sorted that way. Replacing it, or leaving a big gap above the menu, made the preview hard to use.

**44. The agent does not open folders you made.**
It reads only its own folders. An extra duplicate inside one can be offered for Safe to remove, and still waits for Approve. If a rule disagrees with a file you already placed, that is only a suggestion, and it stays put unless you accept it. The AI is not asked about a file that already has a folder.
Why: those folders are yours. A suggestion that moved on its own was how files ended up somewhere unexpected.

**45. Other is a folder. Review is a holding pile.**
Other is for notes, data, and records that are understood but are not receipts, school, work, screenshots, installers, archives, or photos. Review is for no matching rule, almost no readable text, or an answer that does not fit the file.
Why: the two cards looked like the same "not sure" pile.

**46. A similar new label warns you, and is still created.**
"School work" warns that School is already there, then creates the label. With AI on, it says it is sorting from the new label and sorts again. The exact same name is refused. Reset clears the warning.
Why: a close name is worth a warning, but blocking it stopped a label you still wanted.

**47. Create label opens one name box.**
The button is highlighted while the box is open. Enter adds the label, then the box closes. There is no extra hint about pressing Enter.
Why: a box that stayed filled, plus an Add button and a form hint, was more than the one action.

**48. Large files are a card on their own tab.**
A file over 100 MB shows there. Set aside is in the preview, and Approve sends ticked ones to Safe to remove with the other chosen moves. The duplicate list under the cards is gone. The Duplicates card and its tab stay.
Why: the same files were listed twice, once as cards and again as buttons.

**49. After Approve, Undo is always on the done screen and returns to the start.**
Disk says how much space is filled and how much is free. Battery says Loading, then the percent, or No battery.
Why: the old Undo asked a second question, and the disk and battery numbers had no plain meaning.

**50. The screen never shows a raw error.**
A short sentence is shown. The detail goes to app.log.
Why: a traceback is not something you can decide from.

**51. Delete files removes the whole Safe to remove folder, and keeps a copy to restore.**
It has its own heading on the done screen, above Disk and Battery. A Yes/No popup asks first. Each file is copied to `C:\LaptopCareTest\undo_deleted`, then removed from the test folder. The button then becomes **Restore deleted files back?**, which puts the folder back.
Why: you asked for a real delete, but a mistake still has to be fixable. The copies sit outside Downloads, so a scan never sees them.

**52. One Undo, under the green Done bar: "Put every file back?"**
It looks like a button (blue border, light fill), not a bar. A Yes/No popup asks first. Yes puts back any deleted files first, then reverses this approval's moves, then returns to the start page.
Why: two Undo buttons were confusing. Restoring deletions first is what stops files getting stuck (see FIXES 16).

**53. Undo and Restore leave nothing behind.**
After they finish, the copies folder is removed and that run's lines are taken out of `undo.log`. An empty log file is deleted.
Why: a finished undo should not leave an empty folder or old notes around.

**54. The done bar is a soft green.**
A light see-through green with dark green text, matching the theme, instead of a bold bar.
Why: it should say "done" clearly without shouting.

**55. Every message bar has a ✕ to close it.**
That covers success, info, warning and error bars, including Undone and label warnings. A saved note (like "Undone. Files are back.") is cleared when closed. The folder warnings stay closed for that session.
Why: a message you have read should not sit on the screen.

**56. Yes closes the popup at once, then the page says Working.**
Undo, Delete and Restore show a "Working…" spinner while files move.
Why: a popup that hangs after Yes feels like the click didn't work.

**57. The cards come from the folder you scan.**
A saved label (a default like Receipts, or one you made) shows only if files from this folder land in it, or a folder with that name is already there. The rest start hidden but stay in Move to. Moving a file in, or typing that name in Create label, brings the card back, and it stays. Review and Other still open from their tabs.
Why: a folder of lecture notes showed empty Receipts, Installers and Photos cards, as if every folder were a Downloads folder.

## Evals

**58. The prompt moved to `prompts/sort_prompt.txt`, with a definition per folder and an optional 10-word reason before the category. This replaces 28.**
"Leases" was left out of Other on purpose: the lease file was one of the two AI mistakes, so naming it would teach to the test. The generated folder has now been seen while writing the prompt, so the real-file set (36) is the honest number.
Why: the eval needs a prompt worth comparing across models, and the reason shows why a file went where it did.

**59. Eval is read-only and uses the default categories only.**
It snapshots the folder before and after and reports "Folder unchanged". Results go to `evals/results_<date>.csv` and `.md`, a new name each run, and never inside the tested folder.
Why: grading must not change what it grades, and old runs are kept for comparison.

**60. Each model is warmed up (not timed), run, then unloaded. Anything already loaded is unloaded first.**
Why: the first call to a model is the slow load, not its real speed, and 8 GB can't hold two models.

**61. Duplicates are scored once, not per setup.**
Why: the scanner finds copies by their bytes, so every setup gets the same answer.

**62. Tidy uses the new prompt too, but keeps its 30-second timeout. The eval waits up to 120 seconds.**
Why: a 3B model can be that slow, but the app shouldn't hang that long per file if Ollama stalls.
