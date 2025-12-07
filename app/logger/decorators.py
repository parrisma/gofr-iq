import functools
import time
from typing import Any, Callable, TypeVar, cast
from app.logger import session_logger

F = TypeVar("F", bound=Callable[..., Any])

def log_execution_time(func: F) -> F:
    """Decorator to log execution time and arguments of a function.
    
    Logs:
    - Start of execution with arguments (truncated if too large)
    - End of execution with duration
    - Exceptions if they occur
    """
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        func_name = func.__name__
        
        # Sanitize/Truncate args for logging
        safe_args = []
        for arg in args:
            s_arg = str(arg)
            if len(s_arg) > 1000:
                safe_args.append(s_arg[:1000] + "...(truncated)")
            else:
                safe_args.append(s_arg)
                
        safe_kwargs = {}
        for k, v in kwargs.items():
            s_v = str(v)
            if len(s_v) > 1000:
                safe_kwargs[k] = s_v[:1000] + "...(truncated)"
            else:
                safe_kwargs[k] = s_v

        session_logger.debug(f"Starting {func_name}", args=safe_args, kwargs=safe_kwargs)
        
        start_time = time.perf_counter()
        try:
            result = func(*args, **kwargs)
            duration = time.perf_counter() - start_time
            
            session_logger.info(
                f"Completed {func_name}", 
                duration_seconds=round(duration, 4),
                success=True
            )
            return result
        except Exception as e:
            duration = time.perf_counter() - start_time
            session_logger.error(
                f"Failed {func_name}",
                duration_seconds=round(duration, 4),
                error=str(e),
                error_type=type(e).__name__,
                success=False
            )
            raise
            
    return cast(F, wrapper)
