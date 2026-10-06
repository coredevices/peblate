"""Weblate is the authority for reviewers, font decisions and publication settings."""

import re
from pathlib import Path

import polib
from pebble_language_tools.release_packs import completion
from pebble_language_tools.release_policy import font_inputs
from weblate.auth.data import SELECTION_MANUAL
from weblate.auth.models import TeamMembership
from weblate.formats.exporters import PoExporter
from weblate.trans.models.project import CommitPolicyChoices
from weblate.utils.state import STATE_APPROVED

from .models import FontApproval, PublicationSettings
from .weblate_adapter import component_store


def is_maintainer(user, owner):
    return bool(
        user.is_authenticated
        and user.is_active
        and user.can_access_component(owner)
        and user.has_perm("project.edit", owner.project)
    )


def pack_inputs(owner, locale):
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_@.-]*", locale):
        raise ValueError("Invalid language pack")
    store = component_store(owner)
    translations = owner.translation_set.select_related("language").all()
    translation = next(
        (
            item
            for item in translations
            if Path(item.get_filename()).parent.name == locale and not item.is_source
        ),
        None,
    )
    if translation:
        catalog = Path(translation.get_filename()).relative_to(store.root)
    elif re.match(r"(?i)^en[_@-]", locale):
        catalog = Path(locale) / "tintin.po"
    else:
        raise ValueError("This language has no Weblate translation")
    if not store.path(catalog).is_file():
        raise ValueError("Language catalog is missing")
    return store, catalog, translation


def reviewers_for(translation):
    """Use explicit native project/language review teams or membership limits.

    A project administrator's broad review permission is not a claim to speak
    every language. The native permission check also enforces access and account
    verification and rejects revoked or blocked reviewers.
    """
    owner = translation.component
    memberships = (
        TeamMembership.objects.filter(
            user__is_active=True, group__roles__permissions__codename="unit.review"
        )
        .select_related("user", "group")
        .prefetch_related(
            "group__projects",
            "group__components",
            "group__languages",
            "limit_languages",
        )
        .distinct()
    )
    names = set()
    for membership in memberships:
        group = membership.group
        if owner.project_id not in {p.pk for p in group.projects.all()}:
            continue
        components = {c.pk for c in group.components.all()}
        if components and owner.pk not in components:
            continue
        limits = {language.pk for language in membership.limit_languages.all()}
        if limits:
            scoped = translation.language_id in limits
        else:
            scoped = (
                group.language_selection == SELECTION_MANUAL
                and translation.language_id
                in {language.pk for language in group.languages.all()}
            )
        if scoped and membership.user.has_perm("unit.review", translation):
            names.add(membership.user.username)
    return sorted(names)


def font_approval(owner, locale, current_hash):
    approval = (
        FontApproval.objects.select_related("approved_by")
        .filter(component=owner, locale=locale)
        .first()
    )
    if (
        not approval
        or not approval.approved_by
        or not is_maintainer(approval.approved_by, owner)
        or approval.input_hash != current_hash
    ):
        return None
    return {
        "approvedBy": approval.approved_by.username,
        "approvedAt": approval.approved_at.isoformat(),
        "inputHash": approval.input_hash,
        "redistributionConfirmed": True,
        "renderingReviewed": True,
        "note": approval.note,
        "acceptedMissingCharacters": approval.accepted_missing_characters,
        "unknownBaselineAccepted": approval.unknown_baseline_accepted,
    }


def evidence(owner, locale):
    store, catalog_path, translation = pack_inputs(owner, locale)
    settings = PublicationSettings.objects.filter(component=owner).first()
    with store.lock:
        mapping = store.mapping(catalog_path, locale)
        try:
            current_hash = font_inputs(store.path(catalog_path.parent), mapping)
        except (ValueError, OSError, KeyError):
            current_hash = None
        approval = font_approval(owner, locale, current_hash)
    native_reviews = owner.project.translation_review
    if translation:
        native_reviews = translation.enable_review
        exporter = PoExporter(translation=translation)
        exporter.add_units(
            translation.unit_set.filter(state=STATE_APPROVED)
            .prefetch_full()
            .order_by("position")
        )
        catalog = polib.pofile(exporter.serialize().decode("utf-8"))
        catalog.metadata["Language"] = translation.language.code
    else:
        catalog = polib.POFile()
    progress = {"translatedStrings": 0, "totalStrings": 0}
    if translation:
        source = PoExporter(translation=owner.source_translation)
        source.add_units(
            owner.source_translation.unit_set.prefetch_full().order_by("position")
        )
        progress = completion(catalog, polib.pofile(source.serialize().decode("utf-8")))
    saved = FontApproval.objects.filter(component=owner, locale=locale).first()
    return {
        "schemaVersion": 2,
        "component": owner.full_slug,
        "locale": locale,
        "kind": "translation" if translation else "font-only",
        "language": translation.language.code if translation else None,
        "coverageLanguage": saved.coverage_language if saved else None,
        "publicationEnabled": bool(settings and settings.enabled),
        "minimumApprovedPercent": settings.minimum_approved_percent if settings else 80,
        "reviewEnabled": bool(native_reviews),
        "approvedOnlyCommits": owner.project.commit_policy
        == CommitPolicyChoices.APPROVED_ONLY,
        "reviewers": reviewers_for(translation) if translation else [],
        "fontApproval": approval,
        "catalog": str(catalog),
        "approvedStrings": progress["translatedStrings"],
        "totalStrings": progress["totalStrings"],
        "approvedPercent": progress["translatedStrings"]
        * 100
        // progress["totalStrings"]
        if progress["totalStrings"]
        else 0,
    }


def pack_locales(owner):
    store = component_store(owner)
    return sorted(
        {
            Path(t.get_filename()).parent.name
            for t in owner.translation_set.all()
            if not t.is_source
        }
        | {p.parent.name for p in store.root.glob("en_*/tintin.po")}
    )
