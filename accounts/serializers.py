from rest_framework import serializers
from .models import CustomUser
import numpy as np
import face_recognition
from django.core.files.uploadedfile import InMemoryUploadedFile

class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=6)
    face_image = serializers.ImageField(write_only=True)

    class Meta:
        model = CustomUser
        fields = ['username', 'email', 'password', 'face_image']

    def create(self, validated_data):
        face_image = validated_data.pop('face_image')
        image = face_recognition.load_image_file(face_image)
        encodings = face_recognition.face_encodings(image)
        if not encodings:
            raise serializers.ValidationError("Nenhum rosto detectado na imagem.")
        embedding = encodings[0]

        user = CustomUser.objects.create_user(
            username=validated_data['username'],
            email=validated_data['email'],
            password=validated_data['password'],
            facial_embedding=embedding.tolist()
        )
        return user

class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)
    face_image = serializers.ImageField(write_only=True)