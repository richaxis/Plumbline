# Demo sequence

Run the executable version: `python -m pytest tests/test_logic_sdkfree.py::test_flip_needs_two_consecutive_decisive_failures`

1. `open_case("docs", "Example project docs", <examples/rubric.json>, <examples/evidence.json>)`
2. `assess("docs", 0)`. Validators score 9/9/9 -> weighted 90 -> PASS. Standing is `SET` to PASS.
3. The docs rot. `assess("docs", 1)` scores 2/2/2 -> FAIL band, but standing stays PASS (`FLIP_PENDING`, 1 of 2).
4. A borderline round (7/7/7) resets the streak (`HELD_BORDERLINE`). Noise does not accumulate.
5. Two consecutive FAIL rounds -> `FLIPPED`. `is_passing("docs")` is now false.
6. Any other contract can gate on `is_passing` without knowing the rubric.
