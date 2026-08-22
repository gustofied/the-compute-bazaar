from collections import Counter, defaultdict, deque
from contextlib import contextmanager
from functools import wraps
import json
from pathlib import Path
import re
from typing import Iterator


# -----------------------------------------------------------------------------
# 1. Strings: strip, split, join, replace, formatting
# -----------------------------------------------------------------------------

text = "  gpu-1 ERROR 95\n"

clean_text = text.strip()
server, status, usage_text = clean_text.split()
usage = int(usage_text)

words = ["gpu-1", "ERROR", "95"]
joined = " ".join(words)

# strip("ad") removes any a/d characters from both ends.
# It does not remove the exact substring "ad".
name = "adamsdam"
without_prefix = name.removeprefix("ad")
without_suffix = name.removesuffix("dam")

message = f"{server} has {usage:.1f}% usage"


# -----------------------------------------------------------------------------
# 2. Lists, tuples, sets and dictionaries
# -----------------------------------------------------------------------------

numbers = [1, 3, 4, 5, 6]

server_record = ("gpu-1", 80)

unique_numbers = set(numbers)

scores: dict[str, int] = {
    "Bob": 102,
    "James": 42,
    "Sarah": 34,
}

# Raises KeyError if missing
bob_score = scores["Bob"]

# Returns a safe default if missing
unknown_score = scores.get("Unknown", 0)

# Add or update
scores["Adam"] = 75

# Iterate over dictionary keys and values
for person, score in scores.items():
    pass


# Useful set operations

active = {"gpu-1", "gpu-2"}
healthy = {"gpu-2", "gpu-3"}

both = active & healthy
either = active | healthy
only_active = active - healthy


# -----------------------------------------------------------------------------
# 3. Comprehensions, enumerate and zip
# -----------------------------------------------------------------------------

large_plus_one = [x + 1 for x in numbers if x > 3]

squares = {
    x: x**2
    for x in numbers
}

indexed_numbers = list(enumerate(numbers))

names = ["gpu-1", "gpu-2", "gpu-3"]
loads = [80, 40, 95]

paired = list(zip(names, loads))


# -----------------------------------------------------------------------------
# 4. Functions, return values, *args and **kwargs
# -----------------------------------------------------------------------------

def calculate_total(values: list[int]) -> int:
    """Return the total instead of only printing it."""
    return sum(values)


def add_all(*values: int) -> int:
    """*args collects positional arguments into a tuple."""
    return sum(values)


def describe_server(name: str, **details: object) -> str:
    """**kwargs collects named arguments into a dictionary."""

    formatted = ", ".join(
        f"{key}={value}"
        for key, value in details.items()
    )

    return f"{name}: {formatted}"


# -----------------------------------------------------------------------------
# 5. HackerRank input parsing
# -----------------------------------------------------------------------------

def read_space_separated_integers() -> list[int]:
    """
    Input:
        10 20 30

    Result:
        [10, 20, 30]
    """

    return list(map(int, input().split()))


def read_n_lines() -> list[str]:
    """
    Input:
        3
        first
        second
        third
    """

    n = int(input())

    return [
        input().strip()
        for _ in range(n)
    ]


# Another common HackerRank pattern

def read_one_integer_per_line() -> list[int]:
    n = int(input())
    numbers = []

    for _ in range(n):
        number = int(input())
        numbers.append(number)

    return numbers


# -----------------------------------------------------------------------------
# 6. Sorting
# -----------------------------------------------------------------------------

servers = [
    ("gpu-1", 80),
    ("gpu-2", 40),
    ("gpu-3", 95),
]


# Sort by the second tuple value, descending

servers_by_load = sorted(
    servers,
    key=lambda item: item[1],
    reverse=True,
)


# Sort score descending, then name alphabetically

scores_ranked = sorted(
    scores.items(),
    key=lambda item: (-item[1], item[0].lower()),
)


# list.sort() changes the existing list and returns None

servers_copy = servers.copy()
servers_copy.sort(key=lambda item: item[1])


# sorted() returns a new list

new_sorted_list = sorted(servers)


# -----------------------------------------------------------------------------
# 7. Counter, defaultdict and deque
# -----------------------------------------------------------------------------

