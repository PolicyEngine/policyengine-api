The live staging tests in a release run each get their own pytest worker, so the step takes about as long as the longest test instead of the tests on the busier of two workers.
