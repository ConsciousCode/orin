'''
Consolidate typing in one file.
'''

from abc import ABC, abstractmethod
from typing import Optional, override, overload, Any, Iterable, Iterator, Literal, Optional, Union, TypeVar, Generic, Callable, Awaitable, AsyncIterator, AsyncGenerator, Mapping, get_args, get_origin, cast, TYPE_CHECKING, TypeGuard, Protocol, IO
from collections import defaultdict
import dataclasses
from dataclasses import dataclass, field
from os import PathLike

type json_value = None|bool|int|float|str|list[json_value]|dict[str, json_value]