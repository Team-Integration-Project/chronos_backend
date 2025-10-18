from django.utils import timezone
from collections import defaultdict
from datetime import datetime, timedelta, date
from accounts.models import Attendance, Justification, JustificationApproval, Feriado
import face_recognition
import numpy as np
import logging
from PIL import Image
import os
from django.core.files.storage import default_storage


logger = logging.getLogger(__name__)

def filter_attendances_by_period(user, period, start_date=None, end_date=None):
    today = timezone.now().date()
    attendances = Attendance.objects.filter(user=user).order_by('-data_hora')

    if start_date and end_date:
        return attendances.filter(data_hora__date__gte=start_date, data_hora__date__lte=end_date)

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

def calculate_day_status(colaborador, data: date) -> dict:
    """
    Calcula o status de presença para um colaborador em uma data específica.
    Retorna: dict com 'status' (presente, justificado, falta, feriado_domingo) e 'display' (com emoji/capitalizado).
    """
    # Passo 1: Verificar se é domingo ou feriado
    if data.weekday() == 6:  # 6 = Domingo
        return {'status': 'feriado_domingo', 'display': '⚪ Feriado/Domingo'}
    
    if Feriado.objects.filter(data=data).exists():
        return {'status': 'feriado_domingo', 'display': '⚪ Feriado/Domingo'}
    
    # Passo 2: Verificar se há registro de ponto (qualquer tipo: entrada, almoço, saída)
    if Attendance.objects.filter(user=colaborador, data_hora__date=data).exists():
        return {'status': 'presente', 'display': '🟢 Presente'}
    
    # Passo 3: Verificar se há justificativa aprovada para o dia
    justificativa = Justification.objects.filter(
        user=colaborador,
        date=data
    ).first()
    if justificativa and JustificationApproval.objects.filter(
        justification=justificativa,
        approved=True
    ).exists():
        return {'status': 'justificado', 'display': '🟡 Justificado'}
    
    # Passo 4: Caso contrário, é falta
    return {'status': 'falta', 'display': '🔴 Falta'}

def group_attendances_by_date(attendances, user, start_date, end_date):
    """
    Agrupa atendimentos por data e calcula status para cada dia no intervalo.
    Parâmetros:
        attendances: QuerySet de Attendance
        user: Instância de CustomUser
        start_date: Data inicial do intervalo
        end_date: Data final do intervalo
    Retorna: Lista de dicionários com dados por dia, incluindo status.
    """
    attendance_dict = defaultdict(list)
    for attendance in attendances:
        date_str = attendance.data_hora.astimezone(timezone.get_current_timezone()).strftime('%d/%m/%Y')
        attendance_dict[date_str].append(attendance)

    attendance_data = []
    current_date = start_date
    while current_date <= end_date:
        date_str = current_date.strftime('%d/%m/%Y')
        day_data = {
            'id': str(attendance_dict[date_str][0].id) if date_str in attendance_dict else f"no_attendance_{date_str}",
            'date': date_str,
            'entrada': '-',
            'entrada_almoco': '-',
            'saida_almoco': '-',
            'saida': '-',
            'observacao': ''
        }

        # Preencher dados de atendimentos, se existirem
        for att in attendance_dict.get(date_str, []):
            time_str = att.data_hora.astimezone(timezone.get_current_timezone()).strftime('%H:%M')
            location_key = f'location_{att.point_type}'
            day_data[location_key] = {
                'latitude': att.latitude,
                'longitude': att.longitude,
                'altitude': att.altitude,
                'accuracy': att.accuracy,
                'is_valid_location': att.is_valid_location,
                'distance_from_workplace_meters': att.distance_from_workplace_meters,
                'place_name': att.place_name,
            }
            day_data[f'location_{att.point_type}_latitude'] = att.latitude
            day_data[f'location_{att.point_type}_longitude'] = att.longitude
            day_data[f'location_{att.point_type}_altitude'] = att.altitude
            day_data[f'location_{att.point_type}_accuracy'] = att.accuracy
            day_data[f'location_{att.point_type}_is_valid'] = att.is_valid_location
            day_data[f'location_{att.point_type}_distance'] = att.distance_from_workplace_meters
            day_data[f'location_{att.point_type}_place_name'] = att.place_name
            
            if att.point_type == 'entrada':
                day_data['entrada'] = time_str
            elif att.point_type == 'almoco':
                day_data['entrada_almoco'] = time_str
                day_data['saida_almoco'] = time_str
            elif att.point_type == 'saida':
                day_data['saida'] = time_str

        # Calcular status do dia
        status_info = calculate_day_status(user, current_date)
        day_data['status'] = status_info['status']
        day_data['status_display'] = status_info['display']

        attendance_data.append(day_data)
        current_date += timedelta(days=1)

    return attendance_data

