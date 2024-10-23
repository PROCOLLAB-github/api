from django.conf import settings
from django.core.mail import EmailMessage
from django.template.loader import render_to_string

from weasyprint import HTML

from procollab.celery import app
from procollab.settings import EMAIL_USER
from users.typing import UserCVDataV2
from users.services.cv_data_prepare import UserCVDataPreparerV2


@app.task
def send_mail_cv(user_id: int, user_email: str, filename: str):
    """Sending mail CV.pdf account owner."""
    data_preparer = UserCVDataPreparerV2(user_id)
    user_cv_data: UserCVDataV2 = data_preparer.get_prepared_data()

    html_string: str = render_to_string(
        data_preparer.TEMPLATE_PATH, user_cv_data
    )
    binary_pdf_file: bytes | None = HTML(string=html_string).write_pdf()

    with open(settings.BASE_DIR / "templates/email/email_cv.html", encoding="utf-8") as f:
        template_content = f.read()

    email = EmailMessage(
        subject="Procollab | Резюме",
        body=template_content,
        from_email=EMAIL_USER,
        to=[user_email],
    )
    email.content_subtype = "html"
    email.attach(
        filename=f"{filename}.pdf",
        content=binary_pdf_file,
        mimetype="application/pdf",
    )
    email.send(fail_silently=False)
