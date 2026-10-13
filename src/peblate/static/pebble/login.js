/* Firebase is used only to obtain a fresh identity proof. Weblate owns sessions. */
(() => {
  "use strict";
  const status = document.getElementById("pebble-login-status");
  const buttons = [...document.querySelectorAll("[data-provider]")];
  const form = document.getElementById("pebble-login-form");
  const title = document.getElementById("pebble-login-title");
  const signinOptions = document.getElementById("pebble-signin-options");
  const existingSignin = document.getElementById("pebble-existing-signin");
  const verification = document.getElementById("pebble-email-verification");
  const verificationEmail = document.getElementById("pebble-verification-email");
  const sendVerification = document.getElementById("pebble-send-verification");
  const checkVerification = document.getElementById("pebble-check-verification");
  let verificationUser = null;
  const busy = (value) => [...buttons, sendVerification, checkVerification]
    .forEach((button) => { button.disabled = value; });
  if (!window.firebase) {
    status.textContent = "Could not load sign-in. Please reload and try again.";
    return;
  }
  const app = firebase.initializeApp(
    JSON.parse(document.getElementById("pebble-firebase-config").textContent),
    "peblate-login",
  );
  const auth = app.auth();
  const showVerification = (value) => {
    verification.hidden = !value;
    signinOptions.hidden = value;
    existingSignin.hidden = value;
    title.textContent = value ? "Verify your email" : "Sign in with Pebble";
  };
  const complete = async (user) => {
    const token = await user.getIdToken(true);
    await auth.signOut();
    form.elements.id_token.value = token;
    status.textContent = "Checking your Pebble account…";
    form.submit();
  };
  sendVerification.addEventListener("click", async () => {
    if (!verificationUser) return;
    busy(true);
    try {
      await verificationUser.sendEmailVerification();
      sendVerification.textContent = "Resend verification email";
      status.textContent = "Verification email sent. Open the link in your inbox (check spam too), then return here and select ‘I’ve verified my email’.";
    } catch (error) {
      status.textContent = error.code === "auth/too-many-requests"
        ? "Too many verification requests. Please wait before trying again."
        : "Could not send the verification email. Please try again.";
    } finally {
      busy(false);
    }
  });
  checkVerification.addEventListener("click", async () => {
    if (!verificationUser) return;
    busy(true);
    try {
      await verificationUser.reload();
      if (!verificationUser.emailVerified) {
        status.textContent = "Your email is not verified yet. Open the link in the verification email, then try again.";
        busy(false);
        return;
      }
      await complete(verificationUser);
    } catch (error) {
      if (error.code === "auth/user-token-expired" || error.code === "auth/invalid-user-token") {
        await auth.signOut().catch(() => {});
        verificationUser = null;
        showVerification(false);
        status.textContent = "Your Pebble sign-in expired. Please sign in again.";
      } else {
        status.textContent = "Could not check your email verification. Please try again.";
      }
      busy(false);
    }
  });
  auth.setPersistence(firebase.auth.Auth.Persistence.NONE).then(() => {
    status.textContent = "";
    busy(false);
  }).catch(() => {
    status.textContent = "Could not start sign-in. Please reload and try again.";
  });
  buttons.forEach((button) => button.addEventListener("click", async () => {
    busy(true);
    verificationUser = null;
    showVerification(false);
    form.elements.id_token.value = "";
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
      if (!result.user.email || !result.user.email.trim()) {
        await auth.signOut();
        status.textContent = "Your sign-in provider did not supply an email address. Add an email to that account, then try again.";
        busy(false);
        return;
      }
      if (!result.user.emailVerified) {
        verificationUser = result.user;
        verificationEmail.textContent = result.user.email;
        sendVerification.textContent = "Send verification email";
        showVerification(true);
        status.textContent = "Verify your email address to continue. Select ‘Send verification email’ below.";
        busy(false);
        return;
      }
      await complete(result.user);
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
