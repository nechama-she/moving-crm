"""Checks an address selection signed for this move."""
import os

import jwt
from fastapi import HTTPException



def validate_selection(selection, access_id):
    try:
        claims = jwt.decode(selection.proof or '', os.environ['JWT_SECRET'], algorithms=['HS256'],
            audience='customer-address', options={'require': ['exp', 'sub', 'address']})
        if claims['sub'] != access_id or claims['address'] != selection.model_dump(exclude={'proof'}):
            raise ValueError('Selection changed')
    except (jwt.PyJWTError, ValueError):
        raise HTTPException(400, 'Please select the address suggestion again before saving.') from None
