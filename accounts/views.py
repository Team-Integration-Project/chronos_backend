from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.contrib.auth import authenticate, get_user_model
from rest_framework_simplejwt.tokens import RefreshToken
from .serializers import RegisterSerializer, LoginSerializer, ForgotPasswordSerializer, ResetPasswordSerializer, AttendanceSerializer, JustificationSerializer
from .models import CustomUser, PasswordResetToken, UserRole, Attendance, Justification
from .permission import AdminPermission
import face_recognition
import numpy as np
import logging
import uuid
import os
from django.core.mail import send_mail
from django.utils import timezone
from django.conf import settings
from django.core.files.storage import default_storage
from django.core.exceptions import ObjectDoesNotExist
from PIL import Image

logger = logging.getLogger(__name__)

class RegisterView(APIView):
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

class CameraTestView(APIView):
    def get(self, request):
        return render(request, 'accounts/index.html')

class MarkAttendanceView(APIView):
    def post(self, request):
        logger.info(f"Requisição recebida: {request.FILES}, {request.data}, Content-Type: {request.headers.get('Content-Type')}")
        face_image = request.FILES.get('face_image')
        if not face_image or not hasattr(face_image, 'name'):
            logger.error(f"face_image inválido em request.FILES: {request.FILES}")
            return Response({'error': 'Imagem facial inválida ou ausente. Certifique-se do tipo de codificação no formulário.'}, status=status.HTTP_400_BAD_REQUEST)
        point_type = request.data.get('point_type', 'entrada')

        # Verificar tipo de arquivo
        allowed_extensions = {'.jpg', '.jpeg', '.png'}
        file_extension = os.path.splitext(face_image.name.lower())[1]
        if file_extension not in allowed_extensions:
            logger.error(f"Extensão de arquivo não suportada: {face_image.name}")
            return Response({'error': 'Formato de imagem não suportado. Use .jpg, .jpeg ou .png'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            # Validar com PIL e verificar se é uma imagem JPEG/PNG
            img = Image.open(face_image)
            img.verify()
            img.close()
            # Forçar leitura como JPEG para evitar problemas com .jpg
            image = face_recognition.load_image_file(face_image, mode='RGB')
            logger.info(f"Processando imagem: {face_image.name}, tamanho: {face_image.size} bytes")
            encodings = face_recognition.face_encodings(image)
            logger.info(f"Número de faces detectadas: {len(encodings)}")
            if not encodings:
                justification_data = {
                    'user': None,
                    'reason': 'Nenhum rosto detectado na imagem',
                    'date': timezone.now().date()
                }
                justification_serializer = JustificationSerializer(data=justification_data)
                if justification_serializer.is_valid():
                    justification_serializer.save()
                return Response({'error': 'Nenhum rosto detectado na imagem'}, status=status.HTTP_400_BAD_REQUEST)
            login_embedding = encodings[0]
        except Exception as e:
            logger.error(f"Erro ao processar imagem facial: {str(e)}")
            return Response({'error': f'Erro ao processar imagem facial: {str(e)}'}, status=status.HTTP_400_BAD_REQUEST)

        User = get_user_model()
        user = None
        min_distance = float('inf')
        matched_user = None

        for u in User.objects.all():
            if u.facial_embedding is not None:
                db_embedding = np.array(u.facial_embedding)
                distance = face_recognition.face_distance([db_embedding], login_embedding)[0]
                logger.info(f"Comparando com usuário {u.username}, distância: {distance}")
                if distance < min_distance:
                    min_distance = distance
                    matched_user = u

        logger.info(f"Mínima distância encontrada: {min_distance}, usuário correspondente: {matched_user.username if matched_user else 'Nenhum'}")
        if matched_user and min_distance < 0.4:
            valid_types = ['entrada', 'almoco', 'saida']
            if point_type not in valid_types:
                return Response({'error': 'Tipo de ponto inválido'}, status=status.HTTP_400_BAD_REQUEST)

            current_date = timezone.now().date()
            logger.info(f"Data atual considerada: {current_date}")
            # Verificar todos os registros anteriores do usuário, não apenas do dia atual
            all_attendances = Attendance.objects.filter(user=matched_user).order_by('data_hora')
            registered_types = [a.point_type for a in all_attendances]
            logger.info(f"Todos os tipos de ponto registrados para {matched_user.username}: {registered_types}")
            # Verificar sequência com base nos registros anteriores
            next_index = valid_types.index(point_type) if point_type in valid_types else -1
            if next_index > 0 and valid_types[next_index - 1] not in registered_types:
                return Response({'error': f'Primeiro marque {valid_types[next_index - 1]}'}, status=status.HTTP_400_BAD_REQUEST)
            # Verificar duplicatas apenas no dia atual
            if Attendance.objects.filter(user=matched_user, point_type=point_type, data_hora__date=current_date).exists():
                return Response({'error': 'Tipo de ponto já registrado hoje'}, status=status.HTTP_400_BAD_REQUEST)

            file_path = f"attendance/photos/{timezone.now().strftime('%Y%m%d_%H%M%S')}_{face_image.name}"
            try:
                default_storage.save(file_path, face_image)
                logger.info(f"Arquivo salvo em: {file_path}")
                full_path = default_storage.url(file_path)
            except Exception as e:
                logger.error(f"Erro ao salvar arquivo: {str(e)}")
                return Response({'error': 'Erro ao salvar imagem'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            attendance_data = {
                'user': matched_user.id,
                'point_type': point_type,
                'foto_path': full_path,
                'data_hora': timezone.now(),
                'is_synced': False,
            }
            serializer = AttendanceSerializer(data=attendance_data)
            if serializer.is_valid():
                serializer.save()
                logger.info(f"Registro de ponto bem-sucedido para {matched_user.username} - Tipo: {point_type}")
                last_records = Attendance.objects.filter(user=matched_user).order_by('-data_hora')[:3]
                response_data = {
                    'full_name': f"{matched_user.first_name or ''} {matched_user.last_name or ''}".strip() or matched_user.username,
                    'date': attendance_data['data_hora'].date().isoformat(),
                    'last_records': AttendanceSerializer(last_records, many=True).data
                }
                logger.info(f"Resposta enviada: {response_data}")
                return Response(response_data, status=status.HTTP_200_OK)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        else:
            justification_data = {
                'user': matched_user.id if matched_user else None,
                'reason': f"Falha no reconhecimento. Distância: {min_distance}",
                'date': timezone.now().date()
            }
            justification_serializer = JustificationSerializer(data=justification_data)
            if justification_serializer.is_valid():
                justification_serializer.save()
            logger.error(f"Falha no reconhecimento para usuário. Distância: {min_distance}")
            return Response({'error': 'Rosto não corresponde ou nenhum usuário encontrado'}, status=status.HTTP_401_UNAUTHORIZED)

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