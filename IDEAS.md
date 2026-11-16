# Ideas and future work

Not built yet. Grouped by what each one would make possible.

## Next steps

1. **Real-file eval.** Grade about 20 of my own files, labeled by hand. The generated folder is easier than real life, so this is the honest number.
2. **Approve on real folders.** Today any folder other than the test folder is preview-only. Turn it on once real-file evals and undo have been proven.
3. **Delete that frees space.** Deleted files are kept in `undo_deleted` until Undo or Restore. Clear those copies after a set time (for example, 30 days) or with a second "Empty for good" step.
4. **Better default model.** Make `qwen2.5:3b` the default for a normal scan, since it had the fewest wrong moves in the evals.

## Faster, and bigger folders

5. **Remember files that haven't changed.** Save each file's answer with its sha256, and skip it on the next scan.
6. **Sort the leftovers locally after naming folders.** Once Qwen has named the folders, match most files by name and keywords, and only ask the AI about the unsure ones.
7. **Big folders (thousands of files).** Scan in the background, show "Sorted 200 of 3,000," allow Stop, and approve in batches.
8. **Collapse large cards.** Over about 20 files, show the count, a search box and Show all.
9. **Keep the model loaded while in Ask mode,** since switching models is the slow part on 8 GB.

## Smarter sorting

10. **Test on more kinds of files:** spreadsheets, slides, scanned PDFs (with text recognition), code, and other languages.
11. **Near-duplicates:** the same photo resized, or two versions of an essay.
12. **Fuzzy names:** treat "recipt" like "receipt" when a file has no readable text.
13. **Sort by semester, subject or project,** for example School › Fall 2026 › Biology, from dates and contents.
14. **Learn how each user likes things arranged.** Every Approve, move or rename is feedback. Over time, the agent should suggest the user's own folders and stop repeating mistakes, without retraining a model.
15. **Suggest new folders from patterns:** "You have 9 tax documents. Create a Taxes folder?"

## Photos

16. **Sort pictures into albums** by date, place or event.
17. **Search photos by description,** for example "pictures where I'm wearing a hat," using a local image model.
18. **Search with an image:** give one photo, get similar ones.

## Laptop health

19. **Explain what's slowing the laptop down:** a full disk, startup apps, battery wear, big old files, in plain words with one suggested fix each.
20. **A Laptop Life report** that tracks storage, battery and startup over time, to help the laptop last longer.
21. **Scheduled check-ups** that suggest a tidy-up and still wait for approval.

## Easier for everyone

22. **Simple mode for older users:** big text, one question at a time ("Move these 8 files to Receipts?"), read aloud.
23. **Family approval:** a family member approves a parent's cleanup from their phone.
24. **"Ask your laptop":** where is a setting, how do I check storage, how do I unblock an app.

## Across devices

25. **Connect personal devices** (phone, tablet, laptop): find duplicates across them, tidy downloads everywhere, and answer "how much space is left on my phone?" from the laptop.
26. **Work with AI assistants:** expose scan, plan, apply and undo as tools, so an assistant could tidy files on request, always with the user's approval.
