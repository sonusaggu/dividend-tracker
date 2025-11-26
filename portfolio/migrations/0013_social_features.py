# Generated manually for social features

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('portfolio', '0012_affiliatelink_sponsoredcontent'),
    ]

    operations = [
        migrations.CreateModel(
            name='UserProfile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('bio', models.TextField(blank=True, help_text='Short bio about yourself', max_length=500)),
                ('avatar', models.URLField(blank=True, help_text='URL to profile picture')),
                ('location', models.CharField(blank=True, max_length=100)),
                ('website', models.URLField(blank=True)),
                ('twitter_handle', models.CharField(blank=True, max_length=50)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='profile', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'User Profile',
                'verbose_name_plural': 'User Profiles',
            },
        ),
        migrations.CreateModel(
            name='Follow',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('follower', models.ForeignKey(db_index=True, on_delete=django.db.models.deletion.CASCADE, related_name='following', to=settings.AUTH_USER_MODEL)),
                ('following', models.ForeignKey(db_index=True, on_delete=django.db.models.deletion.CASCADE, related_name='followers', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Follow',
                'verbose_name_plural': 'Follows',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='Post',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('post_type', models.CharField(choices=[('insight', 'Investment Insight'), ('analysis', 'Stock Analysis'), ('question', 'Question'), ('discussion', 'Discussion'), ('update', 'Portfolio Update')], default='insight', max_length=20)),
                ('title', models.CharField(blank=True, max_length=200)),
                ('content', models.TextField(help_text='Post content', max_length=5000)),
                ('likes_count', models.IntegerField(default=0)),
                ('comments_count', models.IntegerField(default=0)),
                ('views_count', models.IntegerField(default=0)),
                ('is_pinned', models.BooleanField(default=False)),
                ('is_edited', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('stock', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='posts', to='portfolio.stock')),
                ('user', models.ForeignKey(db_index=True, on_delete=django.db.models.deletion.CASCADE, related_name='posts', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Post',
                'verbose_name_plural': 'Posts',
                'ordering': ['-is_pinned', '-created_at'],
            },
        ),
        migrations.CreateModel(
            name='Comment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('content', models.TextField(max_length=2000)),
                ('likes_count', models.IntegerField(default=0)),
                ('is_edited', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('post', models.ForeignKey(db_index=True, on_delete=django.db.models.deletion.CASCADE, related_name='comments', to='portfolio.post')),
                ('user', models.ForeignKey(db_index=True, on_delete=django.db.models.deletion.CASCADE, related_name='comments', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Comment',
                'verbose_name_plural': 'Comments',
                'ordering': ['created_at'],
            },
        ),
        migrations.CreateModel(
            name='PostLike',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('post', models.ForeignKey(db_index=True, on_delete=django.db.models.deletion.CASCADE, related_name='post_likes', to='portfolio.post')),
                ('user', models.ForeignKey(db_index=True, on_delete=django.db.models.deletion.CASCADE, related_name='post_likes', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Post Like',
                'verbose_name_plural': 'Post Likes',
            },
        ),
        migrations.CreateModel(
            name='CommentLike',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('comment', models.ForeignKey(db_index=True, on_delete=django.db.models.deletion.CASCADE, related_name='comment_likes', to='portfolio.comment')),
                ('user', models.ForeignKey(db_index=True, on_delete=django.db.models.deletion.CASCADE, related_name='comment_likes', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Comment Like',
                'verbose_name_plural': 'Comment Likes',
            },
        ),
        migrations.AlterUniqueTogether(
            name='postlike',
            unique_together={('post', 'user')},
        ),
        migrations.AlterUniqueTogether(
            name='follow',
            unique_together={('follower', 'following')},
        ),
        migrations.AlterUniqueTogether(
            name='commentlike',
            unique_together={('comment', 'user')},
        ),
    ]

