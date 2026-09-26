import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

spec = importlib.util.spec_from_file_location('token_reset', Path(__file__).resolve().parents[2] / 'backend/reset_liveswitch_access_token.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def failure(code):
    return ClientError({'Error': {'Code': code}}, 'SSM')


def test_reset_only_deletes_access_override_once():
    ssm = MagicMock()
    ssm.get_parameter.side_effect = failure('ParameterNotFound')
    assert module.reset_access_token(ssm, '/moving-crm/dev')
    ssm.delete_parameter.assert_called_once_with(Name='/moving-crm/dev/LIVESWITCH_ACCESS_TOKEN')
    ssm.get_parameter.side_effect = None
    assert not module.reset_access_token(ssm, '/moving-crm/dev')
    assert ssm.delete_parameter.call_count == 1


def test_reset_does_not_hide_permission_errors():
    ssm = MagicMock()
    ssm.get_parameter.side_effect = failure('ParameterNotFound')
    ssm.delete_parameter.side_effect = failure('AccessDeniedException')
    with pytest.raises(ClientError):
        module.reset_access_token(ssm, '/moving-crm/prod')
    ssm.put_parameter.assert_not_called()
