import pathlib
from pathlib import Path


# Learning Python strings

single_quoted = 'Single quoted'
double_quoted = "Double quoted"

print(single_quoted)
print(double_quoted)

# Special characters
print("String with a\nnew line")

# Repeat a string
print(single_quoted * 3)

# Join strings
letters = ["a", "b", "c"]
print("-".join(letters))

# Get the length of a list
print(len(letters))

# Check whether a value is falsy
number = 0

if not number:
    print("Empty")

# Check whether text is absent
sentence = "The dog has spots"

if "brown" not in sentence:
    print("The word 'brown' was not found")

# Split a string
text = "a-b-c"
print(text.split("-"))

# Replace text
new_text = text.replace("a", "b")
print(new_text)

# Remove characters from the right
text_with_trailing_b = "helloBBB"
trimmed_text = text_with_trailing_b.rstrip("B")
print(trimmed_text)

# Check how a string starts
print(new_text.startswith("b"))

# - - -

# Remove trailing characters with rstrip()
text = "adadamaaa"
trimmed_text = text.rstrip("a")

print(text)          # adadamaaa
print(trimmed_text)  # adadam


# Format a number as a percentage
value = 0.22222

print(f"{value:.2%}")  # 22.22%


# Convert text to uppercase
message = "hello"

print(message.upper())  # HELLO


# Use multiple values inside an f-string
print(
    f"Original: {text}, "
    f"trimmed: {trimmed_text}, "
    f"percentage: {value:.2%}, "
    f"uppercase: {message.upper()}"
)


# - - - coroutines and so on generators

def echo():
    print("initialized")
    while True:
        line = (yield)
        print(line)
    
gen = echo()
gen.send(None) # initlizsed
gen.send("hi")
gen.send("Hey")

# with

#problem
# file = open("file.txt", "w")
# file.write("Hey")
# file.close()

# try:
# except:
# finally

# with open("hello.txt", mode="w") as file:
#     if pathlib.Path("./hello.txt").exists():
#         print("exists")
#     else:
#         file.write("Hey there")

    
# with open("input.txt") as in_file, open("output.txt", "w") as out_file:
#     content = in_file.read()
#     transformed = content.upper()
#     out_file.write(transformed)

# with open("input.txt") as file:
#     for line in file:
#         print(line.strip())


# with

# command = input("hey write to me")

# match command:
#     case "red":
#         print("not")
#     case "rev":
#         print("god")
#     case _:
#         print("no good")

# print(repr(Path.cwd()))

def start_programme(data: dict):
    assert isinstance(data, dict), "Invalid"
# start_programme("sad")

print("- - - -")

person = {
    "name": "Adam",
    "age": 25,
    "role": "engineer",
}

print(person["name"])

for keys in person:
    print(keys)

for values in person.values():
    print(values)

words = ["error", "info", "error", "warning"]

counts = {}

for word in words:
    counts[word] = counts.get(word, 0) + 1

print(counts)
# {'error': 2, 'info': 1, 'warning': 1}

from collections import Counter

counts = Counter(words)
print(counts["error"])  # 2

print("Adam sioude")

print 
#dispatch table

functions = {
    "add": lambda x, y: x + y,
    "minus": lambda x, y: x -y
}

print(functions["minus"](2,4))


listen = [1, 3, 4, 5, 6]

listen2 = [x+1 for x in listen if x>3]
# output, in collection, under constraints
print(listen2)


# # #

stringen = "adamsdam"
print(stringen.strip("ad"))
