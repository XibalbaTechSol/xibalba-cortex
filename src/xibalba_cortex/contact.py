"""Bounded public sales inquiries; no access to memory or account data."""
from __future__ import annotations

import os
import re
import threading
import time
from collections import defaultdict, deque
from urllib.parse import urlsplit

from .email_delivery import EmailDeliveryError, send_email


class ContactError(ValueError):
    def __init__(self, status: int, message: str):
        self.status = status
        super().__init__(message)


def same_origin(origin: str, host: str) -> bool:
    parsed = urlsplit(origin)
    return parsed.scheme in {'http', 'https'} and parsed.netloc == host and not parsed.path and not parsed.query and not parsed.fragment


class ContactInbox:
    def __init__(self):
        self._attempts = defaultdict(deque)
        self._lock = threading.Lock()

    def submit(self, data: dict, client: str) -> dict:
        now = time.monotonic()
        with self._lock:
            for key in list(self._attempts):
                if not self._attempts[key] or self._attempts[key][-1] <= now - 900:
                    del self._attempts[key]
            if client not in self._attempts and len(self._attempts) >= 10000:
                raise ContactError(429, 'Inquiry capacity reached. Please email us directly.')
            while self._attempts[client] and self._attempts[client][0] <= now - 900:
                self._attempts[client].popleft()
            if len(self._attempts[client]) >= 3:
                raise ContactError(429, 'Too many inquiries. Please try again later or email us directly.')
            self._attempts[client].append(now)
        if data.get('website'):
            return {'message': 'Inquiry received.'}
        values = {}
        for field, maximum in [('name', 120), ('email', 254), ('organization', 160), ('message', 5000)]:
            value = data.get(field, '')
            if not isinstance(value, str) or len(value.strip()) > maximum:
                raise ContactError(400, f'Invalid {field}.')
            values[field] = value.strip()
        if not values['name'] or len(values['message']) < 20:
            raise ContactError(400, 'Please include your name and a message of at least 20 characters.')
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', values['email']):
            raise ContactError(400, 'Please enter a valid email address.')
        recipient = os.environ.get('CORTEX_CONTACT_TO', 'jacob.v.universe@gmail.com').strip()
        body = '\n'.join([f'Name: {values["name"]}', f'Reply to: {values["email"]}',
            f'Organization: {values["organization"]}', '', values['message']])
        try:
            send_email(recipient, 'Cortex product inquiry', body)
        except EmailDeliveryError:
            raise ContactError(503, 'Your message could not be delivered. Please try again later or email us directly.') from None
        return {'message': 'Your inquiry has been sent. We will reply to your email.'}
