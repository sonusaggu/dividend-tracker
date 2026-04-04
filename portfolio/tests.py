from datetime import timedelta

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from portfolio.backends import EmailOrUsernameBackend
from portfolio.forms import RegistrationForm
from portfolio.models import EmailVerification


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_verified_user(username='verifieduser', email='verified@gmail.com', password='TestPass123!'):
    user = User.objects.create_user(username=username, email=email, password=password)
    EmailVerification.objects.create(user=user, token=f'tok-{username}', is_verified=True)
    return user


def make_unverified_user(username='unverifieduser', email='unverified@gmail.com', password='TestPass123!'):
    user = User.objects.create_user(username=username, email=email, password=password)
    EmailVerification.objects.create(user=user, token=f'tok-{username}', is_verified=False)
    return user


def make_legacy_user(username='legacyuser', email='legacy@gmail.com', password='TestPass123!'):
    """User created > 7 days ago with NO EmailVerification record (pre-verification era)."""
    user = User.objects.create_user(username=username, email=email, password=password)
    User.objects.filter(pk=user.pk).update(date_joined=timezone.now() - timedelta(days=10))
    user.refresh_from_db()
    return user


# ---------------------------------------------------------------------------
# Login view
# ---------------------------------------------------------------------------

class LoginViewTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.url = reverse('login')
        self.verified = make_verified_user()
        self.unverified = make_unverified_user()
        self.legacy = make_legacy_user()

    # --- GET ---

    def test_login_page_loads(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'login.html')

    def test_authenticated_user_redirected_to_dashboard(self):
        self.client.force_login(self.verified)
        response = self.client.get(self.url)
        self.assertRedirects(response, reverse('dashboard'))

    # --- Successful login ---

    def test_login_success_by_username(self):
        response = self.client.post(self.url, {'username': 'verifieduser', 'password': 'TestPass123!'})
        self.assertRedirects(response, reverse('dashboard'))

    def test_login_success_by_email(self):
        response = self.client.post(self.url, {'username': 'verified@gmail.com', 'password': 'TestPass123!'})
        self.assertRedirects(response, reverse('dashboard'))

    def test_login_case_insensitive_email(self):
        response = self.client.post(self.url, {'username': 'VERIFIED@GMAIL.COM', 'password': 'TestPass123!'})
        self.assertRedirects(response, reverse('dashboard'))

    def test_login_case_insensitive_username(self):
        response = self.client.post(self.url, {'username': 'VerifiedUser', 'password': 'TestPass123!'})
        self.assertRedirects(response, reverse('dashboard'))

    def test_login_redirects_to_next_url(self):
        response = self.client.post(
            self.url,
            {'username': 'verifieduser', 'password': 'TestPass123!', 'next': '/watchlist/'},
        )
        self.assertRedirects(response, '/watchlist/')

    def test_login_invalid_next_url_defaults_to_dashboard(self):
        """Malicious or invalid next values must not cause an open redirect."""
        for bad_next in ['http://evil.com', 'null', 'None', '', '//evil.com']:
            response = self.client.post(
                self.url,
                {'username': 'verifieduser', 'password': 'TestPass123!', 'next': bad_next},
            )
            # Should go to dashboard, not an external URL
            self.assertRedirects(response, reverse('dashboard'))

    # --- Remember me ---

    def test_remember_me_sets_long_session(self):
        self.client.post(self.url, {
            'username': 'verifieduser', 'password': 'TestPass123!', 'remember-me': 'on',
        })
        self.assertGreater(self.client.session.get_expiry_age(), 86400)  # > 1 day

    def test_no_remember_me_session_expires_on_close(self):
        self.client.post(self.url, {'username': 'verifieduser', 'password': 'TestPass123!'})
        # set_expiry(0) means "expire when browser closes"; check the flag, not the age
        self.assertTrue(self.client.session.get_expire_at_browser_close())

    # --- Failed login ---

    def test_wrong_password_shows_error(self):
        response = self.client.post(self.url, {'username': 'verifieduser', 'password': 'WrongPass!'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Invalid username or password')

    def test_nonexistent_user_shows_error(self):
        response = self.client.post(self.url, {'username': 'nobody', 'password': 'TestPass123!'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Invalid username or password')

    def test_empty_credentials_show_error(self):
        response = self.client.post(self.url, {'username': '', 'password': ''})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'required')

    # --- Email verification checks ---

    def test_unverified_user_blocked_at_login(self):
        response = self.client.post(self.url, {'username': 'unverifieduser', 'password': 'TestPass123!'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'not yet verified')

    def test_unverified_user_not_logged_in_after_block(self):
        self.client.post(self.url, {'username': 'unverifieduser', 'password': 'TestPass123!'})
        response = self.client.get(reverse('dashboard'))
        # Should redirect to login (not authenticated)
        self.assertRedirects(response, f"{reverse('login')}?next={reverse('dashboard')}")

    def test_legacy_user_without_verification_record_can_login(self):
        """Users created before email verification was added must still be able to log in."""
        response = self.client.post(self.url, {'username': 'legacyuser', 'password': 'TestPass123!'})
        self.assertRedirects(response, reverse('dashboard'))

    def test_unverified_warning_contains_resend_link_with_username(self):
        """The resend link must include the username param so unauthenticated users can use it."""
        response = self.client.post(self.url, {'username': 'unverifieduser', 'password': 'TestPass123!'})
        self.assertContains(response, 'resend-verification')
        self.assertContains(response, 'unverifieduser')


# ---------------------------------------------------------------------------
# Registration view
# ---------------------------------------------------------------------------

class RegisterViewTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.url = reverse('register')

    def test_register_page_loads(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'register.html')

    def test_authenticated_user_redirected_to_dashboard(self):
        user = make_verified_user()
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertRedirects(response, reverse('dashboard'))

    # --- Successful registration ---

    def test_register_creates_user(self):
        self.client.post(self.url, {
            'email': 'newuser@gmail.com',
            'password1': 'TestPass123!',
            'password2': 'TestPass123!',
        })
        self.assertTrue(User.objects.filter(email='newuser@gmail.com').exists())

    def test_register_redirects_to_verify_email_sent(self):
        response = self.client.post(self.url, {
            'email': 'newuser@gmail.com',
            'password1': 'TestPass123!',
            'password2': 'TestPass123!',
        })
        self.assertRedirects(response, reverse('verify_email_sent'))

    def test_register_creates_unverified_email_verification_record(self):
        self.client.post(self.url, {
            'email': 'newuser@gmail.com',
            'password1': 'TestPass123!',
            'password2': 'TestPass123!',
        })
        user = User.objects.get(email='newuser@gmail.com')
        verification = EmailVerification.objects.get(user=user)
        self.assertFalse(verification.is_verified)

    def test_register_does_not_auto_login_user(self):
        """User must verify email before being logged in."""
        self.client.post(self.url, {
            'email': 'newuser@gmail.com',
            'password1': 'TestPass123!',
            'password2': 'TestPass123!',
        })
        # Accessing dashboard should redirect to login
        response = self.client.get(reverse('dashboard'))
        self.assertRedirects(response, f"{reverse('login')}?next={reverse('dashboard')}")

    def test_register_auto_generates_username_from_email(self):
        self.client.post(self.url, {
            'email': 'janedoe@gmail.com',
            'password1': 'TestPass123!',
            'password2': 'TestPass123!',
        })
        user = User.objects.get(email='janedoe@gmail.com')
        self.assertIn('janedoe', user.username.lower())

    def test_register_uses_custom_username_when_provided(self):
        self.client.post(self.url, {
            'email': 'user@gmail.com',
            'username': 'mycustomname',
            'password1': 'TestPass123!',
            'password2': 'TestPass123!',
        })
        self.assertTrue(User.objects.filter(username='mycustomname').exists())

    # --- Corporate / non-standard domains now accepted ---

    def test_register_corporate_email_accepted(self):
        """Fix: allowlist was removed — corporate emails must now be accepted."""
        response = self.client.post(self.url, {
            'email': 'user@acme.com',
            'password1': 'TestPass123!',
            'password2': 'TestPass123!',
        })
        self.assertRedirects(response, reverse('verify_email_sent'))
        self.assertTrue(User.objects.filter(email='user@acme.com').exists())

    def test_register_edu_email_accepted(self):
        response = self.client.post(self.url, {
            'email': 'student@ubc.ca',
            'password1': 'TestPass123!',
            'password2': 'TestPass123!',
        })
        self.assertRedirects(response, reverse('verify_email_sent'))

    def test_register_canadian_isp_email_accepted(self):
        response = self.client.post(self.url, {
            'email': 'user@bell.net',
            'password1': 'TestPass123!',
            'password2': 'TestPass123!',
        })
        self.assertRedirects(response, reverse('verify_email_sent'))

    # --- Rejections ---

    def test_register_disposable_email_rejected(self):
        response = self.client.post(self.url, {
            'email': 'test@mailinator.com',
            'password1': 'TestPass123!',
            'password2': 'TestPass123!',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(email='test@mailinator.com').exists())

    def test_register_duplicate_email_rejected(self):
        User.objects.create_user('existinguser', 'taken@gmail.com', 'Pass123!')
        response = self.client.post(self.url, {
            'email': 'taken@gmail.com',
            'password1': 'TestPass123!',
            'password2': 'TestPass123!',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'already exists')

    def test_register_password_mismatch_rejected(self):
        response = self.client.post(self.url, {
            'email': 'newuser@gmail.com',
            'password1': 'TestPass123!',
            'password2': 'DifferentPass456!',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(email='newuser@gmail.com').exists())

    def test_register_duplicate_username_rejected(self):
        User.objects.create_user('takenname', 'other@gmail.com', 'Pass123!')
        response = self.client.post(self.url, {
            'email': 'newuser@gmail.com',
            'username': 'takenname',
            'password1': 'TestPass123!',
            'password2': 'TestPass123!',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(email='newuser@gmail.com').exists())


# ---------------------------------------------------------------------------
# Resend verification email view
# ---------------------------------------------------------------------------

class ResendVerificationTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.url = reverse('resend_verification')
        self.unverified = make_unverified_user()

    def test_unauthenticated_with_username_param_succeeds(self):
        """
        Bug fix: previously @login_required blocked unauthenticated users.
        Now the view looks up the user by username GET param.
        """
        response = self.client.get(f'{self.url}?username=unverifieduser')
        # Redirects to verify_email_sent (even if email sending fails in test env)
        self.assertIn(response.status_code, [200, 302])

    def test_unauthenticated_no_username_redirects_to_login(self):
        response = self.client.get(self.url)
        self.assertRedirects(response, reverse('login'))

    def test_unauthenticated_unknown_username_redirects_to_login(self):
        response = self.client.get(f'{self.url}?username=nosuchuser')
        self.assertRedirects(response, reverse('login'))

    def test_authenticated_already_verified_redirects_to_login(self):
        verified = make_verified_user()
        self.client.force_login(verified)
        response = self.client.get(self.url)
        # Don't follow the chain — the authenticated login page immediately redirects to dashboard
        self.assertRedirects(response, reverse('login'), fetch_redirect_response=False)

    def test_unauthenticated_lookup_by_email_param(self):
        """Username param also accepts email addresses."""
        response = self.client.get(f'{self.url}?username=unverified%40gmail.com')
        # User was found — should redirect to verify_email_sent, not to login
        self.assertRedirects(response, reverse('verify_email_sent'), fetch_redirect_response=False)


# ---------------------------------------------------------------------------
# Email verification view
# ---------------------------------------------------------------------------

class EmailVerificationViewTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user('testuser', 'test@gmail.com', 'TestPass123!')
        self.verification = EmailVerification.objects.create(
            user=self.user,
            token='valid-test-token',
            is_verified=False,
        )

    def test_valid_token_verifies_email(self):
        self.client.get(reverse('verify_email', args=['valid-test-token']))
        self.verification.refresh_from_db()
        self.assertTrue(self.verification.is_verified)

    def test_valid_token_redirects_to_login(self):
        response = self.client.get(reverse('verify_email', args=['valid-test-token']))
        self.assertRedirects(response, reverse('login'))

    def test_invalid_token_redirects_to_login(self):
        response = self.client.get(reverse('verify_email', args=['invalid-token']))
        self.assertRedirects(response, reverse('login'))

    def test_expired_token_not_verified(self):
        # Force created_at to > 24 hours ago
        EmailVerification.objects.filter(pk=self.verification.pk).update(
            created_at=timezone.now() - timedelta(hours=25)
        )
        self.client.get(reverse('verify_email', args=['valid-test-token']))
        self.verification.refresh_from_db()
        self.assertFalse(self.verification.is_verified)

    def test_already_used_token_rejected(self):
        # Mark as already verified
        self.verification.is_verified = True
        self.verification.save()
        response = self.client.get(reverse('verify_email', args=['valid-test-token']))
        self.assertRedirects(response, reverse('login'))

    def test_verified_user_can_login_after_verification(self):
        self.client.get(reverse('verify_email', args=['valid-test-token']))
        # Now try to login
        response = self.client.post(reverse('login'), {
            'username': 'testuser',
            'password': 'TestPass123!',
        })
        self.assertRedirects(response, reverse('dashboard'))


# ---------------------------------------------------------------------------
# RegistrationForm unit tests
# ---------------------------------------------------------------------------

class RegistrationFormTests(TestCase):

    def _data(self, **overrides):
        base = {'email': 'test@gmail.com', 'password1': 'TestPass123!', 'password2': 'TestPass123!'}
        base.update(overrides)
        return base

    def test_valid_gmail_accepted(self):
        form = RegistrationForm(data=self._data())
        self.assertTrue(form.is_valid(), form.errors)

    def test_valid_outlook_accepted(self):
        form = RegistrationForm(data=self._data(email='user@outlook.com'))
        self.assertTrue(form.is_valid(), form.errors)

    def test_corporate_email_now_accepted(self):
        """After removing the allowlist, corporate emails must be valid."""
        form = RegistrationForm(data=self._data(email='john@acme.com'))
        self.assertTrue(form.is_valid(), form.errors)

    def test_edu_email_accepted(self):
        form = RegistrationForm(data=self._data(email='student@ubc.ca'))
        self.assertTrue(form.is_valid(), form.errors)

    def test_disposable_email_rejected(self):
        form = RegistrationForm(data=self._data(email='user@tempmail.com'))
        self.assertFalse(form.is_valid())
        self.assertIn('email', form.errors)

    def test_disposable_mailinator_rejected(self):
        form = RegistrationForm(data=self._data(email='user@mailinator.com'))
        self.assertFalse(form.is_valid())
        self.assertIn('email', form.errors)

    def test_invalid_email_format_rejected(self):
        form = RegistrationForm(data=self._data(email='notanemail'))
        self.assertFalse(form.is_valid())
        self.assertIn('email', form.errors)

    def test_double_at_rejected(self):
        form = RegistrationForm(data=self._data(email='a@@gmail.com'))
        self.assertFalse(form.is_valid())
        self.assertIn('email', form.errors)

    def test_duplicate_email_rejected(self):
        User.objects.create_user('existing', 'taken@gmail.com', 'Pass123!')
        form = RegistrationForm(data=self._data(email='taken@gmail.com'))
        self.assertFalse(form.is_valid())
        self.assertIn('email', form.errors)

    def test_password_mismatch_rejected(self):
        form = RegistrationForm(data=self._data(password2='Different123!'))
        self.assertFalse(form.is_valid())
        self.assertIn('password2', form.errors)

    def test_username_too_short_rejected(self):
        form = RegistrationForm(data=self._data(username='ab'))
        self.assertFalse(form.is_valid())
        self.assertIn('username', form.errors)

    def test_username_special_chars_rejected(self):
        form = RegistrationForm(data=self._data(username='user@name!'))
        self.assertFalse(form.is_valid())
        self.assertIn('username', form.errors)

    def test_blank_username_allowed(self):
        form = RegistrationForm(data=self._data(username=''))
        self.assertTrue(form.is_valid(), form.errors)

    def test_save_auto_generates_username_from_email(self):
        form = RegistrationForm(data=self._data(email='janedoe@gmail.com', username=''))
        self.assertTrue(form.is_valid())
        user = form.save()
        self.assertIn('janedoe', user.username.lower())
        user.delete()

    def test_save_uses_provided_username(self):
        form = RegistrationForm(data=self._data(username='customuser'))
        self.assertTrue(form.is_valid())
        user = form.save()
        self.assertEqual(user.username, 'customuser')
        user.delete()

    def test_auto_username_unique_on_collision(self):
        """If base username already exists, save() must generate a unique one."""
        User.objects.create_user('janedoe', 'other@outlook.com', 'Pass123!')
        form = RegistrationForm(data=self._data(email='janedoe@gmail.com', username=''))
        self.assertTrue(form.is_valid())
        user = form.save()
        self.assertNotEqual(user.username, 'janedoe')  # Must not conflict
        user.delete()


# ---------------------------------------------------------------------------
# EmailOrUsernameBackend unit tests
# ---------------------------------------------------------------------------

class EmailOrUsernameBackendTests(TestCase):

    def setUp(self):
        self.backend = EmailOrUsernameBackend()
        self.user = User.objects.create_user(
            username='TestUser',
            email='TestUser@gmail.com',
            password='TestPass123!',
        )

    def test_authenticate_by_username(self):
        user = self.backend.authenticate(None, username='TestUser', password='TestPass123!')
        self.assertIsNotNone(user)
        self.assertEqual(user.pk, self.user.pk)

    def test_authenticate_by_email(self):
        user = self.backend.authenticate(None, username='TestUser@gmail.com', password='TestPass123!')
        self.assertIsNotNone(user)
        self.assertEqual(user.pk, self.user.pk)

    def test_authenticate_case_insensitive_username(self):
        user = self.backend.authenticate(None, username='testuser', password='TestPass123!')
        self.assertIsNotNone(user)

    def test_authenticate_case_insensitive_email(self):
        user = self.backend.authenticate(None, username='TESTUSER@GMAIL.COM', password='TestPass123!')
        self.assertIsNotNone(user)

    def test_authenticate_wrong_password_returns_none(self):
        result = self.backend.authenticate(None, username='TestUser', password='WrongPass!')
        self.assertIsNone(result)

    def test_authenticate_nonexistent_user_returns_none(self):
        result = self.backend.authenticate(None, username='nobody', password='TestPass123!')
        self.assertIsNone(result)

    def test_authenticate_inactive_user_blocked(self):
        self.user.is_active = False
        self.user.save()
        result = self.backend.authenticate(None, username='TestUser', password='TestPass123!')
        self.assertIsNone(result)

    def test_authenticate_none_credentials_returns_none(self):
        result = self.backend.authenticate(None, username=None, password=None)
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# EmailVerification model unit tests
# ---------------------------------------------------------------------------

class EmailVerificationModelTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('modeluser', 'model@gmail.com', 'Pass123!')

    def test_fresh_token_not_expired(self):
        v = EmailVerification.objects.create(user=self.user, token='tok1', is_verified=False)
        self.assertFalse(v.is_expired())

    def test_token_older_than_24h_is_expired(self):
        v = EmailVerification.objects.create(user=self.user, token='tok2', is_verified=False)
        EmailVerification.objects.filter(pk=v.pk).update(
            created_at=timezone.now() - timedelta(hours=25)
        )
        v.refresh_from_db()
        self.assertTrue(v.is_expired())

    def test_verified_token_never_expired(self):
        v = EmailVerification.objects.create(user=self.user, token='tok3', is_verified=True)
        EmailVerification.objects.filter(pk=v.pk).update(
            created_at=timezone.now() - timedelta(days=365)
        )
        v.refresh_from_db()
        self.assertFalse(v.is_expired())
