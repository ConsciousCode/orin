'''
Conslidate typing in one file.
'''

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Optional, override, overload, Any
from collections import defaultdict
import dataclasses
from dataclasses import dataclass

type json_value = None|bool|int|float|str|list[json_value]|dict[str, json_value]