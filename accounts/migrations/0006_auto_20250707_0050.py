from django.db import migrations, models
import django.utils.timezone

class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0005_alter_passwordresettoken_is_used_attendance_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='Justification',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField(default=django.utils.timezone.now)),
                ('reason', models.TextField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(blank=True, null=True, on_delete=models.CASCADE, to='accounts.customuser')),
            ],
        ),
    ]