
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
