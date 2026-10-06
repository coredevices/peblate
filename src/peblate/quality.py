"""Native quality settings used by the Weblate publication page."""

from weblate.trans.models.project import CommitPolicyChoices

GLOSSARY_TERMS = (
    (
        "Timeline",
        "Pebble feature name. Use the same term in settings, notifications and help.",
    ),
    ("Quick View", "Pebble feature name. Keep it distinct from Quick Launch."),
    ("watchface", "The clock-screen design shown by the watch."),
)


def merge_flags(existing, *flags):
    keys = {flag.split(":", 1)[0] for flag in flags}
    return ", ".join(
        dict.fromkeys(
            [
                item.strip()
                for item in existing.split(",")
                if item.strip() and item.strip().split(":", 1)[0] not in keys
            ]
            + list(flags)
        )
    )


def configure(owner, user):
    if not user.is_active or not user.has_perm("project.edit", owner.project):
        raise PermissionError("Project management permission is required")
    project = owner.project
    project.translation_review = True
    project.commit_policy = CommitPolicyChoices.APPROVED_ONLY
    project.save(update_fields=["translation_review", "commit_policy"])
    check_flags = merge_flags(owner.check_flags, "check-glossary")
    if owner.check_flags != check_flags:
        owner.check_flags = check_flags
        owner.save(update_fields=["check_flags"])
    glossaries = [
        item
        for item in project.glossaries
        if item.source_language_id == owner.source_language_id
    ]
    if not glossaries:
        glossary = project.scratch_create_component(
            "Pebble glossary",
            "pebble-glossary",
            owner.source_language,
            "tbx",
            is_glossary=True,
            has_template=False,
            allow_translation_propagation=False,
            license=owner.effective_license,
        )
        for source, note in GLOSSARY_TERMS:
            glossary.source_translation.add_unit(
                None,
                context="",
                source=source,
                target=source,
                explanation=note,
                author=user,
                skip_existing=True,
            )
    owner.schedule_update_checks(update_state=True)
