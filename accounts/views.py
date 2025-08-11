from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.contrib.auth import authenticate, get_user_model
from rest_framework_simplejwt.tokens import RefreshToken
from .serializers import RegisterSerializer, LoginSerializer, ForgotPasswordSerializer, ResetPasswordSerializer, AttendanceSerializer, JustificationSerializer, JustificationApprovalSerializer, FacialRecognitionFailureSerializer, AttendanceUsersSerializer, UserProfileSerializer
from .models import CustomUser, PasswordResetToken, UserRole, Attendance, Justification, JustificationApproval, FacialRecognitionFailure
from .permission import AdminPermission
import face_recognition
import numpy as np
import logging
import uuid
import os
import re
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.generics import ListCreateAPIView, RetrieveUpdateDestroyAPIView, ListAPIView
from rest_framework.exceptions import PermissionDenied
from django.core.mail import send_mail
from django.utils import timezone
from django.conf import settings
from django.core.files.storage import default_storage
from django.core.exceptions import ObjectDoesNotExist
from PIL import Image
from django.db.models import Max
from collections import defaultdict
from datetime import datetime, timedelta

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

class CameraTestView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return render(request, 'accounts/index.html')

class MarkAttendanceView(APIView):
    permission_classes = [IsAuthenticated]

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
        if matched_user and min_distance < 0.5:
            valid_types = ['entrada', 'almoco', 'saida']
            if point_type not in valid_types:
                return Response({'error': 'Tipo de ponto inválido'}, status=status.HTTP_400_BAD_REQUEST)

            current_date = timezone.now().date()
            logger.info(f"Data atual considerada: {current_date}")
            all_attendances = Attendance.objects.filter(user=matched_user).order_by('data_hora')
            registered_types = [a.point_type for a in all_attendances]
            logger.info(f"Todos os tipos de ponto registrados para {matched_user.username}: {registered_types}")
            next_index = valid_types.index(point_type) if point_type in valid_types else -1
            if next_index > 0 and valid_types[next_index - 1] not in registered_types:
                return Response({'error': f'Primeiro marque {valid_types[next_index - 1]}'}, status=status.HTTP_400_BAD_REQUEST)
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
                    'cpf': matched_user.cpf or "",
                    'funcao': getattr(matched_user, 'funcao', "") or "",  # Ajuste se 'funcao' não estiver no modelo
                    'matricula': getattr(matched_user, 'matricula', "") or "",
                    'empresa': getattr(matched_user, 'empresa', "") or "",
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

class JustificationListCreateView(ListCreateAPIView):
    serializer_class = JustificationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.is_admin:
            return Justification.objects.all().order_by('-created_at')
        return Justification.objects.filter(user=user).order_by('-created_at')

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
    
    def list(self, request, *args, **kwargs):
        """Customizar a resposta da listagem para incluir dados de aprovação"""
        queryset = self.get_queryset()
        
        data = []
        for justification in queryset:
            # Buscar aprovação associada
            approval = JustificationApproval.objects.filter(justification=justification).first()
            
            item = {
                'id': justification.id,
                'user': justification.user.username if justification.user else 'Desconhecido',
                'employee': justification.user.get_full_name() if justification.user else justification.user.username if justification.user else 'Desconhecido',
                'reason': justification.reason or 'Sem motivo',
                'date': justification.date.strftime('%Y-%m-%d') if justification.date else justification.created_at.date().strftime('%Y-%m-%d'),
                'created_at': justification.created_at.isoformat(),
                
                # Campos de aprovação baseados na tabela JustificationApproval
                'approval': approval.approved if approval else None,
                'approved': approval.approved if approval else None,  # Compatibilidade
                'status': self._get_status_text(approval.approved if approval else None),
                'approved_by': approval.reviewed_by.username if approval and approval.reviewed_by else None,
                'approved_at': approval.reviewed_at.isoformat() if approval and approval.reviewed_at else None,
            }
            data.append(item)
            
            # Log para debug
            logger.info(f"Justification {justification.id}: approval={approval.approved if approval else None}, status={item['status']}")
        
        return Response(data, status=status.HTTP_200_OK)
    
    def _get_status_text(self, approval):
        """Converter o campo approval para texto"""
        if approval is True:
            return 'aprovada'
        elif approval is False:
            return 'recusada'
        else:
            return 'pendente'

