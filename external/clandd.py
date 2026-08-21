# a closure


def enter_some_numbers():
    numbers = []

    def enter_number(x):
        numbers.append(x)
        print(numbers)

    return enter_number

enter_num = enter_some_numbers()
enter_num(2)

# decorator

def wrappy(func):
    def wrapper(a, b):
        func(a, b)
        print("wrapped")


    return wrapper

@wrappy
def combined(a, b):
    print(a + b)

combined(2, 5)

print((lambda x: x + 3)(3))


# class
class Server:
    company = "Fern"

    def __init__(self, name, load):
        self.name = name       # instance attribute
        self.load = load

    def health(self):
        return "healthy" if self.load < 90 else "overloaded"

    def __str__(self):
        return f"{self.name}: {self.load}%"

    def __repr__(self):
        return f"Server(name={self.name!r}, load={self.load!r})"

    def __iter__(self):
        yield self.name
        yield self.load

class MaintenanceServer(Server):
    def __init__(self, name, load, reason):
        super().__init__(name, load)
        self.reason = reason

    def health(self):
        return "maintenance"

#collections

from collections import Counter
a = "aaaaabbcc"
c: Counter[str] = Counter(a)
print(c.most_common(1)[0][0])

listen2 = [2, 5, 6, 6, 6, 2]
counted = Counter(listen2)
print(list(counted.elements()))

print(counted.most_common(2)[1][0])

listen = Counter([2, 5, 6, 6,2])
print(list(listen.elements()))
print(listen.most_common()[-1])
print(listen.most_common())
listen.update([2])
print(listen.most_common())

# context managers trys

