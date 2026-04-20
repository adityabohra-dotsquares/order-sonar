import os
from loguru import logger
from celery_app import email_app

CELERY_EMAIL_TASK_NAME = os.getenv(
    "CELERY_EMAIL_TASK_NAME", "adminuser.accounts.tasks.send_email_template_task"
)


def send_template_email(trigger: str, context_data: dict):
    """
    Triggers the email sending task on the Admin system's Celery broker.
    """
    try:
        # Trigger the task asynchronously on the separate Redis broker
        email_app.send_task(
            CELERY_EMAIL_TASK_NAME,
            kwargs={
                "trigger": trigger,
                "context_data": context_data,
            },
        )
        logger.info(f"Email task '{CELERY_EMAIL_TASK_NAME}' triggered via Celery ")

    except Exception as e:
        logger.error(f"Failed to trigger email task via Celery: {e}")
