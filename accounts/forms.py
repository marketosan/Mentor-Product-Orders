"""Forms for the user admin page. Admin-only -- nobody self-registers."""

from django import forms
from django.contrib.auth import password_validation

from .models import User


class _PasswordFieldsMixin:
    """Two password boxes that must agree and survive Django's validators.

    Written by hand rather than reusing UserCreationForm so the same code can
    serve creation (password required) and editing (blank means unchanged).
    """

    password_required = True

    def _clean_password_pair(self):
        first = self.cleaned_data.get("password1", "")
        second = self.cleaned_data.get("password2", "")

        if not first and not second:
            if self.password_required:
                raise forms.ValidationError("Give the new user a password.")
            return ""  # editing, and the box was left alone

        if first != second:
            raise forms.ValidationError("The two passwords do not match.")

        # Checks length, commonness and similarity to the username, using the
        # validators already configured in settings.
        password_validation.validate_password(first, self.instance)
        return first


class UserFormBase(_PasswordFieldsMixin, forms.ModelForm):
    password1 = forms.CharField(label="Password", required=False, widget=forms.PasswordInput)
    password2 = forms.CharField(label="Confirm password", required=False, widget=forms.PasswordInput)

    class Meta:
        model = User
        fields = ["username", "email", "role"]

    def __init__(self, *args, editor=None, **kwargs):
        """`editor` is whoever is filling the form in, needed for the two rules
        that depend on who is acting rather than on the values alone.
        """
        super().__init__(*args, **kwargs)
        self.editor = editor

    def clean_email(self):
        # Unique on the model, but case-sensitively; two accounts differing only
        # in capitalisation would be one mailbox in practice.
        email = self.cleaned_data["email"].strip()
        clash = User.objects.filter(email__iexact=email)
        if self.instance.pk:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise forms.ValidationError("Another account already uses that email.")
        return email

    def clean(self):
        cleaned = super().clean()
        self.cleaned_password = self._clean_password_pair()
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        if self.cleaned_password:
            user.set_password(self.cleaned_password)
        if commit:
            user.save()
        return user


class NewUserForm(UserFormBase):
    password_required = True


class EditUserForm(UserFormBase):
    """Editing an existing account. The password box is optional here: leaving
    it blank keeps whatever the user already has.
    """

    password_required = False

    def clean_role(self):
        role = self.cleaned_data["role"]
        if role == User.Role.ADMIN or not self.instance.pk:
            return role

        # Demoting to employee -- the two ways that can go wrong.
        if self.editor and self.instance.pk == self.editor.pk:
            raise forms.ValidationError(
                "You cannot remove your own admin role. Ask another admin to do it."
            )
        if self.instance.is_last_admin():
            raise forms.ValidationError(
                "This is the only admin left. Promote someone else first."
            )
        return role
