from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import DataRequired, Length, Email, ValidationError, EqualTo


def wells_fargo_email(form, field):
    if not field.data:
        return
    if not field.data.lower().endswith("@wellsfargo.com"):
        raise ValidationError("Email must be a @wellsfargo.com address.")


class LoginForm(FlaskForm):
    identifier = StringField("Email or EID", validators=[
                             DataRequired(), Length(max=255)])
    password = PasswordField("Password", validators=[
                             DataRequired(), Length(min=8, max=128)])
    submit = SubmitField("Login")


class SignupForm(FlaskForm):
    jira_pat = PasswordField("Jira Personal Access Token", validators=[
                             DataRequired(), Length(max=56)])
    email = StringField("Company Email", validators=[
                        DataRequired(), Email(), wells_fargo_email, Length(max=255)])
    submit = SubmitField("Validate & Signup")


class ConfirmProfileForm(FlaskForm):
    submit = SubmitField("Confirm Profile")


class SetPasswordForm(FlaskForm):
    password = PasswordField("Password", validators=[
                             DataRequired(), Length(min=8, max=128)])
    confirm_password = PasswordField(
        "Confirm Password",
        validators=[DataRequired(), EqualTo(
            "password", message="Passwords must match.")]
    )
    submit = SubmitField("Create Account")
