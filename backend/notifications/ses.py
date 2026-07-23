"""Thin Amazon SES wrapper (boto3). Credentials come from the standard AWS
credential chain: env vars, shared config, or an IAM role."""
from django.conf import settings


def send_ses_email(subject, html_body, text_body, to_addresses, from_address=None):
    import boto3  # imported lazily so the app runs without boto3 when using SMTP

    client = boto3.client("ses", region_name=settings.AWS_SES_REGION)
    kwargs = {
        "Source": from_address or settings.DEFAULT_FROM_EMAIL,
        "Destination": {"ToAddresses": list(to_addresses)},
        "Message": {
            "Subject": {"Data": subject, "Charset": "UTF-8"},
            "Body": {
                "Html": {"Data": html_body, "Charset": "UTF-8"},
                "Text": {"Data": text_body, "Charset": "UTF-8"},
            },
        },
    }
    if settings.AWS_SES_CONFIGURATION_SET:
        kwargs["ConfigurationSetName"] = settings.AWS_SES_CONFIGURATION_SET
    return client.send_email(**kwargs)
