
- Test folder - "C:\LaptopCareTest\Downloads", outside the working project directory
- Test on a generated folder so real files are never at risk
- Labels are generated with the test files and kept outside the test folder, so the agent can’t see the answers.
- "python make_test_folder.py --count 50" - Running it a second time refuses instead of overwriting
- Varied test images so duplicate detection is tested fairly; fixed seed so the test folder is repeatable