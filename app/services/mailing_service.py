import smtplib
import random
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from app.core import config

# OTP generation function
async def generate_otp(length=6):
    return ''.join([str(random.randint(0, 9)) for _ in range(length)])

# Email sending function
async def send_password_reset_email(receiver_email, user_name, otp):
    sender_email = config.SENDER_EMAIL  # Use the sender email from config
    sender_password = config.EMAIL_PASSWORD  # Use app-specific password if needed

    # otp = generate_otp()

    subject = "Reset Your Password – OTP Inside"
    body = f"""
    Dear {user_name},

    We received a request to reset your password.

    Please use the following One-Time Password (OTP) to proceed:

    🔐 OTP: {otp}

    This OTP is valid for the next 10 minutes.

    If you didn’t request this, you can safely ignore this email.

    Best regards,
    Your Company Name
    """

    # Compose the email
    msg = MIMEMultipart()
    msg["From"] = sender_email
    msg["To"] = receiver_email
    msg["Subject"] = subject

    msg.attach(MIMEText(body, "plain"))

    try:
        # Connect to the SMTP server
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender_email, sender_password)
            server.send_message(msg)
        print("Email sent successfully.")
        return True
    except Exception as e:
        print(f"Failed to send email: {e}")
        return False

# Example usage
# otp = generate_otp()
# send_password_reset_email("recipient@example.com", "John Doe", otp)
