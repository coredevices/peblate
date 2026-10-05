# Pebble Accounts login and signup

Peblate integrates Firebase with Weblate's native social-auth pipeline. New
Weblate accounts can be created **only through a verified Pebble Account**.
Existing Weblate accounts retain their IDs, roles, contribution history,
password confirmation, two-factor authentication, and audit entries. Native
password login and recovery remain available for those accounts.

The main sign-in page offers only the Pebble providers. **Existing sign-in**
opens the separate username/password form at `/accounts/login/existing/`, with
native password recovery and two-factor authentication. Refreshing or opening
the Pebble provider URL directly restarts through the protected sign-in entry.

## Configuration and launch

Call this helper at the end of the Weblate settings override:

```python
from peblate.auth_settings import configure_pebble_auth

configure_pebble_auth(globals())
```

Supply the existing Firebase web configuration:

```dotenv
PEBLATE_FIREBASE_ENABLED=1
PEBLATE_FIREBASE_PROJECT_ID=coreapp-ce061
PEBLATE_FIREBASE_AUTH_DOMAIN=coreapp-ce061.firebaseapp.com
PEBLATE_FIREBASE_API_KEY=<existing Pebble Firebase web API key>
WEBLATE_REGISTRATION_OPEN=0
```

Authentication is disabled by default. Registration stays closed with
`WEBLATE_REGISTRATION_OPEN=0`, including for new Pebble identities. When ready
for public signup, set **`WEBLATE_REGISTRATION_OPEN=1`**. The helper forces
`REGISTRATION_ALLOW_BACKENDS = ("pebble",)` and adds a server-side creation guard.
Email/password registration, alternate authentication backends, invitation
sessions and password-reset actions cannot create new accounts. The registration
page directs users to Pebble Accounts and rejects email-form submissions.

Firebase's verified email is used for the new Weblate profile; it does not need
a second email-verification round trip. Native account creation assigns the
normal default teams and no usable local password. It grants no administrator
or reviewer role. Project visibility and contributor permissions are separate
settings; making signup available does not make a private project public.

The Firebase API key and project ID are public browser configuration. Verification
uses Google's public signing certificates; no admin private key or shared SSO
cookie secret is needed. The obsolete `PEBLATE_FIREBASE_TEST_EMAILS` setting is
ignored. Add the site's hostname to Firebase Authentication's authorized domains.

The page offers Google, Apple and GitHub through the same Firebase project and
pinned browser SDK as CloudPebble (10.12.2). It does not silently reuse shared
Pebble cookies. Browser credentials are held in memory and discarded after
obtaining an ID token; Weblate then owns the session.

Deploy the updated Peblate wheel, collect static files, run `weblate check` and
restart before opening signup. The previous image cannot create new Pebble-backed
accounts. Deploy this update while registration is closed, then enable it when
ready. No production signup setting is changed by installing the wheel alone.

## Existing accounts: first-time linking

A Pebble identity with the email of an existing Weblate user cannot create a
duplicate account or automatically take over that account. Instead:

1. Sign in using the existing Weblate login.
2. Open **Settings → Account** (`/accounts/profile/#account`).
3. Connect **Pebble account** using its Google, Apple or GitHub provider.
4. The verified Pebble email must match the Weblate account's email.
5. Complete Weblate's password confirmation and any two-factor challenge.
6. Sign out and test Pebble login.

New users who sign up through Pebble Accounts are linked immediately. Returning
users authenticate by the stable Firebase UID. Unverified emails, invalid or
expired tokens and inactive Weblate users are rejected. Disabling the Firebase
feature also invalidates Firebase-backed sessions; existing native sessions and
recovery login remain available.

## Validation

The disposable local integration test validates real RSA-signed Firebase-format
JWTs using test certificates. It exercises closed registration, Pebble-only
account creation, returning login, rejected email-form signup, the global
creation guard, existing-email collisions, explicit password-confirmed linking,
CSRF/state protection, rejected tokens, inactive accounts and native 2FA. Its
users are rolled back and it makes no Firebase requests or email deliveries:

```sh
docker compose --env-file .env -f examples/docker/compose.yaml exec -T weblate \
  weblate shell < examples/docker/firebase_auth_smoke.py
```

Real Google/Apple/GitHub popups and first signup still need a manual end-to-end
test before announcing public access. The automated test neither creates nor
impersonates any production Firebase identity.
