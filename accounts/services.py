from django.utils import timezone
from collections import defaultdict
from datetime import datetime, timedelta
from accounts.models import Attendance, Justification
import face_recognition
import numpy as np
import logging
from PIL import Image
import os
from django.core.files.storage import default_storage

logger = logging.getLogger(__name__)

def filter_attendances_by_period(user, period):
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

def group_attendances_by_date(attendances):
    attendance_dict = defaultdict(list)
    for attendance in attendances:
        date_str = attendance.data_hora.astimezone(timezone.get_current_timezone()).strftime('%d/%m/%Y')
        attendance_dict[date_str].append(attendance)

    attendance_data = []
    for date_str, atts in attendance_dict.items():
        day_data = {'id': str(atts[0].id), 'date': date_str}
        
        for att in atts:
            time_str = att.data_hora.astimezone(timezone.get_current_timezone()).strftime('%H:%M')
            if att.point_type == 'entrada':
                day_data['entrada'] = time_str
            elif att.point_type == 'almoco':
                day_data['entrada_almoco'] = time_str
                day_data['saida_almoco'] = time_str
            elif att.point_type == 'saida':
                day_data['saida'] = time_str
        
        day_data.setdefault('entrada', '-')
        day_data.setdefault('entrada_almoco', '-')
        day_data.setdefault('saida_almoco', '-')
        day_data.setdefault('saida', '-')
        
        day_data['status'] = calculate_day_status(day_data)
        day_data['observacao'] = ''
        attendance_data.append(day_data)

    return attendance_data

def calculate_day_status(day_data):
    entrada = day_data.get('entrada', '-')
    saida = day_data.get('saida', '-')
    
    if entrada == '-':
        return 'Falta'
    
    if saida == '-':
        return 'Pendente'
    
    try:
        entrada_time = datetime.strptime(entrada, '%H:%M').time()
        horario_limite = datetime.strptime('07:00', '%H:%M').time()
        
        if entrada_time > horario_limite:
            return 'Atraso'
    except ValueError:
        pass
    
    return 'Aprovado'

def calculate_stats(user, attendance_data, total_justificativas):
    total_hours = 0
    total_faltas = 0
    total_atrasos = 0
    
    first_attendance_date = None
    if attendance_data:
        sorted_attendance = sorted(attendance_data, key=lambda x: datetime.strptime(x['date'], '%d/%m/%Y'))
        
        for day in sorted_attendance:
            if (day.get('entrada', '-') != '-' or 
                day.get('saida', '-') != '-' or 
                day.get('entrada_almoco', '-') != '-'):
                first_attendance_date = datetime.strptime(day['date'], '%d/%m/%Y').date()
                break
    
    if not first_attendance_date:
        return {
            'totalHoras': 0,
            'totalFaltas': 0,
            'totalAtrasos': 0,
            'totalJustificativas': total_justificativas
        }
    
    print(f"Primeira data com ponto batido: {first_attendance_date}")
    
    today = timezone.now().date()
    current_date = first_attendance_date
    dias_uteis_esperados = 0
    
    while current_date <= today:
        if current_date.weekday() < 5:
            dias_uteis_esperados += 1
        current_date += timezone.timedelta(days=1)
    
    print(f"Dias úteis esperados desde {first_attendance_date}: {dias_uteis_esperados}")
    
    dias_com_presenca = 0
    
    for day in attendance_data:
        status = day.get('status', '')
        day_date = datetime.strptime(day['date'], '%d/%m/%Y').date()
        
        if day_date < first_attendance_date:
            continue
        
        if day_date.weekday() >= 5:
            continue
        
        if status == 'Falta':
            total_faltas += 1
        elif status == 'Atraso':
            total_atrasos += 1
        
        if status in ['Aprovado', 'Atraso']:
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
                    
                    if almoco_in and almoco_in != '-' and almoco_out and almoco_out != '-':
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
                        print(f"Dia {day['date']}: {hours_worked:.2f} horas")
                    else:
                        print(f"Dia {day['date']}: Duração inválida, ignorando")
                        
            except (ValueError, TypeError) as e:
                print(f"Erro ao calcular horas para o dia {day.get('date', '?')}: {e}")
                continue
    
    total_faltas = max(0, dias_uteis_esperados - dias_com_presenca)
    
    print(f"Resumo: {total_hours:.1f}h trabalhadas, {total_faltas} faltas, {total_atrasos} atrasos")

    return {
        'totalHoras': round(total_hours, 1),
        'totalFaltas': total_faltas,
        'totalAtrasos': total_atrasos,
        'totalJustificativas': total_justificativas
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
