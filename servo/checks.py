import asyncio
import enum
import functools

from datetime import datetime
from hashlib import blake2b
from inspect import Signature, isclass
from typing import Awaitable, Callable, Coroutine, Dict, Iterable, Generator, List, Optional, Pattern, Protocol, Sequence, Set, Type, TypeVar, Tuple, Union, cast, get_args, get_origin, runtime_checkable

from pydantic import BaseModel, Extra, StrictStr, validator, constr
from servo.configuration import BaseConfiguration
from servo.types import Any, Duration
from servo.utilities.inspect import get_instance_methods

import loguru
from loguru import logger as default_logger


__all__ = [
    "BaseChecks",
    "Check",
    "CheckHandlerResult",
    "Filter",
    "HaltOnFailed",
    "check"
]


CheckHandlerResult = Union[bool, str, Tuple[bool, str], None]
CheckHandler = TypeVar("CheckHandler", Callable[..., CheckHandlerResult], Callable[..., Awaitable[CheckHandlerResult]])
CHECK_HANDLER_SIGNATURE = Signature(return_annotation=CheckHandlerResult)

Tag = constr(strip_whitespace=True, min_length=1, max_length=32, regex="^([0-9a-z\\.-])*$")


class Check(BaseModel):
    """
    Check objects represent the status of required runtime conditions.

    A check is an atomic verification that a particular aspect
    of a configuration is functional and ready for deployment. Connectors can
    have an arbitrary number of prerequisites and options that need to be
    checked within the runtime environment.

    Checks are used to verify the correctness of servo configuration before
    starting optimization and report on health and readiness during operation.
    """

    name: StrictStr
    """An arbitrary descriptive name of the condition being checked.
    """

    id: StrictStr = None
    """A short identifier for the check. Generated automatically if unset.
    """

    description: Optional[StrictStr]
    """An optional detailed description about the condition being checked.
    """

    required: bool = False
    """
    Indicates if the check is a pre-condition for subsequent checks.

    Required state is used to halt the execution of a sequence of checks
    that are part of a `Checks` object. For example, given a connector
    that connects to a remote service such as a metrics provider, you
    may wish to check that each metrics query is well formed and returns
    results. In order for any of the query checks to succeed, the servo
    must be able to connect to the service. During failure modes such as
    network partitions, service outage, or simple configuration errors
    this can result in an arbitrary number of failing checks with an 
    identical root cause that make it harder to identify the issue.
    Required checks allow you to declare these sorts of pre-conditions
    and the servo will test them before running any dependent checks,
    ensuring that you get a single failure that identifies the root cause.

    For checks that do not belong to a `Checks` object, required is
    purely advisory metadata and is ignored by the servo.
    """

    tags: Optional[Set[Tag]]
    """
    An optional set of tags for filtering checks.

    Tags are strings between 1 and 32 characters in length and may contain 
    only lowercase alphanumeric characters, hyphens '-', and periods '.'.
    """

    success: Optional[bool]
    """
    Indicates if the condition being checked was met or not. 
    """

    message: Optional[StrictStr]
    """
    An optional message describing the outcome of the check.

    The message is presented to users and should be informative. Long
    messages may be truncated on display.
    """

    exception: Optional[Exception]
    """
    An optional exception encountered while running the check.

    When checks encounter an exception condition, it is recommended to
    store the exception so that diagnostic metadata such as the stack trace 
    can be presented to the user.
    """
    
    created_at: datetime = None
    """When the check was created (set automatically).
    """

    run_at: Optional[datetime]
    """An optional timestamp indicating when the check was run.
    """

    runtime: Optional[Duration]
    """An optional duration indicating how long it took for the check to run.
    """

    @classmethod
    async def run(cls, 
        name: str, 
        *, 
        handler: CheckHandler, 
        description: Optional[str] = None,
        args: List[Any] = [],
        kwargs: Dict[Any, Any] = {}
    ) -> 'Check':
        """Runs a check handler and returns a Check object reporting the outcome.

        This method is useful for quickly implementing checks in connectors that
        do not have enough checkable conditions to warrant implementing a `Checks`
        subclass.

        The handler can be synchronous or asynchronous. An arbitrary number of positional 
        and keyword arguments are supported. The values for the argument must be provided 
        via the `args` and `kwargs` parameters. The handler must return a `bool`, `str`, 
        `Tuple[bool, str]`, or `None` value. Boolean values indicate success or failure 
        and string values are assigned to the `message` attribute of the Check object 
        returned. Exceptions are rescued, mark the check as a failure, and assigned to 
        the `exception` attribute.

        Args:
            name: A name for the check being run.
            handler: The callable to run to perform the check.
            args: A list of positional arguments to pass to the handler.
            kwargs: A dictionary of keyword arguments to pass to the handler.
            description: An optional detailed description about the check being run.

        Returns:
            A check object reporting the outcome of running the handler.
        """
        check = Check(name=name, description=description)
        await run_check_handler(check, handler, *args, **kwargs)
        return check

    @property
    def failed(self) -> bool:
        """
        Indicates if the check was unsuccessful.
        """
        return not self.success

    @validator("created_at", pre=True, always=True)
    @classmethod
    def _set_created_at_now(cls, v):
        return v or datetime.now()
    
    @validator("id", pre=True, always=True)
    @classmethod
    def _generated_id(cls, v,  values):        
        return v or blake2b(values["name"].encode('utf-8'), digest_size=4).hexdigest()
    
    class Config:
        validate_assignment = True
        arbitrary_types_allowed = True
        json_encoders = {
            Exception: lambda v: repr(v),
        }


