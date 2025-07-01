from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.contrib.auth import authenticate, get_user_model
from rest_framework_simplejwt.tokens import RefreshToken
from .serializers import RegisterSerializer, LoginSerializer
from .models import CustomUser
import face_recognition
import numpy as np
import logging

logger = logging.getLogger(__name__)

class RegisterView(APIView):
    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        if serializer.is_valid():
            try:
                user = serializer.save()
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