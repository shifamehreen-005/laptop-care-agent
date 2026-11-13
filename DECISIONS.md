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
Why: "deleted" files go to `_safe_to_remove`, name clashes get " (2)", and the undo log lets one click put everything back. Trust is the whole point of the product.

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

**14. Built-in test cases:** a typo-named file (`homewrok.docx`), and `inovice_march.pdf` as an exact copy of `invoice.pdf` under a different name.
Why: tests that sorting handles typos (the text still decides), and that duplicate detection works on contents, not names.

**15. `labels.csv` has an `is_duplicate` column.**
Why: duplicates go to `_safe_to_remove`, not their category, so evals score sorting and duplicate detection separately.

**16. Added 5 "hard" test files with none of the rule keywords** (a cover letter, a history essay, a reading summary, a gym payment, a lease).
Why: with only keyword-friendly files, rules sorted almost everything and the AI never had a real job. Real Downloads folders are full of files like `doc1.docx` and `scan_0042.pdf`.

## Scanning

**17. The scanner is read-only and previews only the first 300 characters of PDFs, Word files and text files.**
Why: it's fast on a slow laptop, and short input suits the small model.

**18. Duplicates are found by sha256 of the contents, exact matches only.**
Why: the file name doesn't matter, and there's no guessing. Near-duplicates (a resized photo, an edited doc) are a later feature.

**19. When files are identical, keep the plain name and set aside the copies ("(1)", "(2)", " - Copy"). If more than one has a plain name, keep the oldest.**
Why: that's what people expect. Keeping `notes_final (1).docx` and removing `notes_final.docx` looked backwards.

## Sorting

**20. Rules first, AI only for the leftovers.**
Why: rules (extension, "Screenshot" names, keywords like invoice/receipt/lecture/meeting) are fast, free and explainable. On the current test folder, rules sort 44 of 52 unique files.

**21. A fixed category list, at temperature 0.**
Why: a 1B model handles a small, closed question far better than inventing folder names. Temperature 0 gives the same answer every time.

**22. Guardrail: the AI's answer must fit the file type, otherwise the file goes to Review.**
Why: in testing, the 1B model sent text files (`export.csv`, `scratch.txt`) to Installers. A text file can never be an installer, so impossible answers are caught instead of acted on.

**23. The AI only chooses between Receipts, School, Work, Other and Review.**
Why: the model answered "Installers" for almost every document. Rules already decide the file-type folders (Installers, Archives, Photos, Screenshots), so offering them to the AI only gave it wrong answers to fall into.

**24. Files with no readable text skip the AI and go straight to Review.**
Why: given an empty `export.csv`, the model made up an answer (Receipts). With nothing to read, there's nothing to decide.

**25. Structured output: the model must return JSON with one category from the allowed list. A system message says it only labels files by topic.**
Why: before this, the 1B model rambled ("I would categorize this as…"), and it refused a gym payment and a lease as if they were sensitive. Structured output gives a clean, valid answer every time.

**26. The prompt puts the file name and text first, then the question, with short examples (including what counts as Other). `planner.py --debug` shows the exact prompt and raw answer.**
Why: I couldn't fix the model's mistakes until I could see exactly what it was given and what it said.

**27. Stop tuning the prompt at this point.**
Why: further changes would just fit these few test files (teaching to the test). Real files in the evals will show what actually needs improving.

## Results so far (52 unique test files)

| Setup | Correct | Review | Wrong moves |
|---|---|---|---|
| Rules only | 44 | 8 | 0 |
| Rules + llama3.2:1b | 49 | 1 | 2 |

The AI fixes 5 files and gets 2 wrong (a gym payment filed as Other, a lease filed as Work). That's why every plan needs the user's approval before anything moves.

## Planned

**28. In the app, label AI decisions ("AI guess") so the user knows which ones to double-check.**

**29. Evals: rules only vs rules + 1B vs rules + 3B, on the generated folder and on 20 real files I label myself. Report accuracy, Review count, wrong moves and seconds per file.**
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
