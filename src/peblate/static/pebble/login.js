/* Firebase is used only to obtain a fresh identity proof. Weblate owns sessions. */
(() => {
  "use strict";
  const status = document.getElementById("pebble-login-status");
  const buttons = [...document.querySelectorAll("[data-provider]")];
  const form = document.getElementById("pebble-login-form");
  const busy = (value) => buttons.forEach((button) => { button.disabled = value; });
  if (!window.firebase) {
    status.textContent = "Could not load sign-in. Please reload and try again.";
    return;
  }
  const app = firebase.initializeApp(
    JSON.parse(document.getElementById("pebble-firebase-config").textContent),
    "peblate-login",
  );
  const auth = app.auth();
  auth.setPersistence(firebase.auth.Auth.Persistence.NONE).then(() => {
    status.textContent = "";
    busy(false);
  }).catch(() => {
    status.textContent = "Could not start sign-in. Please reload and try again.";
  });
  buttons.forEach((button) => button.addEventListener("click", async () => {
    busy(true);
    status.textContent = "Complete sign-in in the popup window.";
    let provider;
    if (button.dataset.provider === "google") {
      provider = new firebase.auth.GoogleAuthProvider();
      provider.setCustomParameters({ prompt: "select_account" });
    } else if (button.dataset.provider === "github") {
      provider = new firebase.auth.GithubAuthProvider();
      provider.addScope("user:email");
    } else {
      provider = new firebase.auth.OAuthProvider("apple.com");
      provider.addScope("email");
      provider.addScope("name");
    }
    try {
      const result = await auth.signInWithPopup(provider);
      const token = await result.user.getIdToken(true);
      await auth.signOut();
      form.elements.id_token.value = token;
      status.textContent = "Checking your Pebble account…";
      form.submit();
    } catch (error) {
      await auth.signOut().catch(() => {});
      form.elements.id_token.value = "";
      const messages = {
        "auth/popup-closed-by-user": "Sign-in cancelled. You can try again.",
        "auth/popup-blocked": "Allow popups for this site, then try again.",
        "auth/unauthorized-domain": "Sign-in is not configured for this site yet.",
        "auth/account-exists-with-different-credential": "Use the sign-in provider you originally used for your Pebble account.",
      };
      status.textContent = messages[error.code] || "Sign-in failed. Please try again.";
      busy(false);
    }
  }));
})();
