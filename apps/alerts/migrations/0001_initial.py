
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('farms', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Alert',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('kind', models.CharField(choices=[('irrigation_due', 'Irrigation due (AWD threshold reached)'), ('sensor_silent', 'No readings received'), ('overflow', 'Standing water too deep')], max_length=20)),
                ('severity', models.CharField(choices=[('info', 'Info'), ('warning', 'Warning'), ('critical', 'Critical')], default='warning', max_length=10)),
                ('message', models.CharField(max_length=300)),
                ('value', models.DecimalField(blank=True, decimal_places=1, max_digits=6, null=True)),
                ('triggered_at', models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ('resolved_at', models.DateTimeField(blank=True, null=True)),
                ('resolution_note', models.CharField(blank=True, max_length=200)),
                ('field', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='alerts', to='farms.field')),
                ('resolved_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-triggered_at'],
            },
        ),
        migrations.AddConstraint(
            model_name='alert',
            constraint=models.UniqueConstraint(condition=models.Q(('resolved_at__isnull', True)), fields=('field', 'kind'), name='uniq_open_alert_per_field_kind'),
        ),
    ]
