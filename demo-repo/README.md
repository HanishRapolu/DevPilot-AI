# Intentional bug fixture

Two bugs: discounted_price(200,10) returns 190 instead of 180, and average([2,4,6]) returns 3 instead of 4. Empty averages and invalid discounts raise ValueError. The expected unpatched baseline is **2 failed, 2 passed**.

Use the shared sandbox/ image and Testing MCP, not a separate fixture Dockerfile. See docs/setup-guide.md for the fixed SANDBOX_TEST_PATH and repository allowlist. This folder is part of the application repository; it does not represent a separate external repository. Do not fix the baseline fixtures when running application correctness tests.
