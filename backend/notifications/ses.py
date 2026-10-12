"""Thin Amazon SES wrapper (boto3). Credentials come from the standard AWS
credential chain: env vars, shared config, or an IAM role."""
from django.conf import settings

#: Seconds to make the connection and to wait for the answer. boto3's own
#: defaults are a minute for each with up to five attempts, so a service that
#: does not answer would hold the request that sends a message for minutes. A
#: message is tried once: a retry after a slow answer could send it twice.
CONNECT_TIMEOUT = 5
READ_TIMEOUT = 15


def client_config():
    from botocore.config import Config  # with boto3, so imported with it

    return Config(connect_timeout=CONNECT_TIMEOUT, read_timeout=READ_TIMEOUT,
                  retries={"total_max_attempts": 1})


def send_ses_email(subject, html_body, text_body, to_addresses, from_address=None):
    import boto3  # imported lazily so the app runs without boto3 when using SMTP

    client = boto3.client("ses", region_name=settings.AWS_SES_REGION, config=client_config())
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
