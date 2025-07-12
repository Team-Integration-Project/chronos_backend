from django.db import models
from django.contrib.auth.models import AbstractUser
from pgvector.django import VectorField
from enum import Enum
from django.utils import timezone

class UserRole(Enum):
    USER = "user"
    ADMIN = "admin"

class CustomUser(AbstractUser):
    email = models.EmailField(unique=True)
    facial_embedding = VectorField(dimensions=128, null=True, blank=True)
    role = models.CharField(max_length=10, choices=[(role.value, role.value) for role in UserRole], default=UserRole.USER.value)
    phone_number = models.CharField(max_length=15, blank=True, null=True)
    cpf = models.CharField(max_length=14, blank=True, null= True)

    def __str__(self):
        return self.username

    @property
    def is_admin(self):
        return self.role == UserRole.ADMIN.value

class PasswordResetToken(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    token = models.CharField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_used = models.BooleanField(default=False)

    def __str__(self):
        return f"Token for {self.user.email}"

class Attendance(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    point_type = models.CharField(max_length=20, choices=[
        ('entrada', 'Entrada'),
        ('almoco', 'Almoço'),
        ('saida', 'Saída')
    ])
    data_hora = models.DateTimeField(auto_now_add=True)
    foto_path = models.ImageField(upload_to='attendance/photos/', null=True, blank=True)
    is_synced = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.user.username} - {self.point_type} em {self.data_hora}"

class Justification(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, null=True, blank=True)
    date = models.DateField(default=timezone.now)
    reason = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username if self.user else 'Desconhecido'} - Justificativa em {self.date}"

class JustificationApproval(models.Model):
    justification = models.OneToOneField(Justification, on_delete=models.CASCADE, related_name='approval')
    approved = models.BooleanField(null=True)  
    reviewed_by = models.ForeignKey(CustomUser, null=True, blank=True, on_delete=models.SET_NULL, related_name='reviewed_justifications')
    reviewed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        status = "Aprovada" if self.approved else "Reprovada" if self.approved is False else "Pendente"
        return f"{self.justification} - {status}"
    
class FacialRecognitionFailure(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True)
    reason = models.TextField()
    date = models.DateField(default=timezone.now)

    def __str__(self):
        return f"{self.user.username if self.user else 'Desconhecido'} - {self.reason[:20]}"