@runtime_checkable
class Checkable(Protocol):
    """Checkable objects can be represented as a Check.
    """

    def __check__() -> Check:
        """Returns a Check representation of the object.
        """
        ...


CheckRunner = TypeVar("CheckRunner", Callable[..., Check], Coroutine[None, None, Check])

def check(
    name: str, 
    *, 
    description: Optional[str] = None,
    id: Optional[str] = None,
    required: bool = False,
    tags: Optional[List[str]] = None) -> Callable[[CheckHandler], CheckRunner]:
    """
    Transforms a function or method into a check.
    
    Checks are used to test the availability, readiness, and health of resources and
    services that used during optimization. The `Check` class models the status of a
    check that has been run. The `check` function is a decorator that transforms a
    function or method that returns a `bool`, `str`, `Tuple[bool, str]`, or `None` 
    into a check function or method.

    The decorator requires a `name` parameter to identify the check as well as an optional
    informative `description`, an `id` for succintly referencing the check, and a `required`
    boolean value that determines if a failure will halt execution of subsequent checks.
    The body of the decorated function is used to perform the business logic of running
    the check. The decorator wraps the original function body into a handler that runs the
    check and marshalls the value returned or exception caught into a `Check` representation.
    The `run_at` and `runtime` properties are automatically set, providing execution timing of
    the check. The signature of the transformed function is `() -> Check`.

    Args:
        name: Human readable name of the check.
        description: Optional additional details about the check.
        id: A short identifier for referencing the check (e.g. from the CLI interface).
        required: When True, failure of the check will halt execution of subsequent checks.
        tags: An optional list of tags for filtering checks. Tags may contain only lowercase
            alphanumeric characters, hyphens '-', and periods '.'.
    
    Returns:
        A decorator function for transforming a function into a check.
    
    Raises:
        TypeError: Raised if the signature of the decorated function is incompatible.
    """
    def decorator(fn: CheckHandler) -> CheckRunner:
        _validate_check_handler(fn)
        __check__ = Check(
            name=name, 
            description=description, 
            id=(id or fn.__name__),
            required=required,
            tags=tags,
        )

        if asyncio.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def run_check(*args, **kwargs) -> Check:
                check = __check__.copy()
                await run_check_handler(check, fn, *args, **kwargs)
                return check
        else:
            @functools.wraps(fn)
            def run_check(*args, **kwargs) -> Check:
                check = __check__.copy()
                run_check_handler_sync(check, fn, *args, **kwargs)
                return check

        # update the wrapped return signature conform with protocol
        run_check.__check__ = __check__
        run_check.__annotations__['return'] = Check
        return cast(CheckRunner, run_check)

    return decorator


CHECK_SIGNATURE = Signature(return_annotation=Check)
CHECK_SIGNATURE_ANNOTATED = Signature(return_annotation='Check')


