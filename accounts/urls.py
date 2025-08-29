from django.urls import path, include
from accounts.views.auth_views import RegisterView, LoginView, ForgotPasswordView, ResetPasswordView, VerifyResetCodeView
from accounts.views.user_views import UserManagementView, UserProfileView, UserListManageView
from accounts.views.attendance_views import MarkAttendanceView, AttendanceUsersListView, AttendanceListView, UserAttendanceDetailView
from accounts.views.justification_views import JustificationListCreateView, JustificationDetailView, JustificationApprovalView
from accounts.views.facial_recognition_views import FacialFailureView
from rest_framework_simplejwt.views import TokenRefreshView
from accounts.views.attendance_views import MyAttendanceReportView

urlpatterns = [
    path('register/', RegisterView.as_view(), name='register'),
    path('login/', LoginView.as_view(), name="login"),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('mark-attendance/', MarkAttendanceView.as_view(), name='mark_attendance'),
    path('forgot-password/', ForgotPasswordView.as_view(), name='forgot-password'),
    path('verify-reset-code/', VerifyResetCodeView.as_view(), name='verify-reset-code'),  
    path('reset-password/', ResetPasswordView.as_view(), name='reset-password'),
    path('users/manage/<int:user_id>/', UserManagementView.as_view(), name='user_management'),
    path('justification/', JustificationListCreateView.as_view(), name='list-create-justification'),
    path('justification/<int:pk>/', JustificationDetailView.as_view(), name='detail-edit-delete-justification'),
    path('justification/<int:justification_id>/approve/', JustificationApprovalView.as_view(), name='approve-justification'),
    path('facial-failures/', FacialFailureView.as_view(), name='create_facial_failure'),
    path('users-with-attendance/', AttendanceUsersListView.as_view(), name='users_with_attendance'),
    path('attendance/', AttendanceListView.as_view(), name='attendance_list'),
    path('attendance/<int:user_id>/', UserAttendanceDetailView.as_view(), name='user_attendance_detail'),
    path('attendance/me/', MyAttendanceReportView.as_view(), name='my_attendance_report'),
    path('profile/', UserProfileView.as_view(), name='user-profile'),
    path('list-manage/', UserListManageView.as_view(), name='user_list_manage'),
    path('list-manage/<int:user_id>/', UserListManageView.as_view(), name='user_list_manage_detail'),
]
