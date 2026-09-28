const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const assert = require("assert/strict");
const fs = require("fs");

// Run only against the isolated local QA database seeded with ExpertAdminTests.setUpTestData().
const fixture = JSON.parse(
  fs.readFileSync(".cache/expert-admin-qa/fixtures.json", "utf8"),
);
const baseUrl = "http://127.0.0.1:8340/admin/users/expert/";
const parameter = "user__partner_program_profiles__partner_program__id__exact";
const output = "docs/expert-admin";
const findings = [];
let assertions = 0;
function check(actual, expected, message) {
  assert.deepEqual(actual, expected, message);
  assertions++;
}

(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.CHROME_PATH,
  });
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1000 },
  });
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("response", (response) => {
    if (response.status() >= 500)
      errors.push(`${response.status()} ${response.url()}`);
  });
  await page.goto(baseUrl);
  await page.locator("#id_username").fill("admin@example.com");
  await page.locator("#id_password").fill("very_strong_password");
  await Promise.all([
    page.waitForNavigation(),
    page.locator('input[type="submit"]').click(),
  ]);
  await page.locator("#searchbar").waitFor();
  check(
    await page.locator("#searchbar").isVisible(),
    true,
    "standard search visible",
  );
  check(
    (await page.locator("#changelist-filter").innerText()).includes(
      "By partner program",
    ),
    true,
    "standard filter title",
  );
  check(
    await page.locator("#changelist-filter a").count(),
    4,
    "All and three programs",
  );

  async function rows(scenario, expected) {
    const ids = await page
      .locator("#result_list input.action-select")
      .evaluateAll((nodes) =>
        nodes.map((node) => Number(node.value)).sort((a, b) => a - b),
      );
    check(
      ids,
      [...expected].sort((a, b) => a - b),
      scenario,
    );
    findings.push({ scenario, expertIds: ids, url: page.url() });
  }
  async function search(query) {
    await page.locator("#searchbar").fill(query);
    await Promise.all([
      page.waitForNavigation(),
      page.locator('#changelist-search input[type="submit"]').click(),
    ]);
  }
  await rows("all", [
    fixture.ivan,
    fixture.anna,
    fixture.otherIvanov,
    fixture.noProgram,
  ]);
  await page.screenshot({ path: `${output}/all-experts.png`, fullPage: true });
  for (const [query, expected] of [
    ["Анна", [fixture.anna]],
    ["Иванов", [fixture.ivan, fixture.otherIvanov]],
    ["иван@example.com", [fixture.ivan]],
    ["Иван Иванов", [fixture.ivan, fixture.otherIvanov]],
    ["Несуществующий", []],
  ]) {
    await search(query);
    await rows(`search: ${query}`, expected);
  }
  await page.goto(baseUrl);
  await Promise.all([
    page.waitForNavigation(),
    page
      .locator("#changelist-filter a")
      .filter({ hasText: `PartnerProgram<${fixture.program}> - FinFor25-26` })
      .click(),
  ]);
  await rows("program", [fixture.ivan, fixture.anna]);
  await search("Иванов");
  await rows("search + program", [fixture.ivan]);
  check(
    new URL(page.url()).searchParams.get(parameter),
    String(fixture.program),
    "search preserves filter",
  );
  await page.screenshot({
    path: `${output}/search-and-program.png`,
    fullPage: true,
  });
  await Promise.all([
    page.waitForNavigation(),
    page
      .locator("#changelist-filter a")
      .getByText("All", { exact: true })
      .click(),
  ]);
  await rows("All preserves search", [fixture.ivan, fixture.otherIvanov]);
  await page.goto(`${baseUrl}?${parameter}=${fixture.otherProgram}`);
  await rows("other program; dual registration appears once", [
    fixture.ivan,
    fixture.otherIvanov,
  ]);
  await page.goto(`${baseUrl}?${parameter}=999999999`);
  await rows("nonexistent program", []);
  await page.goto(`${baseUrl}?${parameter}=not-a-number`);
  check(
    new URL(page.url()).searchParams.get("e"),
    "1",
    "invalid filter redirects to admin error marker",
  );
  check(errors, [], "no runtime errors or HTTP 500");
  fs.writeFileSync(
    `${output}/browser-results.json`,
    JSON.stringify(
      {
        base: "11f1e66a85e266d57fc6b0f8c080ee8cd0683f19",
        browser: await browser.version(),
        assertions,
        errors,
        findings,
      },
      null,
      2,
    ) + "\n",
  );
  console.log(
    `PASS ${assertions} assertions, ${findings.length} result states, errors ${errors.length}`,
  );
  await browser.close();
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
