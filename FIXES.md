# What went wrong

Problems from building and using the review screen, and what changed. Nothing here moves a file until Approve.

**1. Saving a move put the file back in the old folder.**
The Move to menu still held the old folder. The next rerun sent that old value again and undid the move.
Fix: after a move the menu is a new control, and a repeat of the old folder is ignored.

**2. Moving one file sent another file to No folder.**
The preview stayed open on a file such as doc1.docx. Its menu still said "Leave where it is," and that choice means No folder. The next rerun applied it, so doc1 jumped even though a different file was the one you moved.
Fix: the open menu is refreshed after each move, and a drag does not also apply the menu.

**3. The first file put in No folder could not be moved anywhere else.**
The menu treated the next folder you picked as an old value and snapped back to No folder. A drop onto No folder could also be replayed and pull the file back.
Fix: a file in No folder accepts the next folder you pick, and each drop is applied once.

**4. Moving a file replaced Other notes with "moved by you."**
The original reason, including the duplicate explanation, was overwritten.
Fix: the note from the scan stays. Last location is a separate line, placed just above Move to. The old gap under Other notes had pushed that line too far from the menu.

**5. Removing a folder hid its files.**
Work's files left the screen, and the chip count no longer matched the number of scanned files. Files already sitting in the right folder had also been left out of the plan.
Fix: those files go to the No folder card. Empty folders stay visible. A file already in the right folder is shown, and Approve does not move it.

**6. Labels that were saved but not approved came back on the next scan.**
Save wrote them into the label file. Names such as hello showed up again after a new scan.
Fix: the Save button is gone. A label you make is stored only after Approve actually moves files in the test folder. Approving any other folder moves nothing and does not keep the label.

**7. Reset did not clear the similar-name warning.**
"Receipts is already a label. This one was still created." stayed on the screen after Reset.
Fix: Reset clears that warning along with the rest of this scan's edits.

**8. Reset labels and Reset were easy to mix up.**
Reset labels rewrote the saved folder names immediately. Reset only puts this scan back.
Fix: Reset labels was removed. Reset stays beside Undo.

**9. The duplicate list under the cards repeated the Duplicates card.**
The same copies appeared again as long buttons ("copy of …").
Fix: that list is gone. Duplicates stay as a card and a nav tab. Large files and No folder each have a tab and a card, instead of a list under the grid.

**10. An AI guess was hard to tell from the file name.**
The words sat in the same text as the name.
Fix: the guess is blue, beside the name. The AI guesses tab shows only those files, grouped by the folder they landed in.

**11. The create-label box kept the name, and the form hint got in the way.**
The name stayed after Enter, and "Press Enter to submit form" showed even though Enter already worked.
Fix: one Enter button, an empty box, no hint. The Create label button highlights while the box is open and closes after the label is added.

**12. The chip highlight and the preview spacing looked off.**
The selected chip's outline did not sit on the pill. Move to was tight against Other notes, then later the last-location line had too much space above it. Reload was a boxed button.
Fix: a border on the chip, a plain reload arrow, and last location directly above Move to.

**13. The done screen's Undo and the health numbers were unclear.**
Undo did not return to the start. Battery showed nothing while it loaded. Used and free had no plain meaning.
Fix: Undo on that screen always shows, and after it runs you return to the start. Battery says Loading, then the percent or No battery. Disk says space already filled, and space you can still use.

**14. Some failures looked like the app had crashed.**
Stopping the old server reports exit code 4294967295. "Port 8501 is not available" means the previous Python process is still listening. A connection reset in the log is a browser tab that closed. On this OneDrive folder, saving app.py often does not reload the screen by itself.
Fix: none of those are a crash in the tidy. The detail, when it is a real error, goes to app.log, and the screen shows one short sentence. Restarting means stopping the process that is actually listening, then starting again.

**15. "Those files couldn't be deleted" and "couldn't be put back."**
Streamlit reloaded app.py but kept an old copy of executor.py in memory, so the new delete and undo code was missing.
Fix: app.py reloads executor at the start of every run.

**16. After Delete then Undo, a scan showed 53 files instead of 58.**
Undo moved files back before putting deleted files back. Five duplicates ended up stuck in `_safe_to_remove`, which the scan skips. Restore then showed up later by surprise.
Fix: Undo puts deleted files back first, then reverses the moves. The test folder was repaired once by hand (back to 58 files and `my Notes`). A test now checks Delete then Undo gives back the exact starting folder.