levels = [
    "error",
    "info",
    "error",
    "warning",
    "error",
]


# Counter counts repeated values

level_counts = Counter(levels)

print(level_counts["error"])
# 3

most_common_levels = level_counts.most_common()

print(most_common_levels)
# [('error', 3), ('info', 1), ('warning', 1)]


# defaultdict is useful for grouping values

events = [
    ("gpu-1", "error"),
    ("gpu-2", "info"),
    ("gpu-1", "warning"),
]

events_by_server: defaultdict[str, list[str]] = defaultdict(list)

for event_server, event_level in events:
    events_by_server[event_server].append(event_level)

print(dict(events_by_server))

# {
#     'gpu-1': ['error', 'warning'],
#     'gpu-2': ['info']
# }


# deque is an efficient queue

queue: deque[str] = deque(["job-1", "job-2"])

queue.append("job-3")

first_job = queue.popleft()

print(first_job)
# job-1


# -----------------------------------------------------------------------------
# 8. Exceptions
# -----------------------------------------------------------------------------

def parse_percentage(raw_value: str) -> int:
    try:
        parsed = int(raw_value)

    except ValueError as error:
        raise ValueError(
            "percentage must be an integer"
        ) from error

    if not 0 <= parsed <= 100:
        raise ValueError(
            "percentage must be between 0 and 100"
        )

    return parsed


# try/except/else/finally example

def parse_number(text: str) -> int | None:
    try:
        number = int(text)

    except ValueError:
        print("Invalid number")
        return None

    else:
        print("Conversion succeeded")
        return number

    finally:
        print("Conversion attempt finished")


# Avoid assert for user or data validation.
# Assertions can be disabled.

def require_dictionary(data: object) -> dict:
    if not isinstance(data, dict):
        raise TypeError(
            "data must be a dictionary"
        )

    return data


# -----------------------------------------------------------------------------
# 9. Regular expressions
# -----------------------------------------------------------------------------

log_line = "2026-08-19 gpu-12 ERROR port=8080"


# Search for one match

gpu_match = re.search(
    r"gpu-(\d+)",
    log_line,
)

if gpu_match:
    gpu_number = int(gpu_match.group(1))
else:
    gpu_number = None


# Find every number

all_numbers = re.findall(
    r"\d+",
    log_line,
)


# Check whether the entire string matches

valid_server = re.fullmatch(
    r"gpu-\d+",
    "gpu-123",
)


# Replace using regex

cleaned_log = re.sub(
    r"\d+",
    "<number>",
    log_line,
)


# -----------------------------------------------------------------------------
# 10. Files
# -----------------------------------------------------------------------------

def read_file_examples(path: Path) -> None:
    # Read the entire file as one string

    with path.open() as file:
        content = file.read()
        print(content)

    # Read one line

    with path.open() as file:
        first_line = file.readline()
        print(first_line, end="")

    # Process the file one line at a time

    with path.open() as file:
        for line in file:
            print(line.rstrip("\n"))


def transform_file(
    input_path: Path,
    output_path: Path,
) -> None:

    with input_path.open() as in_file, \
            output_path.open("w") as out_file:

        for line in in_file:
            transformed = line.strip().upper()
            out_file.write(transformed + "\n")


# Check whether a file exists

def create_file_if_missing(path: Path) -> None:
    if path.exists():
        print("File already exists")
    else:
        path.write_text("Hey there\n")


# -----------------------------------------------------------------------------
# 11. JSON
# -----------------------------------------------------------------------------

def write_json(path: Path, data: dict) -> None:
    with path.open("w") as file:
        json.dump(
            data,
            file,
            indent=2,
        )


def read_json(path: Path) -> dict:
    with path.open() as file:
        return json.load(file)


# Convert without writing to a file

json_text = json.dumps(
    {"server": "gpu-1", "load": 80}
)

decoded_data = json.loads(json_text)


# -----------------------------------------------------------------------------
# 12. Classes and magic methods
# -----------------------------------------------------------------------------

class Server:
    def __init__(
        self,
        name: str,
        load: int,
    ) -> None:

        self.name = name
        self.load = load

    def __str__(self) -> str:
        return f"{self.name}: {self.load}%"

    def __repr__(self) -> str:
        return (
            f"Server("
            f"name={self.name!r}, "
            f"load={self.load!r}"
            f")"
        )

    def __iter__(self) -> Iterator[object]:
        yield self.name
        yield self.load

    def health(self) -> str:
        if self.load < 90:
            return "healthy"

        return "overloaded"


