from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.contrib.auth import get_user_model
from rest_framework.permissions import IsAuthenticated
from rest_framework.generics import ListCreateAPIView, ListAPIView
from ..serializers import AttendanceSerializer, JustificationSerializer, AttendanceUsersSerializer
from accounts.models import Attendance, Justification, JustificationApproval, CustomUser
from django.utils import timezone
import logging
from ..services import filter_attendances_by_period, group_attendances_by_date, calculate_day_status, calculate_stats, process_face_image_and_get_embedding, find_matching_user, save_attendance_photo

logger = logging.getLogger(__name__)
User = get_user_model()

class MarkAttendanceView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        logger.info(f"Requisição recebida: {request.FILES}, {request.data}, Content-Type: {request.headers.get('Content-Type')}")
        face_image = request.FILES.get('face_image')
        if not face_image or not hasattr(face_image, 'name'):
            logger.error(f"face_image inválido em request.FILES: {request.FILES}")
            return Response({'error': 'Imagem facial inválida ou ausente. Certifique-se do tipo de codificação no formulário.'}, status=status.HTTP_400_BAD_REQUEST)
        point_type = request.data.get('point_type', 'entrada')

        try:
            login_embedding = process_face_image_and_get_embedding(face_image)
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Erro ao processar imagem facial: {str(e)}")
            return Response({'error': f'Erro ao processar imagem facial: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        matched_user, min_distance = find_matching_user(login_embedding, User)

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

            try:
                full_path = save_attendance_photo(face_image)
            except IOError as e:
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
                    'funcao': getattr(matched_user, 'funcao', "") or "",
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

class AttendanceUsersListView(ListCreateAPIView):
    serializer_class = AttendanceUsersSerializer

    def get_queryset(self):
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

            attendances_display = filter_attendances_by_period(user, period)
            attendance_count = attendances_display.count()

            attendance_data = group_attendances_by_date(attendances_display)

            all_attendances = Attendance.objects.filter(user=user).order_by('-data_hora')
            all_attendance_data = group_attendances_by_date(all_attendances)

            justifications = Justification.objects.filter(user=user)
            justification_map = {}
            for j in justifications:
                date_str = j.date.strftime('%d/%m/%Y') if j.date else timezone.now().date().strftime('%d/%m/%Y')
                justification_map[date_str] = j.reason

            stats = calculate_stats(user, all_attendance_data, justifications.count())

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
