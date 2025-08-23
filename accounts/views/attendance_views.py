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
from collections import defaultdict
from datetime import datetime, timedelta

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
    permission_classes = [IsAuthenticated]
    
    def get(self, request, user_id):
        try:
            user = User.objects.get(id=user_id)
            period = request.query_params.get('period', 'mes').lower()
            
            start_date_str = request.query_params.get('start_date')
            end_date_str = request.query_params.get('end_date')

            start_date = None
            end_date = None

            # Se datas específicas foram fornecidas
            if start_date_str and end_date_str:
                try:
                    start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
                    end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
                except ValueError:
                    return Response({'error': 'Formato de data inválido. Use YYYY-MM-DD.'}, status=status.HTTP_400_BAD_REQUEST)
            
            # Se não há datas específicas, definir baseado no período
            else:
                today = timezone.now().date()
                
                if period == 'hoje':
                    start_date = today
                    end_date = today
                elif period == 'semana':
                    # Início da semana (domingo)
                    days_since_sunday = (today.weekday() + 1) % 7
                    start_date = today - timedelta(days=days_since_sunday)
                    end_date = start_date + timedelta(days=6)
                elif period == 'mes':
                    # Primeiro e último dia do mês atual
                    start_date = today.replace(day=1)
                    if today.month == 12:
                        end_date = today.replace(year=today.year + 1, month=1, day=1) - timedelta(days=1)
                    else:
                        end_date = today.replace(month=today.month + 1, day=1) - timedelta(days=1)
                elif period == 'ano':
                    # Primeiro e último dia do ano atual
                    start_date = today.replace(month=1, day=1)
                    end_date = today.replace(month=12, day=31)
                else:
                    # Default para mês se período inválido
                    start_date = today.replace(day=1)
                    if today.month == 12:
                        end_date = today.replace(year=today.year + 1, month=1, day=1) - timedelta(days=1)
                    else:
                        end_date = today.replace(month=today.month + 1, day=1) - timedelta(days=1)

            logger.info(f"UserAttendanceDetailView: Usuário {user.username}, Período {period}, Data início: {start_date}, Data fim: {end_date}")

            # Filtrar attendances pelo período selecionado
            attendances_display = filter_attendances_by_period(user, period, start_date=start_date, end_date=end_date)
            logger.info(f"UserAttendanceDetailView: Usuário {user.username}, Atendimentos filtrados: {attendances_display.count()}")
            
            attendance_count = attendances_display.count()

            # Agrupar attendances por data para exibição na tabela
            attendance_data = group_attendances_by_date(attendances_display)

            # Preparar atividades recentes para o período selecionado
            recent_activities = defaultdict(list)
            for att in attendances_display:
                date_str = att.data_hora.astimezone(timezone.get_current_timezone()).strftime('%d/%m/%Y')
                recent_activities[date_str].append({
                    'id': att.id,
                    'point_type': att.point_type,
                    'data_hora': att.data_hora.isoformat(),
                    'foto_path': att.foto_path.url if att.foto_path else None,
                })
            
            logger.info(f"UserAttendanceDetailView: `recent_activities` (para exibição na tabela): {dict(recent_activities)}")

            # Para as estatísticas CUMULATIVAS, usar TODOS os attendances do usuário
            all_attendances = Attendance.objects.filter(user=user).order_by('-data_hora')
            all_attendance_data = group_attendances_by_date(all_attendances)

            # Justificativas do usuário
            justifications = Justification.objects.filter(user=user)
            justification_map = {}
            for j in justifications:
                date_str = j.date.strftime('%d/%m/%Y') if j.date else timezone.now().date().strftime('%d/%m/%Y')
                justification_map[date_str] = j.reason

            # Calcular estatísticas cumulativas (todos os registros)
            stats = calculate_stats(user, all_attendance_data, justifications.count(), attendance_count)

            # Adicionar informações adicionais do usuário
            stats['cpf'] = user.cpf if hasattr(user, 'cpf') and user.cpf else 'N/A'
            stats['role'] = user.role if hasattr(user, 'role') and user.role else 'N/A'
            stats['period_start'] = start_date.strftime('%d/%m/%Y') if start_date else None
            stats['period_end'] = end_date.strftime('%d/%m/%Y') if end_date else None

            logger.info(f"UserAttendanceDetailView: Stats calculadas: {stats}")

            return Response({
                'user': user.username,
                'total_attendances': attendance_count,
                'attendances': attendance_data,  # Dados filtrados para a tabela
                'stats': stats,  # Estatísticas cumulativas
                'period_info': {
                    'period': period,
                    'start_date': start_date.strftime('%Y-%m-%d') if start_date else None,
                    'end_date': end_date.strftime('%Y-%m-%d') if end_date else None,
                    'start_date_display': start_date.strftime('%d/%m/%Y') if start_date else None,
                    'end_date_display': end_date.strftime('%d/%m/%Y') if end_date else None,
                }
            }, status=status.HTTP_200_OK)

        except User.DoesNotExist:
            logger.error(f"Usuário com ID {user_id} não encontrado")
            return Response({'error': 'Usuário não encontrado'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Erro ao buscar atendimentos do usuário {user_id}: {str(e)}")
            return Response({'error': f'Erro interno: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class MyAttendanceReportView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            user = request.user
            if not user.is_authenticated:
                return Response({'error': 'Autenticação necessária'}, status=status.HTTP_401_UNAUTHORIZED)

            period = request.query_params.get('period', 'mes').lower()
            
            start_date_str = request.query_params.get('start_date')
            end_date_str = request.query_params.get('end_date')

            start_date = None
            end_date = None

            if start_date_str and end_date_str:
                try:
                    start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
                    end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
                except ValueError:
                    return Response({'error': 'Formato de data inválido. Use YYYY-MM-DD.'}, status=status.HTTP_400_BAD_REQUEST)

            attendances_display = filter_attendances_by_period(user, period, start_date=start_date, end_date=end_date)
            logger.info(f"MyAttendanceReportView: Usuário {user.username}, Período {period}, Atendimentos encontrados: {attendances_display.count()}")
            attendance_count = attendances_display.count()

            attendance_data = group_attendances_by_date(attendances_display) 

            recent_activities = defaultdict(list)
            for att in attendances_display:
                date_str = att.data_hora.astimezone(timezone.get_current_timezone()).strftime('%d/%m/%Y')
                recent_activities[date_str].append({
                    'id': att.id,
                    'point_type': att.point_type,
                    'data_hora': att.data_hora.isoformat(),
                    'foto_path': att.foto_path.url if att.foto_path else None,
                })

            all_attendances = Attendance.objects.filter(user=user).order_by('-data_hora')
            all_attendance_data = group_attendances_by_date(all_attendances)

            justifications = Justification.objects.filter(user=user)
            justification_map = {}
            for j in justifications:
                date_str = j.date.strftime('%d/%m/%Y') if j.date else timezone.now().date().strftime('%d/%m/%Y')
                justification_map[date_str] = j.reason

            stats = calculate_stats(user, all_attendance_data, justifications.count(), attendance_count) 

            stats['cpf'] = user.cpf if user.cpf else 'N/A'
            stats['role'] = user.role if user.role else 'N/A'

            return Response({
                'user': user.username,
                'total_attendances': attendance_count,
                'attendances': attendance_data, 
                'stats': stats
            }, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Erro ao buscar atendimentos do próprio usuário: {str(e)}")
            return Response({'error': 'Erro interno ao buscar relatórios'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

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
            
            start_date_str = request.query_params.get('start_date')
            end_date_str = request.query_params.get('end_date')

            start_date = None
            end_date = None

            if start_date_str and end_date_str:
                try:
                    start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
                    end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
                except ValueError:
                    return Response({'error': 'Formato de data inválido. Use YYYY-MM-DD.'}, status=status.HTTP_400_BAD_REQUEST)

            attendances_display = filter_attendances_by_period(user, period, start_date=start_date, end_date=end_date)
            logger.info(f"UserAttendanceDetailView: Usuário {user.username}, Período {period}, Atendimentos filtrados: {attendances_display.count()}")
            attendance_count = attendances_display.count()

            attendance_data = group_attendances_by_date(attendances_display)

            recent_activities = defaultdict(list)
            for att in attendances_display:
                date_str = att.data_hora.astimezone(timezone.get_current_timezone()).strftime('%d/%m/%Y')
                recent_activities[date_str].append({
                    'id': att.id,
                    'point_type': att.point_type,
                    'data_hora': att.data_hora.isoformat(),
                    'foto_path': att.foto_path.url if att.foto_path else None,
                })
            logger.info(f"UserAttendanceDetailView: `recent_activities` (para exibição na tabela): {recent_activities}")

            all_attendances = Attendance.objects.filter(user=user).order_by('-data_hora')
            all_attendance_data = group_attendances_by_date(all_attendances)

            justifications = Justification.objects.filter(user=user)
            justification_map = {}
            for j in justifications:
                date_str = j.date.strftime('%d/%m/%Y') if j.date else timezone.now().date().strftime('%d/%m/%Y')
                justification_map[date_str] = j.reason

            stats = calculate_stats(user, all_attendance_data, justifications.count(), attendance_count) 

            stats['cpf'] = user.cpf if user.cpf else 'N/A'
            stats['role'] = user.role if user.role else 'N/A'

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

class MyAttendanceReportView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            user = request.user
            if not user.is_authenticated:
                return Response({'error': 'Autenticação necessária'}, status=status.HTTP_401_UNAUTHORIZED)

            period = request.query_params.get('period', 'mes').lower()
            
            start_date_str = request.query_params.get('start_date')
            end_date_str = request.query_params.get('end_date')

            start_date = None
            end_date = None

            if start_date_str and end_date_str:
                try:
                    start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
                    end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
                except ValueError:
                    return Response({'error': 'Formato de data inválido. Use YYYY-MM-DD.'}, status=status.HTTP_400_BAD_REQUEST)

            attendances_display = filter_attendances_by_period(user, period, start_date=start_date, end_date=end_date)
            logger.info(f"MyAttendanceReportView: Usuário {user.username}, Período {period}, Atendimentos encontrados: {attendances_display.count()}")
            attendance_count = attendances_display.count()

            attendance_data = group_attendances_by_date(attendances_display) 

            recent_activities = defaultdict(list)
            for att in attendances_display:
                date_str = att.data_hora.astimezone(timezone.get_current_timezone()).strftime('%d/%m/%Y')
                recent_activities[date_str].append({
                    'id': att.id,
                    'point_type': att.point_type,
                    'data_hora': att.data_hora.isoformat(),
                    'foto_path': att.foto_path.url if att.foto_path else None,
                })

            all_attendances = Attendance.objects.filter(user=user).order_by('-data_hora')
            all_attendance_data = group_attendances_by_date(all_attendances)

            justifications = Justification.objects.filter(user=user)
            justification_map = {}
            for j in justifications:
                date_str = j.date.strftime('%d/%m/%Y') if j.date else timezone.now().date().strftime('%d/%m/%Y')
                justification_map[date_str] = j.reason

            stats = calculate_stats(user, all_attendance_data, justifications.count(), attendance_count) 

            stats['cpf'] = user.cpf if user.cpf else 'N/A'
            stats['role'] = user.role if user.role else 'N/A'

            return Response({
                'user': user.username,
                'total_attendances': attendance_count,
                'attendances': attendance_data, 
                'stats': stats
            }, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Erro ao buscar atendimentos do próprio usuário: {str(e)}")
            return Response({'error': 'Erro interno ao buscar relatórios'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
