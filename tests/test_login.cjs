const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const { test } = require("node:test");
const { runInNewContext } = require("node:vm");

const script = readFileSync(join(__dirname, "../src/peblate/static/pebble/login.js"), "utf8");

async function login({ verified = false, email = "translator@example.org" } = {}) {
  const elements = {};
  const element = (id) => elements[id] = {
    textContent: "", disabled: true, hidden: true, listeners: {},
    addEventListener(event, callback) { this.listeners[event] = callback; },
    async click() {
      assert.equal(this.disabled, false, `${id} should be enabled`);
      await this.listeners.click();
    },
  };
  const providers = ["google", "github", "apple"].map((provider) => {
    const button = element(provider);
    button.dataset = { provider };
    return button;
  });
  const status = element("pebble-login-status");
  element("pebble-login-title").textContent = "Sign in with Pebble";
  element("pebble-signin-options").hidden = false;
  element("pebble-existing-signin").hidden = false;
  const verification = element("pebble-email-verification");
  const address = element("pebble-verification-email");
  const send = element("pebble-send-verification");
  const check = element("pebble-check-verification");
  element("pebble-firebase-config").textContent = "{}";
  const calls = [];
  const user = {
    email, emailVerified: verified,
    async getIdToken(force) { calls.push(["token", force]); return "fresh-token"; },
    async sendEmailVerification() { calls.push("email"); },
    async reload() { calls.push("reload"); },
  };
  const auth = {
    async setPersistence(value) { calls.push(["persistence", value]); },
    async signInWithPopup() { calls.push("popup"); return { user }; },
    async signOut() { calls.push("signout"); },
  };
  const form = element("pebble-login-form");
  form.elements = { id_token: { value: "" } };
  form.submit = () => calls.push("submit");
  class Provider {
    addScope() {}
    setCustomParameters() {}
  }
  const firebase = {
    initializeApp: () => ({ auth: () => auth }),
    auth: {
      Auth: { Persistence: { NONE: "NONE" } },
      GoogleAuthProvider: Provider, GithubAuthProvider: Provider, OAuthProvider: Provider,
    },
  };
  runInNewContext(script, {
    window: { firebase }, firebase,
    document: {
      getElementById: (id) => elements[id],
      querySelectorAll: () => providers,
    },
  });
  await Promise.resolve();
  return { elements, status, verification, address, send, check, calls, user, auth, form };
}

test("verified providers submit a fresh token and clear Firebase sign-in", async () => {
  for (const provider of ["google", "github", "apple"]) {
    const page = await login({ verified: true });
    await page.elements[provider].click();
    assert.equal(page.verification.hidden, true);
    assert.equal(page.form.elements.id_token.value, "fresh-token");
    assert.deepEqual(page.calls.slice(-3), [["token", true], "signout", "submit"]);
    assert.equal(page.calls.includes("email"), false);
  }
});

test("GitHub email verification waits for the email link before submitting", async () => {
  const page = await login();
  assert.equal(page.elements["pebble-signin-options"].hidden, false);
  await page.elements.github.click();
  assert.equal(page.verification.hidden, false);
  assert.equal(page.elements["pebble-signin-options"].hidden, true);
  assert.equal(page.elements["pebble-existing-signin"].hidden, true);
  assert.equal(page.elements["pebble-login-title"].textContent, "Verify your email");
  assert.equal(page.address.textContent, page.user.email);
  assert.equal(page.form.elements.id_token.value, "");
  assert.equal(page.calls.includes("signout"), false);
  assert.equal(page.calls.includes("email"), false);

  await page.send.click();
  assert.equal(page.calls.at(-1), "email");
  assert.match(page.status.textContent, /Verification email sent/);
  assert.match(page.send.textContent, /Resend/);

  await page.check.click();
  assert.match(page.status.textContent, /not verified yet/);
  assert.equal(page.calls.includes("submit"), false);
  assert.equal(page.form.elements.id_token.value, "");

  page.user.reload = async () => {
    page.calls.push("reload");
    page.user.emailVerified = true;
  };
  await page.check.click();
  assert.deepEqual(page.calls.slice(-4), ["reload", ["token", true], "signout", "submit"]);
});

test("missing provider emails cannot send verification or submit tokens", async () => {
  for (const email of [null, "", " "]) {
    const page = await login({ email });
    await page.elements.github.click();
    assert.equal(page.verification.hidden, true);
    assert.equal(page.form.elements.id_token.value, "");
    assert.equal(page.calls.includes("submit"), false);
    assert.equal(page.calls.at(-1), "signout");
    assert.match(page.status.textContent, /did not supply an email/);
    assert.equal(page.elements.github.disabled, false);
  }
});

test("verification failures leave controls available for retry", async () => {
  const page = await login();
  await page.elements.github.click();
  page.user.sendEmailVerification = async () => { throw { code: "auth/too-many-requests" }; };
  await page.send.click();
  assert.match(page.status.textContent, /Please wait/);
  assert.equal(page.send.disabled, false);
  page.user.sendEmailVerification = async () => { throw { code: "auth/network-request-failed" }; };
  await page.send.click();
  assert.match(page.status.textContent, /Could not send/);
  page.user.reload = async () => { throw new Error("offline"); };
  await page.check.click();
  assert.match(page.status.textContent, /Could not check/);
  assert.equal(page.check.disabled, false);
  assert.equal(page.elements["pebble-signin-options"].hidden, true);
  assert.equal(page.calls.includes("submit"), false);
});

test("expired verification sign-in returns to provider selection", async () => {
  const page = await login();
  await page.elements.github.click();
  page.user.reload = async () => { throw { code: "auth/user-token-expired" }; };
  await page.check.click();
  assert.equal(page.verification.hidden, true);
  assert.equal(page.elements["pebble-signin-options"].hidden, false);
  assert.equal(page.elements["pebble-existing-signin"].hidden, false);
  assert.equal(page.elements["pebble-login-title"].textContent, "Sign in with Pebble");
  assert.match(page.status.textContent, /sign-in expired/);
  assert.equal(page.calls.at(-1), "signout");
  page.auth.signInWithPopup = async () => { throw { code: "auth/popup-closed-by-user" }; };
  await page.elements.google.click();
  assert.equal(page.verification.hidden, true);
  assert.match(page.status.textContent, /cancelled/);
  assert.equal(page.form.elements.id_token.value, "");
  const before = [...page.calls];
  await page.send.click();
  assert.deepEqual(page.calls, before);
});
