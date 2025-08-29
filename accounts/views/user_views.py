from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.contrib.auth import get_user_model
from rest_framework.permissions import IsAuthenticated
from rest_framework.generics import ListCreateAPIView
from ..serializers import RegisterSerializer, UserProfileSerializer, AttendanceUsersSerializer
from accounts.models import UserRole, CustomUser
from ..permission import AdminPermission
from django.core.exceptions import ObjectDoesNotExist
import logging
from ..utils.validators import validate_cpf, validate_phone_number

logger = logging.getLogger(__name__)
User = get_user_model()

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

            if cpf:
                is_valid_cpf, cpf_error = validate_cpf(cpf)
                if not is_valid_cpf:
                    logger.error(f"CPF inválido para usuário {user.email}: {cpf}")
                    return Response({'cpf': cpf_error}, status=status.HTTP_400_BAD_REQUEST)

            if phone_number:
                is_valid_phone, phone_error = validate_phone_number(phone_number)
                if not is_valid_phone:
                    logger.error(f"Telefone inválido para usuário {user.email}: {phone_number}")
                    return Response({'phone_number': phone_error}, status=status.HTTP_400_BAD_REQUEST)

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

                if cpf:
                    is_valid_cpf, cpf_error = validate_cpf(cpf)
                    if not is_valid_cpf:
                        logger.error(f"CPF inválido para usuário {user.email}: {cpf}")
                        return Response({'cpf': cpf_error}, status=status.HTTP_400_BAD_REQUEST)

                if phone_number:
                    is_valid_phone, phone_error = validate_phone_number(phone_number)
                    if not is_valid_phone:
                        logger.error(f"Telefone inválido para usuário {user.email}: {phone_number}")
                        return Response({'phone_number': phone_error}, status=status.HTTP_400_BAD_REQUEST)

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
