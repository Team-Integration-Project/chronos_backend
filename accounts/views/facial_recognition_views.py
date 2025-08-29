from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from ..serializers import FacialRecognitionFailureSerializer
from ..models import FacialRecognitionFailure
from django.utils import timezone
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

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
