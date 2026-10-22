"""Transport-independent device isolation. Callers must authenticate before use.

This module does not capture screens, authenticate network clients or emit HID.
A consumed command means dispatched, never proof of successful phone execution.
"""
from copy import deepcopy
from threading import RLock
from time import monotonic
from uuid import uuid4


class Sessions:
    def __init__(self, clock=monotonic, max_age=5.0):
        if max_age <= 0:
            raise ValueError('max_age must be positive')
        self.clock = clock
        self.max_age = max_age
        self._devices = {}
        self._lock = RLock()

    def register(self, phone, board):
        with self._lock:
            if not phone or not board:
                raise ValueError('phone and board are required')
            if phone in self._devices or any(d['board'] == board for d in self._devices.values()):
                raise ValueError('phone or board already bound')
            self._devices[phone] = {'board': board, 'frame': None, 'at': 0, 'pending': None}

    def observe(self, phone):
        """Issue an ID only after the capture adapter receives a fresh frame."""
        with self._lock:
            device = self._devices[phone]
            device.update(frame=uuid4().hex, at=self.clock(), pending=None)
            return device['frame']

    def submit(self, phone, frame, action):
        with self._lock:
            device = self._devices[phone]
            if frame is None or frame != device['frame'] or self.clock() - device['at'] >= self.max_age:
                raise ValueError('stale or missing frame')
            if device['pending'] is not None:
                raise ValueError('command already pending')
            device['pending'] = {'id': uuid4().hex, 'frame': frame,
                                 'action': deepcopy(action), 'expires': device['at'] + self.max_age}
            # A frame may authorize only one command; observe again for the next.
            device['frame'] = None

    def take(self, phone, board):
        with self._lock:
            device = self._devices[phone]
            if device['board'] != board:
                raise PermissionError('board does not belong to this phone')
            command = device['pending']
            device['pending'] = None
            if command is None or self.clock() >= command['expires']:
                return None
            return command

    def stop(self, phone):
        """Invalidate work; the HID adapter must additionally release held inputs."""
        with self._lock:
            self._devices[phone].update(frame=None, pending=None)
