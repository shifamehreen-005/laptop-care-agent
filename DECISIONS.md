# Decisions

Why Laptop Care Agent works the way it does. Each line is a choice, followed by the reason for it.

## Product

1. **One job, done well: tidy a folder safely.** One clear story (tidy, ask first, undo) beats a little of everything.
2. **Ask first, always.** Nothing moves until the user approves. Trust matters more than automation.
3. **Everything can be undone.** Every move is logged, and Undo puts every file back, including deleted ones.
4. **A wrong move is worse than Review.** Review asks the user; a wrong move hides a file. Evals count wrong moves separately.
5. **Local only.** The agent reads personal files (receipts, school work), so their text never leaves the laptop. It also works offline and costs nothing per file.
6. **Built for an everyday laptop** (8 GB RAM, GTX 1650). One model is loaded at a time, and small models only.

## Safety

7. **Approve only moves files in the test folder** (`C:\LaptopCareTest\Downloads`). Other folders can be scanned and previewed, but not changed yet.
8. **System folders are blocked:** drive roots, `C:\Windows`, Program Files, ProgramData, AppData, the user profile root, the OneDrive root and the project folder.
9. **Files are never overwritten:** a name clash gets " (2)".
10. **Duplicates are set aside in `_safe_to_remove`, not deleted.** *Delete files* needs a Yes and keeps a copy in `undo_deleted`, so Restore and Undo still work.
11. **Folders the user made are read, but not rearranged.** The scanner reads every subfolder (except `_safe_to_remove`) so it can find duplicates anywhere. Files inside stay put unless they're an exact duplicate, set aside only after Approve.
12. **Files the user placed are only *suggested* for a move,** and only when a rule disagrees, never just the AI.
13. **The app only listens on `localhost`,** so nobody else on the network can trigger file moves.
14. **No raw errors on screen.** The user sees one short sentence; details go to `app.log`.

## Scanning and duplicates

15. **The scanner never changes anything.** It reads names, sizes, dates and the first part of PDF, Word, text and CSV files.
16. **Duplicates mean identical contents (sha256),** whatever their names. An edited file is never a duplicate. Near-duplicates are future work.
17. **Keep rule:** copy-style names ("(1)", " - Copy") lose; otherwise the earliest *created* date wins (when the file arrived); then the older modified date; then alphabetical. The created date comes first because a Windows copy keeps the original's modified date.

## Sorting

18. **Rules first, AI only for the leftovers.** Rules (extensions, "Screenshot" names, keywords like invoice or lecture) are fast, free and explainable.
19. **The AI only chooses Receipts, School, Work, Other or Review.** Rules own the file-type folders. When the AI was offered those too, it answered "Installers" for almost every document.
20. **Guardrails:** files with no readable text skip the AI; an answer that doesn't fit the file type (a `.txt` "Installer") becomes Review; HTML, CSS and code skip the AI on a normal scan.
21. **Structured JSON output at temperature 0.** The 1B model used to ramble, refuse ordinary documents and guess on empty files. JSON forces one valid answer.
22. **The prompt lives in `prompts/sort_prompt.txt`,** with a clear definition for each folder and examples that don't copy the test files.
23. **Other is a folder; Review is a holding pile.** Other means "understood, but not a receipt or school or work." Review means "not enough to tell."
24. **Stop tuning the prompt to the test files.** More tweaks would be teaching to the test. Real files will show what needs improving.

## Review screen

25. **Every file stays visible.** A removed label sends its files to a *No folder* card, and files already in the right place are shown but not moved.
26. **The user's choice always wins.** Moving a file by hand overrides the agent's choice.
27. **AI decisions are marked** in blue, with their own tab, so the user knows what to double-check.
28. **Labels come from the folder being scanned.** Empty default cards (like Receipts in a folder of lecture notes) stay hidden.
29. **A new label is kept only after Approve really moves files.** A typed name shouldn't come back as if it were approved.
30. **Large files (over 100 MB) are a reminder, not an action.** The user decides whether to set them aside.
31. **One Undo, one Reset.** Undo steps back one edit; Reset restarts this scan's review. A finished undo leaves no notes or empty folders behind.

## Ask an agent

32. **It's an optional toggle and doesn't change the scan.** Qwen runs only after the user asks.
33. **"Group by file type" is the only fixed rule** (no AI). Every other request, including "sort by semester," is the model's judgment, because a semester boundary is a guess while an extension is not.
34. **Rules still place the obvious files.** Qwen names 4–8 folders for the leftovers and reads the start, middle and end of each file, since 40 characters missed the topic.
35. **It always uses `qwen2.5:3b`,** the most accurate model in the evals.

## Models

36. **The user picks the model for a normal scan** (llama3.2:1b, llama3.2:3b, qwen2.5:3b). The 1B model is fastest; the 3B models are more accurate.
37. **Only one model stays loaded.** 8 GB can't hold two, so a leftover model is unloaded first.

## Evals

38. **Eval is read-only.** The folder is snapshotted before and after, and the result must say "unchanged."
39. **The answer key is `labels.csv`,** created with the test files and kept outside the test folder, so the agent never sees the answers.
40. **The test folder is generated, repeatable (`--seed`) and includes hard cases:** typo names, a renamed exact copy, and 30 files with no rule keywords (labeled *clear* or *edge*).
41. **Each model is warmed up (not timed), run, then unloaded.** That gives fair timing and keeps memory free.
42. **Accuracy counts non-duplicate files; duplicates are scored separately** (found, missed, wrongly flagged).
43. **Known limit:** the same project wrote the test files and the rules, so real folders will be harder. A real-file eval is the next step.

## Results that shaped decisions

- **Rules only:** 71.4% correct, 0 wrong moves.
- **The 1B model:** 18 wrong moves, too many to trust without review.
- **The 3B models:** 3–6 wrong moves, which is why Ask uses qwen2.5:3b and why approval stays mandatory.
- **A short reason before the answer** cut llama3.2:3b's wrong moves from 12 to 6, but didn't help qwen.

Full results are in the README and `evals/`.