class Filter(BaseModel):
    """Filter objects are used to select a subset of available checks for execution.
    
    Specific checks can be targetted for execution using the metadata attributes of `name`,
    `id`, and `tags`. Metadata filters are evaluated using AND semantics. Names and ids
    are matched case-sensitively. Tags are always lowercase. Names and ids can be targetted 
    using regular expression patterns.
    """

    name: Union[None, str, Sequence[str], Pattern[str]] = None
    """A name, sequence of names, or regex pattern for selecting checks by name.
    """

    id: Union[None, str, Sequence[str], Pattern[str]] = None
    """A name, sequence of names, or regex pattern for selecting checks by name.
    """

    tags: Optional[Set[str]] = None
    """A set of tags for selecting checks to be run. Checks matching any tag in the set
    are selected.
    """

    @property
    def any(self) -> bool:
        """Returns true if any constraints are in effect.
        """
        return not self.empty
    
    @property
    def empty(self) -> bool:
        """Return true if no constraints are in effect.
        """
        return bool(
            self.name is None 
            and self.id is None 
            and self.tags is None
        )
    
    def matches(self, check: Check) -> bool:
        """Matches a check against the filter.

        Args:
            check: The check to match against the filter.

        Returns:
            bool: True if the check meets the name, id, and tags constraints.
        """
        if self.empty:
            return True

        return (                    
            self._matches_name(check)
            and self._matches_id(check)
            and self._matches_tags(check)
        )

    def _matches_name(self, check: Check) -> bool:
        return self._matches_str_attr(self.name, check.name)
    
    def _matches_id(self, check: Check) -> bool:
        return self._matches_str_attr(self.id, check.id)
    
    def _matches_tags(self, check: Check) -> bool:
        if self.tags is None:
            return True
        
        # exclude untagged checks if filtering by tag
        if check.tags is None:
            return False
        
        # look for an intersection in our sets
        return bool(self.tags.intersection(check.tags))
    
    def _matches_str_attr(
        self, 
        attr: Union[None, str, Sequence[str], Pattern[str]],
        value: str
    ) -> bool:
        if attr is None:
            return True
        elif isinstance(attr, str):
            return value == attr
        elif isinstance(attr, Sequence):
            return value in attr
        elif isinstance(attr, Pattern):
            return bool(attr.search(value))
        else:
            raise ValueError(f"unexpected value of type \"{attr.__class__.__name__}\": {attr}")

    class Config:
        arbitrary_types_allowed = True

class HaltOnFailed(str, enum.Enum):
    """HaltOnFailed is an enumeration that describes how to handle check failures.
    """

    requirement = "requirement"
    """Halt running when a required check has failed.
    """

    check = "check"
    """Halt running when any check has failed.
    """

    never = "never"
    """Never halt running regardless of check failures.
    """


