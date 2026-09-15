"""Configure non-admin accounts for the disposable local Peblate demo."""

import json
import secrets
from pathlib import Path

from django.contrib.auth import get_user_model
from weblate.auth.models import Group, Permission, Role
from weblate.lang.models import Language

from peblate.weblate_adapter import component

owner = component()
assert owner.vcs == "local" and owner.repo == "local:", (
    "This setup is only for the disposable demo"
)
with owner.repository.lock:
    assert not owner.repository.execute(["remote"], remote_op="none").strip()
project = owner.project
project.access_control = 100  # Private: grants must come from the scoped demo groups.
project.translation_review = True
project.save(update_fields=["access_control", "translation_review"])
start_role, _ = Role.objects.get_or_create(name="Peblate demo: start languages")
start_role.permissions.set(
    Permission.objects.filter(codename__in=["translation.add", "translation.add_more"])
)
path = Path("/app/data/peblate-demo-accounts.json")
credentials = json.loads(path.read_text()) if path.exists() else {}
roles = {
    "translator": ["Translate", start_role.name],
    "reviewer": ["Translate", "Review strings", start_role.name],
    "viewer": ["Access repository"],
    "french-only": ["Translate"],
    "outsider": [],
}
for label, names in roles.items():
    username = "peblate-" + label
    user, created = get_user_model().objects.get_or_create(
        username=username,
        defaults={
            "email": username + "@localhost.test",
            "full_name": "Peblate test " + label,
        },
    )
    assert not user.is_superuser, "Do not modify an administrator"
    if username not in credentials:
        credentials[username] = secrets.token_urlsafe(18)
    user.set_password(credentials[username])
    user.is_active = True
    user.save()
    if names:
        group, _ = Group.objects.get_or_create(name="Peblate demo: " + label)
        group.project_selection = 0
        group.language_selection = 0 if label == "french-only" else 1
        group.save()
        group.projects.set([project])
        group.components.set([owner])
        group.roles.set(Role.objects.filter(name__in=names))
        group.languages.set(
            [Language.objects.get(code="fr")] if label == "french-only" else []
        )
        user.groups.set([group])
    else:
        user.groups.clear()
path.touch(mode=0o600, exist_ok=True)
path.chmod(0o600)
path.write_text(json.dumps(credentials, indent=2) + "\n")
print(
    "Configured private local demo and non-admin accounts:",
    ", ".join("peblate-" + label for label in roles),
)
print("Passwords are in /app/data/peblate-demo-accounts.json (not printed).")
