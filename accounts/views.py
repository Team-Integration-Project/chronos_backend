from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.contrib.auth import authenticate, get_user_model
from rest_framework_simplejwt.tokens import RefreshToken
from .serializers import RegisterSerializer, LoginSerializer, ForgotPasswordSerializer, ResetPasswordSerializer
from .models import CustomUser, PasswordResetToken, UserRole
from .permission import AdminPermission
import face_recognition
import numpy as np
import logging
import uuid
from django.core.mail import send_mail
from django.utils import timezone
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist

logger = logging.getLogger(__name__)

class RegisterView(APIView):
    permission_classes = [AdminPermission]

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
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        if serializer.is_valid():
            email = serializer.validated_data['email']
            password = serializer.validated_data['password']
            face_image = serializer.validated_data['face_image']

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

            try:
                image = face_recognition.load_image_file(face_image)
                encodings = face_recognition.face_encodings(image)
                if not encodings:
                    logger.error("Nenhum rosto detectado na imagem de login")
                    return Response({'error': 'Nenhum rosto detectado na imagem'}, status=status.HTTP_400_BAD_REQUEST)
                login_embedding = encodings[0]
                logger.info(f"Embedding de login: {login_embedding.tolist()}")
            except Exception as e:
                logger.error(f"Erro ao processar imagem facial: {str(e)}")
                return Response({'error': 'Erro ao processar imagem facial'}, status=status.HTTP_400_BAD_REQUEST)

            if user.facial_embedding is not None:
                try:
                    db_embedding = np.array(user.facial_embedding)
                    distance = face_recognition.face_distance([db_embedding], login_embedding)[0]
                    logger.info(f"Embedding do banco: {db_embedding.tolist()}")
                    logger.info(f"Distância calculada: {distance}")
                    if distance < 0.4:
                        refresh = RefreshToken.for_user(user)
                        logger.info(f"Login bem-sucedido para {user.username}")
                        return Response({
                            'refresh': str(refresh),
                            'access': str(refresh.access_token),
                            'user': RegisterSerializer(user).data
                        })
                    else:
                        logger.error(f"Rosto não corresponde. Distância: {distance}")
                        return Response({'error': f'Rosto não corresponde. Distância: {distance}'}, status=status.HTTP_401_UNAUTHORIZED)
                except Exception as e:
                    logger.error(f"Erro ao comparar embeddings: {str(e)}")
                    return Response({'error': 'Erro interno ao comparar embeddings'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            else:
                logger.error(f"Nenhum embedding facial registrado para {user.username}")
                return Response({'error': 'Nenhum embedding facial registrado'}, status=status.HTTP_400_BAD_REQUEST)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class MarkAttendanceView(APIView):
    def post(self, request):
        face_image = request.data.get('face_image')
        if not face_image:
            return Response({'error': 'Imagem facial é obrigatória'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            image = face_recognition.load_image_file(face_image)
            encodings = face_recognition.face_encodings(image)
            if not encodings:
                return Response({'error': 'Nenhum rosto detectado na imagem'}, status=status.HTTP_400_BAD_REQUEST)
            login_embedding = encodings[0]
        except Exception as e:
            logger.error(f"Erro ao processar imagem facial: {str(e)}")
            return Response({'error': 'Erro ao processar imagem facial'}, status=status.HTTP_400_BAD_REQUEST)

        User = get_user_model()
        user = None
        min_distance = float('inf')
        matched_user = None

        for u in User.objects.all():
            if u.facial_embedding is not None:
                db_embedding = np.array(u.facial_embedding)
                distance = face_recognition.face_distance([db_embedding], login_embedding)[0]
                if distance < min_distance:
                    min_distance = distance
                    matched_user = u

        if matched_user and min_distance < 0.4:
            attendance_data = {
                'username': matched_user.username,
                'email': matched_user.email,
                'entry_date': timezone.now().date().isoformat(),
                'entry_time': timezone.now().time().isoformat(),
            }
            logger.info(f"Registro de ponto bem-sucedido para {matched_user.username} - Data: {attendance_data['entry_date']} Hora: {attendance_data['entry_time']}")
            return Response(attendance_data, status=status.HTTP_200_OK)
        else:
            logger.error(f"Rosto não corresponde ou nenhum usuário encontrado. Distância: {min_distance}")
            return Response({'error': 'Rosto não corresponde ou nenhum usuário encontrado'}, status=status.HTTP_401_UNAUTHORIZED)

class CameraTestView(APIView):
    def get(self, request):
        return render(request, 'accounts/index.html')

class ForgotPasswordView(APIView):
    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        if serializer.is_valid():
            email = serializer.validated_data['email']
            User = get_user_model()
            try:
                user = User.objects.get(email=email)
            except User.DoesNotExist:
                logger.warning(f"Tentativa de redefinição para email inexistente: {email}")
                return Response({'message': 'Se o email existir, um link será enviado.'}, status=status.HTTP_200_OK)

            token = str(uuid.uuid4())
            PasswordResetToken.objects.update_or_create(
                user=user,
                defaults={'token': token, 'is_used': False, 'created_at': timezone.now()}
            )

            reset_link = f"http://127.0.0.1:8000/api/reset-password/{token}/" 
            subject = 'Redefinição de Senha'
            message = f"Olá {user.username},\n\nClique no link para redefinir sua senha: {reset_link}\n\nEste link expira em 1 hora."
            from_email = settings.DEFAULT_FROM_EMAIL
            try:
                send_mail(subject, message, from_email, [email])
                logger.info(f"Email de redefinição enviado para {email}")
                return Response({'message': 'Se o email existir, um link foi enviado.'}, status=status.HTTP_200_OK)
            except Exception as e:
                logger.error(f"Erro ao enviar email para {email}: {str(e)}")
                return Response({'error': 'Erro ao enviar email'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class ResetPasswordView(APIView):
    def post(self, request, token):
        serializer = ResetPasswordSerializer(data=request.data)
        if serializer.is_valid():
            token_obj = PasswordResetToken.objects.filter(token=token, is_used=False).first()
            if not token_obj or (timezone.now() - token_obj.created_at).total_seconds() > 3600:  
                logger.error(f"Token inválido ou expirado: {token}")
                return Response({'error': 'Token inválido ou expirado'}, status=status.HTTP_400_BAD_REQUEST)

            new_password = serializer.validated_data['new_password']
            user = token_obj.user
            user.set_password(new_password)
            user.save()
            token_obj.is_used = True
            token_obj.save()
            logger.info(f"Senha redefinida para {user.email}")
            return Response({'message': 'Senha redefinida com sucesso'}, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
class UserManagementView(APIView):
    permission_classes = [AdminPermission]

    def put(self, request, user_id):
        try:
            User = get_user_model()
            user = User.objects.get(id=user_id)
            serializer = RegisterSerializer(user, data=request.data, partial=True)
            if serializer.is_valid():
                if 'role' in request.data and request.data['role'] == 'admin' and not request.user.is_admin:
                    return Response({'error': 'Apenas admins podem promover a admin'}, status=status.HTTP_403_FORBIDDEN)
                serializer.save()
                logger.info(f"Usuário {user.email} editado por {request.user.email}")
                return Response(serializer.data, status=status.HTTP_200_OK)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        except ObjectDoesNotExist:
            logger.error(f"Usuário com ID {user_id} não encontrado")
            return Response({'error': 'Usuário não encontrado'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Erro ao editar usuário {user_id}: {str(e)}")
            return Response({'error': 'Erro interno'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def delete(self, request, user_id):
        try:
            User = get_user_model()
            user = User.objects.get(id=user_id)
            if user.id == request.user.id:
                return Response({'error': 'Não é possível excluir a si mesmo'}, status=status.HTTP_403_FORBIDDEN)
            user_email = user.email
            user.delete()
            logger.info(f"Usuário {user_email} excluído por {request.user.email}")
            return Response({'message': 'Usuário excluído com sucesso'}, status=status.HTTP_200_OK)
        except ObjectDoesNotExist:
            logger.error(f"Usuário com ID {user_id} não encontrado")
            return Response({'error': 'Usuário não encontrado'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Erro ao excluir usuário {user_id}: {str(e)}")
            return Response({'error': 'Erro interno'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)