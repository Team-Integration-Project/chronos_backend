from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.contrib.auth import authenticate, get_user_model
from rest_framework_simplejwt.tokens import RefreshToken
from ..serializers import RegisterSerializer, LoginSerializer, ForgotPasswordSerializer, ResetPasswordSerializer
from ..models import CustomUser, PasswordResetToken, UserRole
import random
from rest_framework.permissions import AllowAny
from django.core.mail import send_mail
from django.utils import timezone
from django.conf import settings
import logging

logger = logging.getLogger(__name__)
User = get_user_model()

class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        if serializer.is_valid():
            try:
                role_param = request.data.get('role', request.query_params.get('role', 'user')).lower()
                role = UserRole.ADMIN.value if role_param == 'admin' else UserRole.USER.value
                user = serializer.save()
                user.role = role
                user.save()
                refresh = RefreshToken.for_user(user)
                return Response({
                    'refresh': str(refresh),
                    'access': str(refresh.access_token),
                    'user': RegisterSerializer(user).data
                }, status=status.HTTP_201_CREATED)
            except Exception as e:
                logger.error(f"Erro ao registrar usuário: {str(e)}")
                return Response({'error': 'Erro interno ao registrar'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        if serializer.is_valid():
            email = serializer.validated_data['email']
            password = serializer.validated_data['password']

            User = get_user_model()
            user = None
            try:
                user = User.objects.get(email=email)
                if not user.check_password(password):
                    user = None
            except User.DoesNotExist:
                pass

            if not user:
                logger.error(f"Autenticação falhou. Email: {email}, Password: {password}")
                return Response({'error': 'Credenciais inválidas'}, status=status.HTTP_401_UNAUTHORIZED)
            
            refresh = RefreshToken.for_user(user)
            return Response({
                'refresh': str(refresh),
                'access': str(refresh.access_token),
                'user': RegisterSerializer(user).data
            }, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class ForgotPasswordView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        if serializer.is_valid():
            email = serializer.validated_data['email']
            try:
                user = User.objects.get(email=email)
            except User.DoesNotExist:
                return Response({'message': 'Se o email existir, um código será enviado.'}, status=status.HTTP_200_OK)

            otp_code = str(random.randint(100000, 999999))

            PasswordResetToken.objects.update_or_create(
                user=user,
                defaults={
                    'token': otp_code,
                    'is_used': False,
                    'created_at': timezone.now()
                }
            )
            subject = 'Código de Redefinição de Senha'
            message = f"Olá {user.username},\n\nSeu código de redefinição de senha é: {otp_code}\nEle expira em 10 minutos."
            send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [email])

            return Response({'message': 'Se o email existir, um código foi enviado.'}, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class VerifyResetCodeView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        code = request.data.get('code')
        email = request.data.get('email')

        if not code or not email:
            return Response({'error': 'Código e email são obrigatórios'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = User.objects.get(email=email)
            token_obj = PasswordResetToken.objects.filter(user=user, token=code, is_used=False).first()

            if not token_obj:
                return Response({'error': 'Código inválido'}, status=status.HTTP_400_BAD_REQUEST)

            if (timezone.now() - token_obj.created_at).total_seconds() > 600:
                return Response({'error': 'Código expirado'}, status=status.HTTP_400_BAD_REQUEST)

            return Response({'message': 'Código válido'}, status=status.HTTP_200_OK)

        except User.DoesNotExist:
            return Response({'error': 'Código inválido'}, status=status.HTTP_400_BAD_REQUEST)

class ResetPasswordView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get('email')
        code = request.data.get('code')
        password = request.data.get('new_password')

        if not email or not code or not password:
            return Response({'error': 'Email, código e nova senha são obrigatórios'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = User.objects.get(email=email)
            token_obj = PasswordResetToken.objects.filter(user=user, token=code, is_used=False).first()

            if not token_obj:
                return Response({'error': 'Código inválido'}, status=status.HTTP_400_BAD_REQUEST)

            if (timezone.now() - token_obj.created_at).total_seconds() > 600:
                return Response({'error': 'Código expirado'}, status=status.HTTP_400_BAD_REQUEST)

            user.set_password(password)
            user.save()

            token_obj.is_used = True
            token_obj.save()

            return Response({'message': 'Senha redefinida com sucesso'}, status=status.HTTP_200_OK)

        except User.DoesNotExist:
            return Response({'error': 'Código inválido'}, status=status.HTTP_400_BAD_REQUEST)