**17. Undo and Delete were confusing.**
There were two Undo buttons, error popups covered the screen, and the Undo under the green bar looked like a bar.
Fix: one Undo under the bar with a Yes/No popup, and one Delete or Restore button under Delete files.

**18. Undo left notes and folders behind.**
Old lines stayed in `undo.log`, and an empty `undo_deleted` folder stayed after a restore.
Fix: finished runs are removed from the log, an empty log is deleted, and the empty copies folder is removed.

**19. Messages could not be closed.**
Bars like "Undone. Files are back." stayed until the next action.
Fix: every message bar has a ✕.

**20. A see-through copy of the review screen showed on the done screen.**
Streamlit fades the last screen out while the new one loads, and the battery check takes a few seconds.
Fix: on the start and done screens the faded copy is hidden, so you only see Battery saying Loading. The review screen keeps it, so its cards don't flicker on every click.

**21. A long warning kept showing in the terminal.**
"The widget with key move_… was created with a default value but also had its value set via the Session State API." The Move to menu set its folder twice, once directly and once through session state. Nothing was broken.
Fix: the menu only gets its folder from session state.

**22. The popup stayed up for a moment after Yes.**
Yes did the work inside the popup, so the popup only closed once the files had moved.
Fix: Yes closes the popup first. The page then does the work under a "Working…" spinner placed where the popup was, so it disappears at once. If you click while Battery is still loading, the click waits for it to finish.

**23. `make_test_folder.py --count 120` stopped on Invoice_15.pdf.**
Windows did not keep the dates: the planned time fell in the spring-forward DST gap (2:56 AM), which does not exist locally, so the stamp came back as 3:56 AM and the check failed.
Fix: dates are round-tripped through the real local clock before writing, and the stamp check uses that same time.

**24. Eval download was named like `2026-11-15T22-49_export.csv`.**
That came from Streamlit's built-in dataframe toolbar export, which uses UTC and can't be renamed.
Fix: that export is disabled in `.streamlit/config.toml`. Eval keeps one **Download results** button that uses the local-time `results_*.csv` name.

**25. Removing `CATEGORY_DESCRIPTIONS` from classifier broke the app.**
`folders.py` still imports those short lines for the Tidy folder cards.
Fix: the descriptions stayed for the cards; only the model prompt moved to `prompts/sort_prompt.txt`.

**26. A dead Ollama model could hang the eval for minutes.**
Each silent file waited the full timeout.
Fix: after three silent AI replies in a row, that setup is skipped and the model is unloaded. Warm-up failure also unloads.

**27. Remove on Review also removed the Web Development suggestion.**
Those files were still in Review. The suggestion only shows while at least two of its files are still there. Remove sent them to No folder, so the card vanished.
Fix: none yet. Add the suggestion first if you want to keep it. See `ideas.md`.

**28. `.html` files all went to Review.**
There is no rule for `.html` or `.css`, and the scanner used to not read inside them, so the model was never asked.
Fix: Ask an agent reads the text and asks `qwen2.5:3b`. A normal scan still leaves code and web files in Review so it stays fast.

**29. Ask an agent was slow, and a normal scan got slow too.**
Qwen stayed in memory next to `llama3.2:1b`, so the 8 GB laptop was swapping. Ask an agent also called Qwen once per 8 files. After the scanner started reading HTML, a normal scan sent those files to the model one by one.
Fix: only one model stays loaded. Ask an agent sends up to 40 files in one call. A normal scan skips the model for HTML, CSS, and code.

**30. A normal scan of the test folder still takes about a minute.**
Checked with Ask an agent off and only `llama3.2:1b` loaded. 158 files: 4.4 seconds to read, 116 sorted by rules, 42 documents sent to the model at about 1.1–1.6 seconds each.
Fix: none. Those documents have no rule, so the model has to see them. Ideas for the slow part are in `ideas.md`.

**31. Sort by what's inside put every file in Review, then in Miscellaneous.**
An empty Qwen answer became Review. The model also copied file names, or returned the folder list instead of one folder per file, so the batch was thrown out. Screenshots and installers were sent to Qwen too, and landed in Documents or Scripts. The one call of up to 40 files from fix 29 is gone.
Fix: rules place the obvious files first. Qwen invents folder names only for the leftovers and answers with a `choices` list, 8 files at a time. Miscellaneous becomes Other. Review is only when the name is generic and there is almost no text.

**32. Ask only saw the first 40 characters.**
The topic was often later in the file, so a bill or a homework note was easy to misfile.
Fix: Ask sends the start, middle, and end, in the same name, type, and quoted-text shape as Eval. A short file is sent whole. Eval still uses the first 300 characters.
