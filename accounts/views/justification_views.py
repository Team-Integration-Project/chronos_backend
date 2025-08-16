from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.generics import ListCreateAPIView, RetrieveUpdateDestroyAPIView
from ..serializers import JustificationSerializer, JustificationApprovalSerializer
from ..models import Justification, JustificationApproval
from ..permission import AdminPermission
from django.utils import timezone
from django.core.exceptions import ObjectDoesNotExist
from rest_framework.exceptions import PermissionDenied
import logging

logger = logging.getLogger(__name__)

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
            approval = JustificationApproval.objects.filter(justification=justification).first()
            
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
                
                'approval': approved_status,
                'approved': approved_status,
                'status': status_text,
                'approved_by': approval.reviewed_by.username if approval and approval.reviewed_by else None,
                'approved_at': approval.reviewed_at.isoformat() if approval and approval.reviewed_at else None,
            }
            data.append(item)
            
            logger.info(f"Justification {justification.id}: approved={approved_status}, status={status_text}")
        
        return Response(data, status=status.HTTP_200_OK)


class JustificationApprovalView(APIView):
    permission_classes = [AdminPermission]

    def post(self, request, justification_id):
        try:
            justification = Justification.objects.get(id=justification_id)
            
            approved = request.data.get('approved')
            approval = request.data.get('approval')
            
            final_approval = approved if approved is not None else approval
            
            logger.info(f"Processando aprovação/reprovação para justification {justification_id}: approved={approved}, approval={approval}, final={final_approval}")
            
            if final_approval is None:
                return Response({'error': 'Campo approved ou approval é obrigatório'}, status=status.HTTP_400_BAD_REQUEST)
            
            if isinstance(final_approval, str):
                final_approval_bool = final_approval.lower() in ['true', '1', 'yes']
            else:
                final_approval_bool = bool(final_approval)
            
            approval_obj, created = JustificationApproval.objects.update_or_create(
                justification=justification,
                defaults={
                    'approved': final_approval_bool,
                    'reviewed_by': request.user,
                    'reviewed_at': timezone.now()
                }
            )
            
            action = "aprovada" if approval_obj.approved else "reprovada"
            status_text = "aprovada" if approval_obj.approved else "recusada"
            logger.info(f"Justificativa {justification_id} {action} por {request.user.username}")
            
            response_data = {
                'id': justification.id,
                'user': justification.user.username if justification.user else 'Desconhecido',
                'employee': justification.user.get_full_name() if justification.user else justification.user.username if justification.user else 'Desconhecido',
                'reason': justification.reason or 'Sem motivo',
                'date': justification.date.strftime('%Y-%m-%d') if justification.date else justification.created_at.date().strftime('%Y-%m-%d'),
                'created_at': justification.created_at.isoformat(),
                
                'approval': approval_obj.approved,
                'approved': approval_obj.approved,
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