class BaseChecks(BaseModel):
    """
    Base class for collections of Check objects.

    This is a convenience class for quickly and cleanly implementing checks
    for a connector. A check is an atomic verification that a particular aspect
    of a configuration is functional and ready for deployment. Connectors can
    have an arbitrary number of prerequisites and options that need to be
    checked within the runtime environment. The BaseChecks class provides a simple 
    inheritance based interface for implementing an arbitrary number of checks.
    
    Checks are implemented through standard instance methods that are prefixed
    with `check_`, accept no arguments, and return an instance of `Check`. The method
    body tests a single aspect of the configuration (rescuing exceptions as necessary)
    and returns a `Check` object that models the results of the check performed.

    Checks are executed in method definition order within the subclass (top to bottom).
    Check methods can be implemented synchronously or asynchronously. Methods that are
    declared as coroutines via the `async def` syntax are run asynchronously.

    By default, check execution is halted upon encountering a failure. This behavior
    allows the developer to assume that the runtime environment described by preceding
    checks has been established and implement a narrowly scoped check. Halting execution
    can be overridden via the boolean `all` argument to the `run` class method entry point 
    or by setting the `required` attribute of the returned `Check` instance to `False`.

    Args:
        config: The configuration object for the connector being checked.
    """
    
    config: BaseConfiguration
    """The configuration object for the connector being checked.
    """

    @classmethod
    async def run(cls, 
        config: BaseConfiguration, 
        filter_: Optional[Filter] = None,
        *, 
        logger: 'loguru.Logger' = default_logger,        
        halt_on: HaltOnFailed = HaltOnFailed.requirement
    ) -> List[Check]:
        """
        Runs checks and returns a list of Check objects reflecting the results.

        Checks are implemented as instance methods prefixed with `check_` that return a `Check`
        object. Please refer to the `BaseChecks` class documentation for details.

        Args:
            config: The connector configuration to initialize the checks instance with.
            filter_: An optional filter to limit the set of checks that are run.
            logger: The logger to write messages to.            
            halt_on: The type of check failure that should halt the run.
        
        Returns:
            A list of `Check` objects that reflect the outcome of the checks executed.
        """
        return await cls(config, logger=logger).run_(filter_=filter_, halt_on=halt_on)

    async def run_(self,         
        filter_: Optional[Filter] = None,
        *, 
        halt_on: HaltOnFailed = HaltOnFailed.requirement
    ) -> List[Check]:
        """
        Runs checks and returns the results.

        Args:
            logger: An optional filter to limit the set of checks that are run.
            halt_on: The type of check failure that should halt the run.
        
        Returns:
            A list of checks that were run.
        """
        
        # identify methods that match the filter
        filtered_methods  = []
        for method_name, method in self.check_methods():
            if filter_ and filter_.any:
                if isinstance(method, Checkable):
                    spec = method.__check__
                else:
                    self.logger.warning(f"filtering requested but encountered non-filterable check method \"{method_name}\"")
                    continue
                
                if not filter_.matches(spec):
                    continue
            
            filtered_methods.append(method)
        
        # iterate a second time to run filtered and required checks
        checks = []
        for method_name, method in self.check_methods():
            if method in filtered_methods:
                filtered_methods.remove(method)            
            else:
                spec = getattr(method, '__check__', None)
                if spec:
                    # once all filtered methods are removed, only run non-decorated
                    if not spec.required or not filtered_methods:
                        continue
            
            check = (
                await method() if asyncio.iscoroutinefunction(method)
                else method()
            )
            if not isinstance(check, Check):
                raise TypeError(f"check methods must return `Check` objects: `{method_name}` returned `{check.__class__.__name__}`")
            
            checks.append(check)            

            # halt the run if necessary
            if check.failed:
                if (halt_on == HaltOnFailed.check 
                or (halt_on == HaltOnFailed.requirement and check.required)):
                    break
        
        return checks
    
    @property
    def logger(self) -> 'loguru.Logger':
        return self.__dict__["logger"]
    
    def check_methods(self) -> Generator[Tuple[str, CheckRunner], None, None]:
        """
        Enumerates all check methods and yields the check method names and callable instances 
        in method definition order.

        Check method names are prefixed with "check_", accept no parameters, and return a
        `Check` object reporting the outcome of the check operation.
        """
        for name, method in get_instance_methods(self, stop_at_parent=BaseChecks).items():
            if name.startswith("_") or name in ("run_", "check_methods"):
                continue
            
            if not name.startswith(("_", "check_")):
                raise ValueError(f'invalid method name "{name}": method names of Checks subtypes must start with "_" or "check_"')
            
            sig = Signature.from_callable(method)
            if sig not in (CHECK_SIGNATURE, CHECK_SIGNATURE_ANNOTATED):
                raise TypeError(f'invalid signature for method "{name}": expected {repr(CHECK_SIGNATURE)}, but found {repr(sig)}')
            
            yield (name, method)

    
    def __init__(self, config: BaseConfiguration, *, logger: 'loguru.Logger' = default_logger, **kwargs) -> None:
        super().__init__(config=config, logger=logger, **kwargs)
    
    class Config:
        arbitrary_types_allowed = True
        extra = Extra.allow


def _validate_check_handler(fn: CheckHandler) -> None:
    """
    Validates that a function or method is usable as a check handler.

    Check handlers accept no arguments and return a `bool`, `str`, 
    `Tuple[bool, str]`, or `None`.

    Args:
        fn: The check handler to be validated.
    
    Raises:
        TypeError: Raised if the handler function is invalid.
    """
    signature = Signature.from_callable(fn)
    if len(signature.parameters) >= 1:
        for param in signature.parameters.values():
            if param.name == "self" and param.kind == param.POSITIONAL_OR_KEYWORD:
                continue

            raise TypeError(f"invalid check handler \"{fn.__name__}\": unexpected parameter \"{param.name}\" in signature {repr(signature)}, expected {repr(CHECK_HANDLER_SIGNATURE)}")

    error = TypeError(f"invalid check handler \"{fn.__name__}\": incompatible return type annotation in signature {repr(signature)}, expected to match {repr(CHECK_HANDLER_SIGNATURE)}")
    acceptable_types = set(get_args(CheckHandlerResult))
    origin = get_origin(signature.return_annotation)
    args = get_args(signature.return_annotation)
    if origin is not None:
        if origin == Union:
            handler_types = set(args)
            if handler_types - acceptable_types:
                raise error
        elif origin is tuple:
            if args != (bool, str):
                raise error
        else:
            raise error
    else:
        cls = signature.return_annotation if isclass(signature.return_annotation) else signature.return_annotation.__class__
        if not cls in acceptable_types:
            raise error


