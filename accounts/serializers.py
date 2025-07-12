from rest_framework import serializers
from .models import CustomUser, Attendance, Justification, JustificationApproval
import numpy as np
import face_recognition
from django.core.files.uploadedfile import InMemoryUploadedFile
import logging

logger = logging.getLogger(__name__)

class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=6)
    confirm_password = serializers.CharField(write_only=True)
    phone_number = serializers.CharField()
    cpf = serializers.CharField()
    face_image = serializers.ImageField(write_only=True)

    class Meta:
        model = CustomUser
        fields = ['id', 'username', 'email', 'password', 'confirm_password', 'phone_number', 'cpf', 'face_image']
    
    def validate(self, attrs):
        if attrs['password'] != attrs['confirm_password']:
            raise serializers.ValidationError({"password": "As senhas não coincidem."})
        return attrs

    def create(self, validated_data):
        face_image = validated_data.pop('face_image')
        try:
            logger.info(f"Processando imagem: {face_image.name}, tamanho: {face_image.size}")
            image = face_recognition.load_image_file(face_image.file)
            encodings = face_recognition.face_encodings(image)
            if not encodings:
                raise serializers.ValidationError("Nenhum rosto detectado na imagem.")
            embedding = encodings[0]
            logger.info(f"Embedding gerado com sucesso: {embedding.tolist()}")
        except Exception as e:
            logger.error(f"Erro ao processar imagem facial: {str(e)}")
            raise serializers.ValidationError(f"Erro ao processar imagem: {str(e)}")

        user = CustomUser.objects.create_user(
            username=validated_data['username'],
            email=validated_data['email'],
            password=validated_data['password'],
            phone_number=validated_data['phone_number'],
            cpf=validated_data['cpf'],
            facial_embedding=embedding.tolist()
        )
        return user

class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()

class ResetPasswordSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=255)
    new_password = serializers.CharField(min_length=6, write_only=True)

class AttendanceSerializer(serializers.ModelSerializer):
    user = serializers.PrimaryKeyRelatedField(queryset=CustomUser.objects.all(), write_only=True)
    user_detail = serializers.StringRelatedField(source='user', read_only=True)  

    class Meta:
        model = Attendance
        fields = ['id', 'user', 'user_detail', 'point_type', 'data_hora', 'foto_path', 'is_synced']
        read_only_fields = ['id', 'data_hora', 'foto_path', 'user_detail']
        extra_kwargs = {
            'point_type': {'required': True, 'validators': []},
        }

    def validate_point_type(self, value):
        valid_types = ['entrada', 'almoco', 'saida']
        if value not in valid_types:
            raise serializers.ValidationError(f"Tipo de ponto deve ser um dos seguintes: {', '.join(valid_types)}")
        return value

    def create(self, validated_data):
        user = validated_data.pop('user')  
        if isinstance(user, CustomUser):
            user_id = user.id
        else:
            user_id = user
        attendance = Attendance.objects.create(user_id=user_id, **validated_data)
        return attendance

class JustificationSerializer(serializers.ModelSerializer):
    user = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = Justification
        fields = ['id', 'user', 'date', 'reason', 'created_at']
        read_only_fields = ['id', 'created_at', 'user']
        extra_kwargs = {
            'reason': {'required': True, 'min_length': 5},
            'date': {'required': True},
        }

class JustificationApprovalSerializer(serializers.ModelSerializer):
    justification_detail = JustificationSerializer(source='justification', read_only=True)
    reviewed_by = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = JustificationApproval
        fields = ['id', 'justification', 'justification_detail', 'approved', 'reviewed_by', 'reviewed_at']
        read_only_fields = ['id', 'reviewed_by', 'reviewed_at']
