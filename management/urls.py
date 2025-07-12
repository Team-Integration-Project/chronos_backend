"""
URL configuration for management project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

from accounts.views import RegisterView, LoginView, MarkAttendanceView, CameraTestView, ForgotPasswordView, ResetPasswordView, UserManagementView, JustificationListCreateView, JustificationDetailView, JustificationApprovalView
from rest_framework_simplejwt.views import TokenRefreshView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/register/', RegisterView.as_view(), name='register'),
    path('api/login/', LoginView.as_view(), name="login"),
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('api/mark-attendance/', MarkAttendanceView.as_view(), name='mark_attendance'),
    path('camera-test/', CameraTestView.as_view(), name='camera_test'),
    path('api/forgot-password/', ForgotPasswordView.as_view(), name='forgot-password'),
    path('api/reset-password/<str:token>/', ResetPasswordView.as_view(), name='reset-password'),
    path('api/users/manage/<int:user_id>/', UserManagementView.as_view(), name='user_management'),
    path('api/justification/', JustificationListCreateView.as_view(), name='list-create-justification'),
    path('api/justification/<int:pk>/', JustificationDetailView.as_view(), name='detail-edit-delete-justification'),
    path('api/justification/<int:justification_id>/approve/', JustificationApprovalView.as_view(), name='approve-justification'),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)