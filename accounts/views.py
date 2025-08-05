from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.contrib.auth import authenticate, get_user_model
from rest_framework_simplejwt.tokens import RefreshToken
from .serializers import RegisterSerializer, LoginSerializer, ForgotPasswordSerializer, ResetPasswordSerializer, AttendanceSerializer, JustificationSerializer, JustificationApprovalSerializer, FacialRecognitionFailureSerializer, AttendanceUsersSerializer
from .models import CustomUser, PasswordResetToken, UserRole, Attendance, Justification, JustificationApproval, FacialRecognitionFailure
from .permission import AdminPermission
import face_recognition
import numpy as np
import logging
import uuid
import os
from rest_framework.permissions import IsAuthenticated
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
        instance.delete()

class JustificationApprovalView(APIView):
    permission_classes = [AdminPermission]

    def post(self, request, justification_id):
        try:
            justification = Justification.objects.get(id=justification_id)
            approved = request.data.get('approved')

            if approved not in [True, False, 'true', 'false', 'True', 'False', 1, 0, '1', '0']:
                return Response({'error': 'Campo "approved" deve ser true ou false'}, status=status.HTTP_400_BAD_REQUEST)

            approved_bool = str(approved).lower() in ['true', '1']

            approval, created = JustificationApproval.objects.update_or_create(
                justification=justification,
                defaults={
                    'approved': approved_bool,
                    'reviewed_by': request.user,
                    'reviewed_at': timezone.now()
                }
            )

            serializer = JustificationApprovalSerializer(approval)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Justification.DoesNotExist:
            return Response({'error': 'Justificativa não encontrada'}, status=status.HTTP_404_NOT_FOUND)

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

            # Filtro por período
            attendances = self._filter_attendances_by_period(user, period)
            attendance_count = attendances.count()

            # Agrupar atendimentos por data
            attendance_data = self._group_attendances_by_date(attendances)

            # Calcular estatísticas
            stats = self._calculate_stats(attendance_data)

            return Response({
                'user': user.username,
                'total_attendances': attendance_count,
                'attendances': attendance_data,
                'stats': stats
            }, status=status.HTTP_200_OK)

        except User.DoesNotExist:
            return Response({'error': 'Usuário não encontrado'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Erro ao buscar atendimentos: {str(e)}")
            return Response({'error': 'Erro interno'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def _filter_attendances_by_period(self, user, period):
        """Filtra os atendimentos com base no período especificado."""
        today = timezone.now().date()  # Ajustado para fuso de Brasília
        attendances = Attendance.objects.filter(user=user).order_by('-data_hora')

        if period == 'hoje':
            return attendances.filter(data_hora__date=today)
        elif period == 'semana':
            week_start = today - timezone.timedelta(days=today.weekday())
            return attendances.filter(data_hora__date__gte=week_start, data_hora__date__lte=today)
        elif period == 'mes':
            return attendances.filter(data_hora__month=today.month, data_hora__year=today.year)
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
            # Mapear horários com base em point_type
            for att in atts:
                time_str = att.data_hora.astimezone(timezone.get_current_timezone()).strftime('%H:%M')
                if att.point_type == 'entrada':
                    day_data['entrada'] = time_str
                elif att.point_type == 'almoco':
                    day_data['entrada_almoco'] = time_str
                    day_data['saida_almoco'] = time_str  # Simplificado, ajuste se houver saída de almoço separada
                elif att.point_type == 'saida':
                    day_data['saida'] = time_str
            # Preencher campos ausentes com '-'
            day_data.setdefault('entrada', '-')
            day_data.setdefault('entrada_almoco', '-')
            day_data.setdefault('saida_almoco', '-')
            day_data.setdefault('saida', '-')
            day_data['status'] = 'Aprovado'  # Ajuste conforme lógica de status
            day_data['observacao'] = ''
            attendance_data.append(day_data)

        return attendance_data

    def _calculate_stats(self, attendance_data):
        """Calcula estatísticas baseadas nos atendimentos, focando em horas."""
        total_hours = 0
        for day in attendance_data:
            try:
                if day['entrada'] != '-' and day['saida'] != '-':
                    # Converter horários para objetos datetime
                    entrada = datetime.strptime(day['entrada'], '%H:%M')
                    saida = datetime.strptime(day['saida'], '%H:%M')
                    # Ajustar para o mesmo dia com fuso de Brasília
                    today_br = timezone.now().date()
                    entrada = entrada.replace(year=today_br.year, month=today_br.month, day=today_br.day)
                    saida = saida.replace(year=today_br.year, month=today_br.month, day=today_br.day)

                    # Calcular intervalo de almoço, se existir
                    almoco_in = day['entrada_almoco'] if day['entrada_almoco'] != '-' else None
                    almoco_out = day['saida_almoco'] if day['saida_almoco'] != '-' else None
                    almoco_duration = timedelta(hours=0)
                    if almoco_in and almoco_out:
                        almoco_in_dt = datetime.strptime(almoco_in, '%H:%M').replace(year=today_br.year, month=today_br.month, day=today_br.day)
                        almoco_out_dt = datetime.strptime(almoco_out, '%H:%M').replace(year=today_br.year, month=today_br.month, day=today_br.day)
                        almoco_duration = almoco_out_dt - almoco_in_dt

                    # Calcular horas trabalhadas (saida - entrada - intervalo de almoço)
                    work_duration = saida - entrada - almoco_duration
                    total_hours += work_duration.total_seconds() / 3600  # Converter para horas
            except ValueError:
                continue  # Ignorar se os horários forem inválidos

        return {
            'total_horas': round(total_hours, 2),  # Arredondar pra 2 casas decimais
            'total_faltas': 0,  # Temporariamente zerado
            'total_atrasos': 0,  # Temporariamente zerado
            'total_justificativas': 0  # Temporariamente zerado
        }