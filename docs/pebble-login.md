# Pebble Accounts login

Peblate integrates Firebase with Weblate's existing social-auth pipeline. It
preserves Weblate account IDs, roles, contribution history, password confirmation,
two-factor authentication, and audit entries. The native password login remains
available for recovery. This feature is disabled by default.

This integration **only links and signs in existing Weblate accounts**. It
does not create accounts, even if Weblate registration is accidentally opened.
Any verified email is accepted, but matching an email never automatically
links accounts: the user must first authenticate to their existing Weblate account.

## Configuration

After installing the updated Peblate wheel, append this to the existing Weblate
settings override:

```python
from peblate.auth_settings import configure_pebble_auth

configure_pebble_auth(globals())
```

Supply these environment variables to the Weblate processes:

```dotenv
PEBLATE_FIREBASE_ENABLED=1
PEBLATE_FIREBASE_PROJECT_ID=coreapp-ce061
PEBLATE_FIREBASE_AUTH_DOMAIN=coreapp-ce061.firebaseapp.com
PEBLATE_FIREBASE_API_KEY=<existing Pebble Firebase web API key>
```

The Firebase web API key is browser configuration, not a service-account private
key. Token verification uses Google's public signing certificates. No Firebase
admin private key, signing key, or shared SSO cookie secret is required.
The former `PEBLATE_FIREBASE_TEST_EMAILS` setting is no longer used and can be
removed from deployment configuration **after deploying the updated Peblate image**.
Older images still require that setting; the updated image ignores it.

Keep `WEBLATE_REGISTRATION_OPEN=0` and the project private during testing. These
settings do not grant project access or change any user's role. The Firebase
backend requires a verified email matching the existing Weblate account on every
sign-in, including returning users and resumed password/2FA flows. Disabling the
feature also prevents Firebase-backed sessions being used;
existing native Weblate sessions and recovery login are unaffected.

Add the site's hostname to Firebase Authentication's authorized domains. Retain
the existing Firebase auth domain and provider configuration used by CloudPebble.
The page uses Google, Apple, and GitHub through Firebase's popup flow, with the
same pinned browser SDK version as CloudPebble (10.12.2). It does not silently
reuse shared Pebble cookies. Browser credentials are held in memory only and
discarded after obtaining an ID token; Weblate then owns the session.

Run `weblate check`, collect static files, and restart after configuring the
backend. Deploy the wheel containing this module before referencing it in the
settings override. The Docker example wires the helper and environment variables
already; its defaults keep the feature disabled.

## First-time linking

1. Sign in using your existing Weblate login.
2. Open **Settings → Account** (`/accounts/profile/#account`).
3. Under available authentication methods, connect **Pebble account**.
4. Choose the existing Pebble account's Google, Apple, or GitHub sign-in provider.
   Its verified email must match the Weblate account's email.
5. Complete Weblate's password confirmation and any two-factor challenge.
6. Sign out of Weblate, then test **Pebble account** on the login page.

Starting with Pebble login before linking displays instructions to sign in to
Weblate first; it never silently creates a duplicate account or merges users.
The linking flow does not elevate permissions. If two providers have not been
linked in Firebase, use the original Pebble sign-in method.

## Validation

The disposable local integration test exercises real RSA-signed Firebase-format
JWT validation, rejecting forged/expired tokens, wrong projects/issuers,
unverified emails, CSRF/state attacks, and new or duplicate-account
creation. It also exercises native password-confirmed linking, returning login,
disabled accounts, and a native two-factor challenge. It rolls back its fixture
users and makes no Firebase requests or email deliveries:

```sh
docker compose --env-file .env -f examples/docker/compose.yaml exec -T weblate \
  weblate shell < examples/docker/firebase_auth_smoke.py
```

Provider popups and real Google/Apple/GitHub identity exchange still need a manual
end-to-end test with an existing linked account. A production Firebase identity is not
created or impersonated by the automated test.
