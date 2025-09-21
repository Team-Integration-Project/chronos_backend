from rest_framework import serializers
from .models import CustomUser, Attendance, Justification, JustificationApproval, FacialRecognitionFailure, UserRole
from django.core.files.uploadedfile import InMemoryUploadedFile
import logging
from .services import process_face_image_and_get_embedding

logger = logging.getLogger(__name__)

class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=6)
    confirm_password = serializers.CharField(write_only=True)
    phone_number = serializers.CharField()
    cpf = serializers.CharField()
    face_image = serializers.ImageField(write_only=True)

    class Meta:
        model = CustomUser
        fields = ['id', 'username', 'email', 'password', 'confirm_password', 'phone_number', 'cpf', 'face_image', 'role']

    def validate(self, attrs):
        if attrs['password'] != attrs['confirm_password']:
            raise serializers.ValidationError({"password": "As senhas não coincidem."})
        return attrs

    def create(self, validated_data):
        face_image = validated_data.pop('face_image')
        validated_data.pop('confirm_password')
        try:
            embedding = process_face_image_and_get_embedding(face_image)
        except ValueError as e:
            raise serializers.ValidationError(str(e))

        user = CustomUser.objects.create_user(
            username=validated_data['username'],
            email=validated_data['email'],
            password=validated_data['password'],
            phone_number=validated_data['phone_number'],
            cpf=validated_data['cpf'],
            facial_embedding=embedding.tolist(),
            role=validated_data.get('role', UserRole.USER.value)
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

from rest_framework import serializers
from accounts.models import Attendance, Justification, CustomUser

class AttendanceSerializer(serializers.ModelSerializer):
    user = serializers.PrimaryKeyRelatedField(queryset=CustomUser.objects.all(), write_only=True)
    user_detail = serializers.StringRelatedField(source='user', read_only=True)
    latitude = serializers.FloatField(required=True, allow_null=False)
    longitude = serializers.FloatField(required=True, allow_null=False)
    altitude = serializers.FloatField(required=False, allow_null=True) 
    accuracy = serializers.FloatField(required=False, allow_null=True) 
    place_name = serializers.CharField(required=False, allow_null=True, allow_blank=True)  
    
    class Meta:
        model = Attendance
        fields = [
            'id', 'user', 'user_detail', 'point_type', 'data_hora', 'foto_path', 
            'is_synced', 'latitude', 'longitude', 'altitude', 'accuracy', 
            'place_name', 'is_valid_location', 'distance_from_workplace_meters'
        ]
        read_only_fields = [
            'id', 'data_hora', 'foto_path', 'user_detail', 
            'is_valid_location', 'distance_from_workplace_meters'
        ]
        extra_kwargs = {
            'point_type': {'required': True, 'validators': []},
        }

    def validate_point_type(self, value):
        valid_types = ['entrada', 'almoco', 'saida']
        if value not in valid_types:
            raise serializers.ValidationError(f"Tipo de ponto deve ser um dos seguintes: {', '.join(valid_types)}")
        return value

    def validate(self, attrs):
        latitude = attrs.get('latitude')
        longitude = attrs.get('longitude')
        
        if latitude is not None and longitude is not None:
            try:
                latitude = float(latitude)
                longitude = float(longitude)
                if not (-90 <= latitude <= 90) or not (-180 <= longitude <= 180):
                    raise serializers.ValidationError("Latitude deve estar entre -90 e 90, e longitude entre -180 e 180.")
            except (TypeError, ValueError):
                raise serializers.ValidationError("Latitude e longitude devem ser números válidos.")
        
        altitude = attrs.get('altitude')
        if altitude is not None:
            try:
                altitude = float(altitude)
                if altitude < -500 or altitude > 10000:  
                    raise serializers.ValidationError("Altitude deve estar entre -500 e 10000 metros.")
            except (TypeError, ValueError):
                raise serializers.ValidationError("Altitude deve ser um número válido.")
        
        accuracy = attrs.get('accuracy')
        if accuracy is not None:
            try:
                accuracy = float(accuracy)
                if accuracy < 0:
                    raise serializers.ValidationError("Precisão (accuracy) deve ser um valor positivo.")
            except (TypeError, ValueError):
                raise serializers.ValidationError("Precisão (accuracy) deve ser um número válido.")
        
        return attrs

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
        fields = ['id', 'user', 'date', 'reason', 'created_at', 'attachment']
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

class FacialRecognitionFailureSerializer(serializers.ModelSerializer):
    class Meta:
        model = FacialRecognitionFailure
        fields = ['id', 'user', 'reason', 'date']

class AttendanceUsersSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='__str__')
    cpf = serializers.CharField()
    phone_number = serializers.CharField()

    class Meta:
        model = CustomUser
        fields = ['id', 'username', 'email', 'cpf', 'phone_number']

class UserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomUser
        fields = ['id', 'username', 'email', 'role', 'phone_number', 'cpf']