# Inheritance

class MaintenanceServer(Server):
    def health(self) -> str:
        return "maintenance"


# Polymorphism

def report_health(server: Server) -> str:
    return server.health()


# -----------------------------------------------------------------------------
# 13. Closures
# -----------------------------------------------------------------------------

def minimum_load(minimum: int):
    """
    The inner function remembers minimum after the
    outer function has finished.
    """

    def check(load: int) -> bool:
        return load >= minimum

    return check


is_high_load = minimum_load(80)

print(is_high_load(95))
# True

print(is_high_load(50))
# False


# -----------------------------------------------------------------------------
# 14. Decorators
# -----------------------------------------------------------------------------

def log_call(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        print(f"Calling {function.__name__}")

        result = function(*args, **kwargs)

        print(f"Result: {result}")

        return result

    return wrapper


@log_call
def add(x: int, y: int) -> int:
    return x + y


# -----------------------------------------------------------------------------
# 15. Custom context managers
# -----------------------------------------------------------------------------

class ManagedResource:
    def __enter__(self):
        print("Opening resource")
        return self

    def __exit__(
        self,
        error_type,
        error,
        traceback,
    ) -> bool:

        print("Closing resource")

        # False means exceptions are not suppressed
        return False


# Generator-based context manager

@contextmanager
def managed_message(message: str):
    print("Starting")

    try:
        yield message

    finally:
        print("Finished")


# -----------------------------------------------------------------------------
# 16. Basic generators
# -----------------------------------------------------------------------------

def generate_numbers(limit: int):
    for number in range(limit):
        yield number


generated = generate_numbers(3)

print(list(generated))
# [0, 1, 2]


# -----------------------------------------------------------------------------
# 17. Combined HackerRank pattern: parse -> count -> sort
# -----------------------------------------------------------------------------

def summarize_logs(
    logs: list[str],
) -> list[tuple[str, int]]:

    statuses = [
        line.split()[1].lower()
        for line in logs
    ]

    counts = Counter(statuses)

    return counts.most_common()


# -----------------------------------------------------------------------------
# 18. Dispatch table
# -----------------------------------------------------------------------------

operations = {
    "add": lambda x, y: x + y,
    "subtract": lambda x, y: x - y,
    "multiply": lambda x, y: x * y,
}

operation = "subtract"

result = operations[operation](10, 4)

print(result)
# 6


# -----------------------------------------------------------------------------
# Run demonstrations
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    print("Parsed:", server, status, usage)
    print("Joined:", joined)
    print("Message:", message)

    print("Comprehension:", large_plus_one)
    print("Squares:", squares)
    print("Enumerated:", indexed_numbers)
    print("Zipped:", paired)

    print("Total:", calculate_total(numbers))
    print("Add all:", add_all(1, 2, 3, 4))

    print(
        describe_server(
            "gpu-1",
            load=80,
            status="healthy",
        )
    )

    print("Servers by load:", servers_by_load)
    print("Scores ranked:", scores_ranked)
    print("Counts:", most_common_levels)
    print("Grouped:", dict(events_by_server))
    print("First queued job:", first_job)

    print("GPU number:", gpu_number)
    print("All numbers:", all_numbers)
    print("Regex replacement:", cleaned_log)

    sample_logs = [
        "gpu-1 ERROR",
        "gpu-2 INFO",
        "gpu-1 ERROR",
    ]

    print(
        "Log summary:",
        summarize_logs(sample_logs),
    )

    production_server = Server(
        "gpu-1",
        95,
    )

    maintenance_server = MaintenanceServer(
        "gpu-2",
        20,
    )

    print(
        production_server,
        report_health(production_server),
    )

    print(
        maintenance_server,
        report_health(maintenance_server),
    )

    print(
        "Server as list:",
        list(production_server),
    )

    print(
        "Decorated result:",
        add(2, 3),
    )

    with ManagedResource() as resource:
        print("Using resource")

    with managed_message(
        "inside context manager"
    ) as context_message:
        print(context_message)