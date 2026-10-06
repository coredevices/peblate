"""Read-only publication evidence using native API authentication and permissions."""

from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .publication import evidence, pack_inputs
from .weblate_adapter import component


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def release_evidence(request, code):
    owner = component()
    try:
        _, _, translation = pack_inputs(owner, code)
    except ValueError as error:
        raise NotFound(str(error)) from error
    scope = translation or owner
    user = request.user
    if (
        not user.is_active
        or not user.can_access_component(owner)
        or not user.has_perm("translation.download", scope)
    ):
        raise PermissionDenied("Your account cannot download this language.")
    return Response(evidence(owner, code))
