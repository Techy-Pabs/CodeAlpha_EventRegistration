from rest_framework.permissions import BasePermission


class IsOrganiser(BasePermission):
    """User has the is_organiser flag (set by an admin)."""

    message = "Only organisers can create events."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_organiser)


class IsEventOrganiser(BasePermission):
    """Object-level: the user organises this particular event."""

    message = "Only this event's organiser can do that."

    def has_object_permission(self, request, view, obj):
        return obj.organiser_id == request.user.id