def calculate_stats(user, attendance_data, total_justificativas, total_pontos_registrados):
    total_hours = 0
    total_faltas = 0
    dias_com_presenca = 0

    for day in attendance_data:
        status = day.get('status', '')
        if status == 'falta':
            total_faltas += 1
        if status == 'presente':
            dias_com_presenca += 1
            try:
                if day['entrada'] != '-' and day['saida'] != '-':
                    entrada_str = day['entrada']
                    saida_str = day['saida']
                    
                    entrada = datetime.strptime(entrada_str, '%H:%M')
                    saida = datetime.strptime(saida_str, '%H:%M')
                    
                    if saida.time() < entrada.time():
                        saida = saida + timezone.timedelta(days=1)
                    
                    almoco_duration = timezone.timedelta(hours=0)
                    almoco_in = day.get('entrada_almoco', '-')
                    almoco_out = day.get('saida_almoco', '-')
                    
                    if almoco_in != '-' and almoco_out != '-':
                        try:
                            almoco_in_dt = datetime.strptime(almoco_in, '%H:%M')
                            almoco_out_dt = datetime.strptime(almoco_out, '%H:%M')
                            
                            if almoco_out_dt.time() >= almoco_in_dt.time():
                                almoco_duration = almoco_out_dt - almoco_in_dt
                            else:
                                almoco_out_dt = almoco_out_dt + timezone.timedelta(days=1)
                                almoco_duration = almoco_out_dt - almoco_in_dt
                        except ValueError:
                            almoco_duration = timezone.timedelta(hours=1)
                    else:
                        almoco_duration = timezone.timedelta(hours=1)
                    
                    work_duration = saida - entrada - almoco_duration
                    
                    if work_duration.total_seconds() > 0:
                        hours_worked = work_duration.total_seconds() / 3600
                        total_hours += hours_worked
                        logger.info(f"Dia {day['date']}: {hours_worked:.2f} horas")
                    else:
                        logger.info(f"Dia {day['date']}: Duração inválida, ignorando")
            except (ValueError, TypeError) as e:
                logger.error(f"Erro ao calcular horas para o dia {day.get('date', '?')}: {e}")
                continue

    return {
        'dias_trabalhados': dias_com_presenca,
        'total_pontos_registrados': total_pontos_registrados,
        'total_justificativas': total_justificativas,
        'horas_trabalhadas_total': round(total_hours, 1),
        'total_faltas': total_faltas,
        'total_atrasos': 0,  # Mantido para compatibilidade
    }

def process_face_image_and_get_embedding(face_image):
    allowed_extensions = {'.jpg', '.jpeg', '.png'}
    file_extension = os.path.splitext(face_image.name.lower())[1]
    if file_extension not in allowed_extensions:
        raise ValueError('Formato de imagem não suportado. Use .jpg, .jpeg ou .png')

    try:
        img = Image.open(face_image)
        img.verify()
        img.close()
        image = face_recognition.load_image_file(face_image, mode='RGB')
        logger.info(f"Processando imagem: {face_image.name}, tamanho: {face_image.size} bytes")
        encodings = face_recognition.face_encodings(image)
        if not encodings:
            raise ValueError("Nenhum rosto detectado na imagem.")
        embedding = encodings[0]
        logger.info(f"Embedding gerado com sucesso: {embedding.tolist()}")
        return embedding
    except Exception as e:
        logger.error(f"Erro ao processar imagem facial: {str(e)}")
        raise ValueError(f"Erro ao processar imagem facial: {str(e)}")

def find_matching_user(login_embedding, User):
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
    return matched_user, min_distance

def save_attendance_photo(face_image):
    file_path = f"attendance/photos/{timezone.now().strftime('%Y%m%d_%H%M%S')}_{face_image.name}"
    try:
        default_storage.save(file_path, face_image)
        logger.info(f"Arquivo salvo em: {file_path}")
        full_path = default_storage.url(file_path)
        return full_path
    except Exception as e:
        logger.error(f"Erro ao salvar arquivo: {str(e)}")
        raise IOError("Erro ao salvar imagem")
