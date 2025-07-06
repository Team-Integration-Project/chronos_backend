from rest_framework.permissions import BasePermission
from .models import CustomUser, UserRole

class AdminPermission(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and getattr(request.user, 'role', UserRole.USER.value) == UserRole.ADMIN.value