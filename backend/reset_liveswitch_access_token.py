"""One-time deployment reset of the legacy LiveSwitch access-token override."""
import os

import boto3
from botocore.exceptions import ClientError


def reset_access_token(ssm, prefix):
    prefix = prefix.rstrip('/')
    marker = prefix + '/LIVESWITCH_ACCESS_RESET_20260926'
    try:
        ssm.get_parameter(Name=marker)
        return False
    except ClientError as exc:
        if exc.response['Error']['Code'] != 'ParameterNotFound':
            raise
    try:
        ssm.delete_parameter(Name=prefix + '/LIVESWITCH_ACCESS_TOKEN')
    except ClientError as exc:
        if exc.response['Error']['Code'] != 'ParameterNotFound':
            raise
    ssm.put_parameter(Name=marker, Value='complete', Type='String', Overwrite=True)
    return True


if __name__ == '__main__':
    environment = os.environ.get('ENVIRONMENT', 'dev')
    if environment not in ('dev', 'prod'):
        raise ValueError('Unsupported deployment environment')
    changed = reset_access_token(boto3.client('ssm'), f'/moving-crm/{environment}')
    print('LiveSwitch access-token override removed; OAuth refresh authorization preserved.'
          if changed else 'LiveSwitch access-token reset already completed.')