async def run_check_handler(check: Check, handler: CheckHandler, *args, **kwargs) -> None:
    """Runs a check handler and records the result into a Check object.

    Args:
        check: The check to record execution results.
        handler: A callable handler to perform the check.
        args: A list of positional arguments to pass to the handler.
        kwargs: A dictionary of keyword arguments to pass to the handler.

    Raises:
        ValueError: Raised if an invalid value is returned by the handler.
    """
    try:
        check.run_at = datetime.now()
        if asyncio.iscoroutinefunction(handler):
            result = await handler(*args, **kwargs)
        else:
            result = handler(*args, **kwargs)
        _set_check_result(check, result)
    except Exception as error:
        _set_check_result(check, error)
    finally:
        check.runtime = Duration(datetime.now() - check.run_at)

def run_check_handler_sync(check: Check, handler: CheckHandler, *args, **kwargs) -> None:
    """Runs a check handler and records the result into a Check object.

    Args:
        check: The check to record execution results.
        handler: A callable handler to perform the check.
        args: A list of positional arguments to pass to the handler.
        kwargs: A dictionary of keyword arguments to pass to the handler.

    Raises:
        ValueError: Raised if an invalid value is returned by the handler.
    """
    try:
        check.run_at = datetime.now()
        _set_check_result(check, handler(*args, **kwargs))
    except Exception as error:
        _set_check_result(check, error)
    finally:
        check.runtime = Duration(datetime.now() - check.run_at)

def _set_check_result(check: Check, result: Union[None, bool, str, Tuple[bool, str], Exception]) -> None:
    """Sets the result of a check handler run on a check instance."""
    check.success = True
        
    if isinstance(result, str):
        check.message = result
    elif isinstance(result, bool):
        check.success = result
    elif isinstance(result, tuple):
        check.success, check.message = result
    elif result is None:
        pass
    elif isinstance(result, Exception):
        check.success = False
        check.exception = result
        check.message = f"caught exception: {repr(result)}"
        default_logger.exception("error", exception=result)
    else:
        raise ValueError(f"check method returned unexpected value of type \"{result.__class__.__name__}\"")
    

def create_checks_from_iterable(handler: CheckHandler, iterable: Iterable, *, base_class: Type[BaseChecks] = BaseChecks) -> BaseChecks:
    """Returns a class wrapping each item in an iterable collection into check instance methods. 

    Building a checks subclass implementation with this function is semantically equivalent to 
    iterating through every item in the collection, defining a new `check_` prefixed method,
    and passing the item and the handler to the `run_check_handler` function.

    Some connector types such as metrics system integrations wind up exposing collections
    of homogenously typed settings within their configuration. The canonical example is a
    collection of queries against Prometheus. Each query really should be validated for 
    correctness early and often, but this can become challenging to manage, audit, and enforce
    as the collection grows and entropy increases. Key challenges include non-obvious 
    evolution within the collection and developer fatigue from boilerplate code maintenance.
    This function provides a remedy for these issues by wrapping these sorts of collections into
    fully featured classes that are integrated into the servo checks system.

    Args:
        handler: A callable for performing a check given a single element input.
        iterable: An iterable collection of checkable items to be wrapped into check methods.
        base_class: The base class for the new checks subclass. Enables mixed mode checks where
            some are written by hand and others a are generated.

    Returns:
        A new subclass of `BaseChecks` with instance method check implememntatiomns for each
        item in the `iterable` argument collection.
    """
    cls = type("_IterableChecks", (base_class,), {})

    def create_fn(name, item):
        async def fn(self) -> Check:
            check = fn.__check__.copy()
            await run_check_handler(check, handler, item)
            return check

        return fn

    for item in iterable:
        if isinstance(item, Checkable):
            check = item.__check__().copy()
            fn = create_fn(check.name, item)
            fn.__check__ = check
        else:
            name = item.name if hasattr(item, 'name') else str(item)
            check = Check(name=f"Check {name}")
            fn = create_fn(name, item)            
            fn.__check__ = check
        
        method_name = f"check_{check.id}"
        setattr(cls, method_name, fn)
    
    return cls