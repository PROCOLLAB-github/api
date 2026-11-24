const assert = require("node:assert/strict");
const { randomUUID } = require("node:crypto");
const { chromium, request } = require("playwright");
const { PNG } = require("pngjs");
const { deploy } = require("./dev_ci_ssh.cjs");

const base = "https://dev.procollab.ru";
const ref = process.env.EXPECTED_API;
assert.match(ref, /^[a-f0-9]{40}$/);
const suffix = randomUUID();
const actorEmail = "qa-branding-" + suffix + "@example.com";
const draftName = "QA оформление " + suffix;
async function django(source, capture = false) {
  let out = "";
  await deploy({
    host: process.env.DEV_SERVER_HOST,
    username: process.env.DEV_SERVER_USER,
    password: process.env.DEV_SERVER_PASSWORD,
    hostFingerprint: process.env.DEV_SSH_HOST_KEY_SHA256,
    timeoutMs: 120000,
    script: [
      "set +x",
      "set -eu",
      "cd /root/api",
      'web="$(docker compose -f docker-compose.dev-ci.yml ps -q web)"',
      'image="$(docker inspect -f \'{{.Config.Image}}\' "$web")"',
      'case "$image" in procollab-dev-api:' + ref + '-*) ;; *) exit 31 ;; esac',
      'docker exec -i "$web" python - <<\'BRANDING_QA_PY\'',
      "import os",
      "os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'procollab.settings')",
      "import django",
      "django.setup()",
      "from django.contrib.auth import get_user_model",
      "User = get_user_model()",
      "email = " + JSON.stringify(actorEmail),
      source,
      "BRANDING_QA_PY",
    ].join("\n"),
  }, capture ? {write(chunk) { out += chunk; }} : process.stdout);
  return out;
}
function image(name, tone) {
  const png = new PNG({width: 420, height: 260});
  for (let i = 0; i < png.data.length; i += 4) {
    png.data[i] = (i / 4 + tone) % 214;
    png.data[i + 1] = tone;
    png.data[i + 2] = (i / 420) % 246;
    png.data[i + 3] = 255;
  }
  return { name, mimeType: "image/png", buffer: PNG.sync.write(png) };
}
async function run() {
  const raw = await django([
    "from datetime import timedelta",
    "from django.contrib.auth.models import Permission",
    "from rest_framework_simplejwt.tokens import RefreshToken",
    "import json",
    "user = User.objects.create_user(email=email, first_name='Service', last_name='QA', birthday='1990-01-01', is_active=True)",
    "user.user_permissions.add(Permission.objects.get(content_type__app_label='partner_programs', codename='add_partnerprogram'))",
    "refresh = RefreshToken.for_user(user)",
    "refresh.set_exp(lifetime=timedelta(minutes=15))",
    "access = refresh.access_token",
    "access.set_exp(lifetime=timedelta(minutes=12))",
    "print('QA_SESSION:' + json.dumps({'access':str(access),'refresh':str(refresh)}))",
  ].join("\n"), true);
  const line = raw.split(/\r?\n/).find(x => x.startsWith("QA_SESSION:"));
  assert.ok(line, "Synthetic session not created");
  const tokens = JSON.parse(line.slice("QA_SESSION:".length));
  console.log("::add-mask::" + tokens.access);
  console.log("::add-mask::" + tokens.refresh);
  const api = await request.newContext({baseURL:base, extraHTTPHeaders:{Authorization:"Bearer " + tokens.access}});
  let browser;
  try {
    const created = await api.post("/programs/drafts/", {data:{name:draftName,format:"noncompetitive",idempotency_key:suffix}});
    assert.equal(created.status(), 201, "Draft creation");
    const {id} = await created.json();
    const settings = async () => {
      const response = await api.get("/programs/" + id + "/management/");
      assert.equal(response.status(), 200, "Management settings");
      return response.json();
    };
    const expectedTag = (await settings()).tag;
    assert.match(expectedTag, /^program-[0-9a-f]{32}$/);
    console.log("The deployed API assigned an automatic tag for draft " + id);

    browser = await chromium.launch();
    const context = await browser.newContext({baseURL:base});
    await context.addCookies(Object.entries({devAccessToken:tokens.access,devRefreshToken:tokens.refresh}).map(([name,value])=>({name,value,url:base})));
    const page = await context.newPage();
    page.setDefaultTimeout(20000);
    const settingsUrl = "/office/program/" + id + "/management/settings";
    await page.goto(settingsUrl);
    await page.getByRole("heading",{name:"Основная информация",exact:true}).waitFor();
    assert.equal(await page.locator("#program-tag").count(),0);

    const items = [
      ["Обложка программы","Компьютер","cover_image_address","cover"],
      ["Обложка для телефона","Телефон","mobile_cover_image_address","mobile_cover"],
      ["Аватар программы","Аватар программы","image_address","logo"],
      ["Баннер регистрации","Баннер регистрации","advertisement_image_address",null],
    ];
    for (const [title,label,field,frameKey] of items) {
      const card = page.locator(".management__image").filter({has:page.getByText(title,{exact:true})});
      const dialog = page.getByRole("dialog",{name:title,exact:true});
      const save = async () => {
        const updated = page.waitForResponse(response =>
          response.request().method() === "PATCH" && response.url().endsWith("/management/settings/basic/"));
        await dialog.getByRole("button",{name:"Сохранить",exact:true}).click();
        assert.equal((await updated).status(),200,"Settings PATCH: "+field);
        await dialog.waitFor({state:"hidden"});
      };
      await card.locator("input[type=file]").setInputFiles(image("first.png",80));
      const crop = dialog.locator(".image-crop__frame");
      if (frameKey) { await crop.waitFor(); await crop.press("+"); }
      await save();
      const first = await settings();
      assert.ok(first[field],"Missing uploaded URL: " + field);
      if (frameKey) assert.equal(first.image_framing[frameKey].zoom,1.1);
      assert.equal(await card.locator(".management__dropzone").count(),0);
      await page.reload();
      const pencil = card.getByRole("button",{name:"Изменить изображение: "+label,exact:true});
      await pencil.click();
      const previousImage = dialog.locator("app-program-image-crop img");
      await previousImage.waitFor();
      if (frameKey) await crop.waitFor();
      await dialog.locator("input[type=file]").setInputFiles(image("replacement.png",145));
      if (frameKey) await crop.waitFor();
      await save();
      const replaced = await settings();
      assert.notEqual(replaced[field],first[field],"Replacement URL: "+field);
      assert.equal(replaced.tag,expectedTag,"The automatic tag changed");
      console.log("Upload, save, reload and replace verified for "+field);
    }
  } finally {
    if (browser) await browser.close();
    await api.dispose();
  }
}
run().catch(error => {
  console.error(String(error.message));
  process.exitCode = 1;
}).finally(async () => {
  try {
    await django([
      "from partner_programs.models import PartnerProgram",
      "from django.contrib.auth.models import Permission",
      "user = User.objects.filter(email=email, is_staff=False, is_superuser=False).first()",
      "if user:",
      "    PartnerProgram.objects.filter(created_by=user, draft=True, name=" + JSON.stringify(draftName) + ").delete()",
      "    user.user_permissions.clear()",
      "    user.is_active = False",
      "    user.save(update_fields=['is_active'])",
      "    print('Synthetic draft removed and test session revoked')",
    ].join("\n"));
  } catch {
    console.error("Synthetic fixture cleanup could not be verified");
    process.exitCode = 1;
  }
});