class JustificationApprovalView(APIView):
    permission_classes = [AdminPermission]

    def post(self, request, justification_id):
        try:
            justification = Justification.objects.get(id=justification_id)
            
            # Pegar o valor de aprovação do request
            approved = request.data.get('approved')
            approval = request.data.get('approval')  # Compatibilidade
            
            # Usar approved se existir, senão usar approval
            final_approval = approved if approved is not None else approval
            
            logger.info(f"Processando aprovação/reprovação para justification {justification_id}: approved={approved}, approval={approval}, final={final_approval}")
            
            if final_approval is None:
                return Response({'error': 'Campo approved ou approval é obrigatório'}, status=status.HTTP_400_BAD_REQUEST)
            
            # Converter string para boolean se necessário
            if isinstance(final_approval, str):
                final_approval_bool = final_approval.lower() in ['true', '1', 'yes']
            else:
                final_approval_bool = bool(final_approval)
            
            # Atualizar ou criar a aprovação
            approval_obj, created = JustificationApproval.objects.update_or_create(
                justification=justification,
                defaults={
                    'approved': final_approval_bool,
                    'reviewed_by': request.user,
                    'reviewed_at': timezone.now()
                }
            )
            
            # Log da operação
            action = "aprovada" if approval_obj.approved else "reprovada"
            status_text = "aprovada" if approval_obj.approved else "recusada"
            logger.info(f"Justificativa {justification_id} {action} por {request.user.username}")
            
            # Retornar dados atualizados no formato esperado pelo frontend
            response_data = {
                'id': justification.id,
                'user': justification.user.username if justification.user else 'Desconhecido',
                'employee': justification.user.get_full_name() if justification.user else justification.user.username if justification.user else 'Desconhecido',
                'reason': justification.reason or 'Sem motivo',
                'date': justification.date.strftime('%Y-%m-%d') if justification.date else justification.created_at.date().strftime('%Y-%m-%d'),
                'created_at': justification.created_at.isoformat(),
                
                # Campos de aprovação padronizados
                'approval': approval_obj.approved,
                'approved': approval_obj.approved,  # Compatibilidade
                'status': status_text,
                'approved_by': approval_obj.reviewed_by.username,
                'approved_at': approval_obj.reviewed_at.isoformat(),
                'message': f'Justificativa {action} com sucesso!'
            }
            
            return Response(response_data, status=status.HTTP_200_OK)
            
        except Justification.DoesNotExist:
            logger.error(f"Justificativa {justification_id} não encontrada")
            return Response({'error': 'Justificativa não encontrada'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Erro ao aprovar/reprovar justificativa {justification_id}: {str(e)}")
            return Response({'error': f'Erro interno: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def _get_status_text(self, approved):
        """Converter o campo approved para texto"""
        if approved is True:
            return 'aprovada'
        elif approved is False:
            return 'recusada'
        else:
            return 'pendente'

# Atualizar também a JustificationListCreateView para garantir consistência
class JustificationListCreateView(ListCreateAPIView):
    serializer_class = JustificationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.is_admin:
            return Justification.objects.all().order_by('-created_at')
        return Justification.objects.filter(user=user).order_by('-created_at')

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
    
    def list(self, request, *args, **kwargs):
        """Customizar a resposta da listagem para incluir dados de aprovação"""
        queryset = self.get_queryset()
        
        data = []
        for justification in queryset:
            # Buscar aprovação associada
            approval = JustificationApproval.objects.filter(justification=justification).first()
            
            # Determinar status baseado na aprovação
            if approval is not None:
                status_text = 'aprovada' if approval.approved else 'recusada'
                approved_status = approval.approved
            else:
                status_text = 'pendente'
                approved_status = None
            
            item = {
                'id': justification.id,
                'user': justification.user.username if justification.user else 'Desconhecido',
                'employee': justification.user.get_full_name() if justification.user else justification.user.username if justification.user else 'Desconhecido',
                'reason': justification.reason or 'Sem motivo',
                'date': justification.date.strftime('%Y-%m-%d') if justification.date else justification.created_at.date().strftime('%Y-%m-%d'),
                'created_at': justification.created_at.isoformat(),
                
                # Campos de aprovação padronizados
                'approval': approved_status,
                'approved': approved_status,  # Compatibilidade
                'status': status_text,
                'approved_by': approval.reviewed_by.username if approval and approval.reviewed_by else None,
                'approved_at': approval.reviewed_at.isoformat() if approval and approval.reviewed_at else None,
            }
            data.append(item)
            
            # Log para debug
            logger.info(f"Justification {justification.id}: approved={approved_status}, status={status_text}")
        
        return Response(data, status=status.HTTP_200_OK)

# Atualizar a JustificationDetailView para DELETE
class JustificationDetailView(RetrieveUpdateDestroyAPIView):
    serializer_class = JustificationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.is_admin:
            return Justification.objects.all()
        return Justification.objects.filter(user=user)

    def perform_update(self, serializer):
        instance = self.get_object()
        if not self.request.user.is_admin and instance.user != self.request.user:
            raise PermissionDenied("Você não tem permissão para editar esta justificativa.")
        serializer.save()

    def perform_destroy(self, instance):
        if not self.request.user.is_admin and instance.user != self.request.user:
            raise PermissionDenied("Você não tem permissão para excluir esta justificativa.")
        
        # Deletar aprovação associada também
        JustificationApproval.objects.filter(justification=instance).delete()
        
        logger.info(f"Justificativa {instance.id} deletada por {self.request.user.username}")
        instance.delete()
    
    def destroy(self, request, *args, **kwargs):
        """Customizar resposta de delete"""
        try:
            instance = self.get_object()
            self.perform_destroy(instance)
            return Response({'message': 'Justificativa deletada com sucesso!'}, status=status.HTTP_204_NO_CONTENT)
        except Exception as e:
            logger.error(f"Erro ao deletar justificativa: {str(e)}")
            return Response({'error': 'Erro interno do servidor'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class FacialFailureView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        reason = request.data.get('reason', '').strip()
        date = request.data.get('date', timezone.now().date().isoformat())

        if not reason or len(reason) < 5:
            return Response({'reason': ['Garantir que este campo tenha no mínimo 5 caracteres.']}, status=status.HTTP_400_BAD_REQUEST)
        try:
            from datetime import datetime
            datetime.strptime(date, '%Y-%m-%d')
        except ValueError:
            return Response({'date': ['Data inválida. Use o formato YYYY-MM-DD.']}, status=status.HTTP_400_BAD_REQUEST)

        failure = FacialRecognitionFailure.objects.create(
            user=request.user,
            reason=reason,
            date=date
        )
        logger.info(f"Justificativa de falha de reconhecimento registrada para {request.user.username}: {reason}")
        return Response({'message': 'Justificativa de falha de reconhecimento registrada com sucesso'}, status=status.HTTP_201_CREATED)

class AttendanceUsersListView(ListCreateAPIView):
    serializer_class = AttendanceUsersSerializer

    def get_queryset(self):
        # Obtém todos os usuários que têm registros em Attendance
        users_with_attendance = CustomUser.objects.filter(attendance__isnull=False).distinct()
        return users_with_attendance

class AttendanceListView(ListAPIView):
    serializer_class = AttendanceSerializer

    def get_queryset(self):
        user = self.request.user
        if user.is_admin:
            return Attendance.objects.all().order_by('-data_hora')
        return Attendance.objects.filter(user=user).order_by('-data_hora')

class UserAttendanceDetailView(APIView):
    def get(self, request, user_id):
        try:
            user = User.objects.get(id=user_id)
            period = request.query_params.get('period', 'mes').lower()

            # Filtro por período APENAS para exibição da tabela
            attendances_display = self._filter_attendances_by_period(user, period)
            attendance_count = attendances_display.count()

            # Agrupar atendimentos por data para exibição
            attendance_data = self._group_attendances_by_date(attendances_display)

            # IMPORTANTE: Buscar TODOS os atendimentos para calcular estatísticas
            all_attendances = Attendance.objects.filter(user=user).order_by('-data_hora')
            all_attendance_data = self._group_attendances_by_date(all_attendances)

            # Buscar justificativas associadas
            justifications = Justification.objects.filter(user=user)
            justification_map = {}
            for j in justifications:
                date_str = j.date.strftime('%d/%m/%Y') if j.date else timezone.now().date().strftime('%d/%m/%Y')
                justification_map[date_str] = j.reason

            # Calcular estatísticas SEMPRE baseado em todos os dados (não no período)
            stats = self._calculate_stats(user, all_attendance_data, period, justification_map, justifications.count())

            return Response({
                'user': user.username,
                'total_attendances': attendance_count,
                'attendances': attendance_data,  # Dados filtrados por período para exibição
                'stats': stats  # Estatísticas baseadas em todos os dados
            }, status=status.HTTP_200_OK)

        except User.DoesNotExist:
            return Response({'error': 'Usuário não encontrado'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Erro ao buscar atendimentos: {str(e)}")
            return Response({'error': 'Erro interno'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def _filter_attendances_by_period(self, user, period):
        """Filtra os atendimentos com base no período especificado."""
        today = timezone.now().date()
        attendances = Attendance.objects.filter(user=user).order_by('-data_hora')

        if period == 'hoje':
            return attendances.filter(data_hora__date=today)
        elif period == 'semana':
            week_start = today - timezone.timedelta(days=today.weekday())
            return attendances.filter(data_hora__date__gte=week_start, data_hora__date__lte=today)
        elif period == 'mes':
            return attendances.filter(data_hora__date__gte=today.replace(day=1))
        elif period == 'ano':
            return attendances.filter(data_hora__year=today.year)
        return attendances

    def _group_attendances_by_date(self, attendances):
        """Agrupar atendimentos por data e mapear para o formato esperado."""
        attendance_dict = defaultdict(list)
        for attendance in attendances:
            date_str = attendance.data_hora.astimezone(timezone.get_current_timezone()).strftime('%d/%m/%Y')
            attendance_dict[date_str].append(attendance)

        attendance_data = []
        for date_str, atts in attendance_dict.items():
            day_data = {'id': str(atts[0].id), 'date': date_str}
            
            # Organizar pontos por tipo
            for att in atts:
                time_str = att.data_hora.astimezone(timezone.get_current_timezone()).strftime('%H:%M')
                if att.point_type == 'entrada':
                    day_data['entrada'] = time_str
                elif att.point_type == 'almoco':
                    day_data['entrada_almoco'] = time_str
                    day_data['saida_almoco'] = time_str  # Simplificado
                elif att.point_type == 'saida':
                    day_data['saida'] = time_str
            
            # Definir valores padrão
            day_data.setdefault('entrada', '-')
            day_data.setdefault('entrada_almoco', '-')
            day_data.setdefault('saida_almoco', '-')
            day_data.setdefault('saida', '-')
            
            # Calcular status do dia
            day_data['status'] = self._calculate_day_status(day_data)
            day_data['observacao'] = ''
            attendance_data.append(day_data)

        return attendance_data

    def _calculate_day_status(self, day_data):
        """Calcula o status de um dia específico baseado nos horários."""
        entrada = day_data.get('entrada', '-')
        saida = day_data.get('saida', '-')
        
        # Se não tem entrada, é falta
        if entrada == '-':
            return 'Falta'
        
        # Se tem entrada mas não tem saída, é pendente
        if saida == '-':
            return 'Pendente'
        
        # Verificar atraso - após 07:00 é considerado atraso
        try:
            entrada_time = datetime.strptime(entrada, '%H:%M').time()
            horario_limite = datetime.strptime('07:00', '%H:%M').time()
            
            # Se entrada for após 07:00, é atraso
            if entrada_time > horario_limite:
                return 'Atraso'
        except ValueError:
            pass
        
        return 'Aprovado'

    def _calculate_stats(self, user, attendance_data, period, justification_map, total_justificativas):
        """Calcula estatísticas baseadas nos atendimentos a partir do primeiro ponto batido."""
        total_hours = 0
        total_faltas = 0
        total_atrasos = 0
        
        # Encontrar a primeira data com ponto batido
        first_attendance_date = None
        if attendance_data:
            # Ordenar por data para encontrar a primeira
            sorted_attendance = sorted(attendance_data, key=lambda x: datetime.strptime(x['date'], '%d/%m/%Y'))
            
            # Encontrar a primeira data com pelo menos um ponto batido
            for day in sorted_attendance:
                if (day.get('entrada', '-') != '-' or 
                    day.get('saida', '-') != '-' or 
                    day.get('entrada_almoco', '-') != '-'):
                    first_attendance_date = datetime.strptime(day['date'], '%d/%m/%Y').date()
                    break
        
        if not first_attendance_date:
            # Se não há pontos batidos, retornar zeros
            return {
                'totalHoras': 0,
                'totalFaltas': 0,
                'totalAtrasos': 0,
                'totalJustificativas': total_justificativas
            }
        
        print(f"Primeira data com ponto batido: {first_attendance_date}")
        
        # Calcular dias úteis a partir da primeira data até hoje
        today = timezone.now().date()
        current_date = first_attendance_date
        dias_uteis_esperados = 0
        
        while current_date <= today:
            # Contar apenas dias úteis (segunda a sexta: 0-4)
            if current_date.weekday() < 5:
                dias_uteis_esperados += 1
            current_date += timezone.timedelta(days=1)
        
        print(f"Dias úteis esperados desde {first_attendance_date}: {dias_uteis_esperados}")
        
        # Contar dias com presença e calcular horas
        dias_com_presenca = 0
        
        for day in attendance_data:
            status = day.get('status', '')
            day_date = datetime.strptime(day['date'], '%d/%m/%Y').date()
            
            # Só considerar dias a partir da primeira data com ponto
            if day_date < first_attendance_date:
                continue
            
            # Só contar dias úteis
            if day_date.weekday() >= 5:  # Sábado (5) ou Domingo (6)
                continue
            
            # Contar faltas e atrasos
            if status == 'Falta':
                total_faltas += 1
            elif status == 'Atraso':
                total_atrasos += 1
            
            # Calcular horas trabalhadas para dias com presença
            if status in ['Aprovado', 'Atraso']:
                dias_com_presenca += 1
                try:
                    if day['entrada'] != '-' and day['saida'] != '-':
                        # Converter horários para objetos datetime
                        entrada_str = day['entrada']
                        saida_str = day['saida']
                        
                        entrada = datetime.strptime(entrada_str, '%H:%M')
                        saida = datetime.strptime(saida_str, '%H:%M')
                        
                        # Tratar casos onde a saída é no dia seguinte (após meia-noite)
                        if saida.time() < entrada.time():
                            saida = saida + timezone.timedelta(days=1)
                        
                        # Calcular intervalo de almoço
                        almoco_duration = timezone.timedelta(hours=0)
                        almoco_in = day.get('entrada_almoco', '-')
                        almoco_out = day.get('saida_almoco', '-')
                        
                        if almoco_in and almoco_in != '-' and almoco_out and almoco_out != '-':
                            try:
                                almoco_in_dt = datetime.strptime(almoco_in, '%H:%M')
                                almoco_out_dt = datetime.strptime(almoco_out, '%H:%M')
                                
                                # Se saída do almoço for menor que entrada, assumir mesmo dia
                                if almoco_out_dt.time() >= almoco_in_dt.time():
                                    almoco_duration = almoco_out_dt - almoco_in_dt
                                else:
                                    # Caso especial: almoço atravessa meia-noite
                                    almoco_out_dt = almoco_out_dt + timezone.timedelta(days=1)
                                    almoco_duration = almoco_out_dt - almoco_in_dt
                            except ValueError:
                                # Se houver erro na conversão, assumir 1 hora de almoço
                                almoco_duration = timezone.timedelta(hours=1)
                        else:
                            # Se não há registro de almoço, assumir 1 hora
                            almoco_duration = timezone.timedelta(hours=1)
                        
                        # Calcular horas trabalhadas (saida - entrada - almoço)
                        work_duration = saida - entrada - almoco_duration
                        
                        # Garantir que não sejam horas negativas
                        if work_duration.total_seconds() > 0:
                            hours_worked = work_duration.total_seconds() / 3600
                            total_hours += hours_worked
                            print(f"Dia {day['date']}: {hours_worked:.2f} horas")
                        else:
                            print(f"Dia {day['date']}: Duração inválida, ignorando")
                            
                except (ValueError, TypeError) as e:
                    print(f"Erro ao calcular horas para o dia {day.get('date', '?')}: {e}")
                    continue
        
        # Calcular faltas: dias úteis esperados - dias com presença
        total_faltas = max(0, dias_uteis_esperados - dias_com_presenca)
        
        print(f"Resumo: {total_hours:.1f}h trabalhadas, {total_faltas} faltas, {total_atrasos} atrasos")

        return {
            'totalHoras': round(total_hours, 1),
            'totalFaltas': total_faltas,
            'totalAtrasos': total_atrasos,
            'totalJustificativas': total_justificativas
        }
    
class UserProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = UserProfileSerializer(request.user)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request):
        user = request.user
        serializer = UserProfileSerializer(user, data=request.data, partial=True) 
        if serializer.is_valid():

            cpf = request.data.get('cpf', '')
            phone_number = request.data.get('phone_number', '')

            if cpf and not re.match(r'^\d{11}$', cpf):
                logger.error(f"CPF inválido para usuário {user.email}: {cpf}")
                return Response(
                    {'cpf': 'CPF deve conter 11 dígitos numéricos.'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            if phone_number and not re.match(r'^\d{10,11}$', phone_number):
                logger.error(f"Telefone inválido para usuário {user.email}: {phone_number}")
                return Response(
                    {'phone_number': 'Telefone deve conter 10 ou 11 dígitos numéricos.'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            serializer.save()
            logger.info(f"Perfil do usuário {user.email} atualizado com sucesso")
            return Response(serializer.data, status=status.HTTP_200_OK)
        logger.error(f"Erro ao atualizar perfil do usuário {user.email}: {serializer.errors}")
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class UserListManageView(APIView):
    permission_classes = [IsAuthenticated, AdminPermission]

    def get(self, request):
        try:
            users = CustomUser.objects.filter(role=UserRole.USER.value)
            serializer = UserProfileSerializer(users, many=True)
            logger.info(f"Lista de usuários comuns retornada para {request.user.email}")
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Erro ao listar usuários comuns: {str(e)}")
            return Response({'error': 'Erro interno ao listar usuários'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def put(self, request, user_id):
        try:
            user = CustomUser.objects.get(id=user_id, role=UserRole.USER.value)
            serializer = UserProfileSerializer(user, data=request.data, partial=True)
            if serializer.is_valid():
                cpf = request.data.get('cpf', '')
                phone_number = request.data.get('phone_number', '')

                if cpf and not re.match(r'^\d{11}$', cpf):
                    logger.error(f"CPF inválido para usuário {user.email}: {cpf}")
                    return Response(
                        {'cpf': 'CPF deve conter 11 dígitos numéricos.'},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                if phone_number and not re.match(r'^\d{10,11}$', phone_number):
                    logger.error(f"Telefone inválido para usuário {user.email}: {phone_number}")
                    return Response(
                        {'phone_number': 'Telefone deve conter 10 ou 11 dígitos numéricos.'},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                serializer.save()
                logger.info(f"Usuário {user.email} editado por {request.user.email}")
                return Response(serializer.data, status=status.HTTP_200_OK)
            logger.error(f"Erro ao editar usuário {user_id}: {serializer.errors}")
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        except CustomUser.DoesNotExist:
            logger.error(f"Usuário com ID {user_id} não encontrado ou não é um usuário comum")
            return Response({'error': 'Usuário não encontrado ou não é um usuário comum'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Erro ao editar usuário {user_id}: {str(e)}")
            return Response({'error': 'Erro interno'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def delete(self, request, user_id):
        try:
            user = CustomUser.objects.get(id=user_id, role=UserRole.USER.value)
            if user.id == request.user.id:
                logger.error(f"Tentativa de excluir a si mesmo por {request.user.email}")
                return Response({'error': 'Não é possível excluir a si mesmo'}, status=status.HTTP_403_FORBIDDEN)
            user_email = user.email
            user.delete()
            logger.info(f"Usuário {user_email} excluído por {request.user.email}")
            return Response({'message': 'Usuário excluído com sucesso'}, status=status.HTTP_200_OK)
        except CustomUser.DoesNotExist:
            logger.error(f"Usuário com ID {user_id} não encontrado ou não é um usuário comum")
            return Response({'error': 'Usuário não encontrado ou não é um usuário comum'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Erro ao excluir usuário {user_id}: {str(e)}")
            return Response({'error': 'Erro interno'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
